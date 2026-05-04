<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const views = [
  { id: "answers_export", label: "Answers Export" },
  { id: "scores_contexts", label: "Scores Contexts" },
  { id: "scores_by_driver", label: "Scores By Driver" },
  { id: "org_map", label: "Org Map Explorer" },
  { id: "org_headcount", label: "Org Headcount" },
  { id: "employee_birthdays", label: "Employee Birthdays" },
  { id: "employee_start_dates", label: "Employee Start Dates" },
];

const ORPHANED_MANAGER_ID = "__orphaned__";

const activeView = ref("answers_export");
const limit = ref(50);
const skip = ref(0);
const total = ref(0);
const items = ref([]);
const uniqueEmployees = ref(0);
const employeeCache = ref(new Map());
const employeeErrors = ref(new Map());
const hoverEmployeeId = ref("");
const hoverLoading = ref(false);
const loading = ref(false);
const exportingCsv = ref(false);
const error = ref("");
const driverId = ref("");
const search = ref("");
const employeeId = ref("");
const questionId = ref("");
const minScore = ref("");
const maxScore = ref("");
const answeredFrom = ref("");
const answeredTo = ref("");
const hasComment = ref("");
const department = ref("");
const subDepartment = ref("");
const departmentInput = ref("");
const birthdayDepartmentPick = ref("");
const subDepartmentInput = ref("");
const selectedDepartments = ref([]);
const birthdaySelectedDepartments = ref([]);
const selectedSubDepartments = ref([]);
const managerId = ref("");
const orgHeadcountManagerQuery = ref("");
const orgHeadcountManagerOptions = ref([]);
const orgHeadcountManagerLoading = ref(false);
const grade = ref("");
const impact = ref("");
const timeFrom = ref("");
const timeTo = ref("");
const ANON_EMAIL = "user@pax8.com";
const managerOptions = ref([]);
const managerLoading = ref(false);
const managerCache = ref(new Map());
const departmentOptions = ref([]);
const subDepartmentOptions = ref([]);
const orgMap = ref({ nodes: [], edges: [], stats: {}, rootId: null });
const orgHeadcount = ref({ totalHeadcount: 0, managerCount: 0, rows: [], managers: [], stats: {} });
const birthdayGroups = ref([]);
const birthdaysTotal = ref(0);
const birthdaysStats = ref({ employeesScanned: 0, employeesWithBirthday: 0, source: "employees" });
const birthdayMonth = ref("");
const birthdayNameSearch = ref("");
const employeeStartDates = ref([]);
const startDateSearch = ref("");
const orgMapSearch = ref("");
const debouncedOrgMapSearch = ref("");
const orgMapDepartment = ref("");
const orgMapDepartmentInput = ref("");
const selectedOrgDepartments = ref([]);
const orgMapSubDepartment = ref("");
const orgMapSubDepartmentInput = ref("");
const selectedOrgSubDepartments = ref([]);
const orgMapManagerFocus = ref("");
const orgLayoutMode = ref("hierarchy_tree");
const orgClusterBy = ref("department");
const orgClusterSpread = ref(1.8);
const orgHideUnassigned = ref(true);
const orgTreeSeparateDepartments = ref(true);
const orgHierarchyGroupByDepartment = ref(true);
const orgColorMode = ref("department");
const orgRadialLayerGap = ref(1.2);
const orgTreeSpreadX = ref(2.4);
const orgTreeSpreadY = ref(4.8);
const knnK = ref(5);
const knnProfile = ref("all");
const orgMapZoom = ref(1);
const orgPanX = ref(0);
const orgPanY = ref(0);
const orgCanvasRef = ref(null);
const orgMapContainerRef = ref(null);
const orgFullscreen = ref(false);
const orgDragging = ref(false);
const orgDidDrag = ref(false);
const selectedOrgNodeId = ref("");
let managerRequestId = 0;
let orgSearchDebounceTimer = null;
let orgDragStartX = 0;
let orgDragStartY = 0;
let orgPanStartX = 0;
let orgPanStartY = 0;

const hasPrev = computed(() => skip.value > 0);
const hasNext = computed(() => skip.value + limit.value < total.value);
const pageRange = computed(() => {
  const start = total.value === 0 ? 0 : skip.value + 1;
  const end = Math.min(skip.value + limit.value, total.value);
  return `${start}-${end} of ${total.value}`;
});

const visibleManagerOptions = computed(() =>
  managerOptions.value.filter((manager) => manager.id !== ORPHANED_MANAGER_ID)
);

const selectedOrgNode = computed(() => {
  if (!selectedOrgNodeId.value) return null;
  return orgMap.value.nodes.find((node) => node.id === selectedOrgNodeId.value) || null;
});

const filteredOrgNodes = computed(() => {
  const q = debouncedOrgMapSearch.value.trim().toLowerCase();
  return orgMap.value.nodes.filter((node) => {
    if (orgHideUnassigned.value && (!node.department || String(node.department).trim() === "")) {
      return false;
    }
    if (!q) return true;
    return [node.label, node.id, node.email, node.department, node.subDepartment, node.country, node.title]
      .filter(Boolean)
      .some((v) => String(v).toLowerCase().includes(q));
  });
});

const filteredBirthdayGroups = computed(() => {
  const rawMonth = String(birthdayMonth.value || "").trim();
  const monthFilter = rawMonth ? rawMonth.padStart(2, "0") : "";
  const nameQuery = String(birthdayNameSearch.value || "").trim().toLowerCase();
  const deptFilters = new Set(birthdaySelectedDepartments.value.map((d) => String(d).trim().toLowerCase()).filter(Boolean));

  const out = [];
  for (const group of birthdayGroups.value || []) {
    const deptName = String(group.department || "Unassigned");
    if (deptFilters.size && !deptFilters.has(deptName.toLowerCase())) continue;

    const employees = (group.employees || []).filter((emp) => {
      const b = String(emp.birthday || "");
      const m = b.includes("/") ? b.split("/")[0].padStart(2, "0") : "";
      if (monthFilter && m !== monthFilter) return false;
      if (nameQuery && !String(emp.name || "").toLowerCase().includes(nameQuery)) return false;
      return true;
    });

    if (employees.length) {
      out.push({ ...group, count: employees.length, employees });
    }
  }
  return out;
});

const filteredBirthdaysTotal = computed(() =>
  filteredBirthdayGroups.value.reduce((sum, g) => sum + (g.count || 0), 0)
);

const orgHeadcountVisibleIds = computed(() => {
  const selected = String(managerId.value || "").trim();
  if (!selected) return null;
  const rows = orgHeadcount.value.rows || [];
  const byParent = new Map();
  for (const row of rows) {
    const parent = String(row.managerId || "");
    if (!byParent.has(parent)) byParent.set(parent, []);
    byParent.get(parent).push(String(row.id || ""));
  }
  const visible = new Set([selected]);
  const queue = [selected];
  while (queue.length) {
    const current = queue.shift();
    const kids = byParent.get(current) || [];
    for (const kid of kids) {
      if (!visible.has(kid)) {
        visible.add(kid);
        queue.push(kid);
      }
    }
  }
  return visible;
});

const orgHeadcountRowsVisible = computed(() => {
  const ids = orgHeadcountVisibleIds.value;
  const rows = orgHeadcount.value.rows || [];
  if (!ids) return rows;
  return rows.filter((row) => ids.has(String(row.id || "")));
});

const orgHeadcountManagersVisible = computed(() => {
  const ids = orgHeadcountVisibleIds.value;
  const all = orgHeadcount.value.managers || [];
  if (!ids) return all;
  return all
    .filter((m) => ids.has(String(m.id || "")) && Number(m.directReports || 0) > 0)
    .sort((a, b) => Number(b.teamSizeInScope || 0) - Number(a.teamSizeInScope || 0));
});

function hashSeed(input) {
  const s = String(input || "");
  let h = 2166136261;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h >>> 0);
}

function groupColor(groupKey) {
  // Generate many distinct, deterministic colors so large orgs don't repeat quickly.
  const seed = hashSeed(groupKey || "group");
  const hue = (seed * 137.508) % 360; // golden-angle spread
  const sat = 62 + (seed % 14); // 62-75%
  const light = 52 + ((seed >> 4) % 10); // 52-61%
  return `hsl(${hue.toFixed(1)} ${sat}% ${light}%)`;
}

function clusterKeyForNode(node) {
  if (orgClusterBy.value === "subDepartment") return node.subDepartment || node.department || "Unassigned";
  if (orgClusterBy.value === "manager") return node.managerId || "No manager";
  if (orgClusterBy.value === "country") return node.country || "Unknown country";
  if (orgClusterBy.value === "title") return node.title || "No title";
  return node.department || "Unassigned";
}

const clusterNodes = computed(() => {
  const groups = new Map();
  for (const node of filteredOrgNodes.value) {
    const key = clusterKeyForNode(node);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(node);
  }

  const groupEntries = Array.from(groups.entries()).sort((a, b) => b[1].length - a[1].length);
  const groupCount = Math.max(1, groupEntries.length);
  const centerRadius = 260 + orgClusterSpread.value * 260;
  const out = [];

  groupEntries.forEach(([groupKey, nodes], gi) => {
    const theta = (2 * Math.PI * gi) / groupCount;
    const cx = Math.cos(theta) * centerRadius;
    const cy = Math.sin(theta) * centerRadius;

    nodes.forEach((node) => {
      const seed = hashSeed(`${groupKey}:${node.id}`);
      const angle = ((seed % 3600) / 3600) * 2 * Math.PI;
      const localR = 16 + (seed % 130) + Math.sqrt(nodes.length) * 5;
      out.push({
        ...node,
        x: cx + Math.cos(angle) * localR,
        y: cy + Math.sin(angle) * localR,
        groupKey,
        groupColor: groupColor(groupKey),
      });
    });
  });

  return out;
});

const clusterGroups = computed(() => {
  const groups = new Map();
  for (const node of clusterNodes.value) {
    const key = node.groupKey || "Unassigned";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(node);
  }
  const out = [];
  groups.forEach((nodes, key) => {
    const count = nodes.length;
    const cx = nodes.reduce((sum, n) => sum + n.x, 0) / Math.max(count, 1);
    const cy = nodes.reduce((sum, n) => sum + n.y, 0) / Math.max(count, 1);
    let maxR = 30;
    for (const n of nodes) {
      const dx = n.x - cx;
      const dy = n.y - cy;
      maxR = Math.max(maxR, Math.sqrt(dx * dx + dy * dy));
    }
    out.push({ key, count, cx, cy, r: maxR + 24, color: groupColor(key) });
  });
  return out;
});

const treeNodes = computed(() => {
  const nodes = filteredOrgNodes.value;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const children = new Map();
  nodes.forEach((n) => children.set(n.id, []));

  const roots = [];
  for (const n of nodes) {
    if (n.parentId && byId.has(n.parentId)) {
      children.get(n.parentId).push(n.id);
    } else {
      roots.push(n.id);
    }
  }

  roots.sort();
  children.forEach((arr) => arr.sort());

  let nextX = 0;
  const pos = new Map();

  function place(nodeId) {
    const kids = children.get(nodeId) || [];
    let x;
    if (!kids.length) {
      x = nextX;
      nextX += 1;
    } else {
      kids.forEach((kid) => place(kid));
      const first = pos.get(kids[0]);
      const last = pos.get(kids[kids.length - 1]);
      x = ((first?.x || 0) + (last?.x || 0)) / 2;
    }
    pos.set(nodeId, { x });
  }

  roots.forEach((rootId) => place(rootId));

  const xGap = 52 + orgTreeSpreadX.value * 56;
  const yGap = 220 + orgTreeSpreadY.value * 220;
  const values = Array.from(pos.values());
  const minX = values.length ? Math.min(...values.map((v) => v.x)) : 0;
  const maxX = values.length ? Math.max(...values.map((v) => v.x)) : 0;
  const centerX = (minX + maxX) / 2;

  const deptList = Array.from(
    new Set(nodes.map((n) => String(n.department || n.subDepartment || "Unassigned").trim()))
  ).sort();
  const deptIndex = new Map(deptList.map((d, i) => [d, i]));
  const deptGap = 260 + orgTreeSpreadY.value * 180;

  return nodes.map((n) => {
    const p = pos.get(n.id) || { x: 0 };
    const d = Number.isFinite(Number(n.depth)) ? Number(n.depth) : 0;
    const deptKey = String(n.department || n.subDepartment || "Unassigned").trim();
    const deptOffset = orgTreeSeparateDepartments.value ? (deptIndex.get(deptKey) || 0) * deptGap : 0;
    return {
      ...n,
      x: (p.x - centerX) * xGap,
      y: d * yGap + deptOffset,
    };
  });
});

const radialDepartmentNodes = computed(() => {
  const nodes = filteredOrgNodes.value;
  const deptKeys = Array.from(
    new Set(nodes.map((n) => String(n.department || n.subDepartment || "Unassigned").trim() || "Unassigned"))
  ).sort();
  const deptCount = Math.max(1, deptKeys.length);
  const deptIndex = new Map(deptKeys.map((k, i) => [k, i]));

  return nodes.map((n) => {
    const d = Math.max(0, Number.isFinite(Number(n.depth)) ? Number(n.depth) : 0);
    if (d === 0) {
      return { ...n, x: 0, y: 0 };
    }

    const deptKey = String(n.department || n.subDepartment || "Unassigned").trim() || "Unassigned";
    const idx = deptIndex.get(deptKey) || 0;
    const baseAngle = (2 * Math.PI * idx) / deptCount;
    const sectorWidth = ((2 * Math.PI) / deptCount) * 0.82;
    const seed = hashSeed(`${deptKey}:${n.id}`);
    const offset = ((seed % 1000) / 999 - 0.5) * sectorWidth;
    const angle = baseAngle + offset;

    const radius = d * (120 + orgRadialLayerGap.value * 95);
    return {
      ...n,
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    };
  });
});

const nodesToRender = computed(() => {
  if (orgLayoutMode.value === "cluster" || orgLayoutMode.value === "knn") return clusterNodes.value;
  if (orgLayoutMode.value === "hierarchy_tree") return treeNodes.value;
  if (orgLayoutMode.value === "hierarchy" && orgHierarchyGroupByDepartment.value) return radialDepartmentNodes.value;
  return filteredOrgNodes.value;
});
const orgNodeById = computed(() => new Map(nodesToRender.value.map((n) => [n.id, n])));
const filteredOrgNodeIds = computed(() => new Set(nodesToRender.value.map((n) => n.id)));
const filteredOrgEdges = computed(() =>
  orgMap.value.edges.filter(
    (edge) => filteredOrgNodeIds.value.has(edge.source) && filteredOrgNodeIds.value.has(edge.target)
  )
);
function knnTokens(node) {
  const tokens = [];
  const add = (k, v) => {
    if (v === undefined || v === null) return;
    const s = String(v).trim().toLowerCase();
    if (!s) return;
    tokens.push(`${k}:${s}`);
  };

  if (knnProfile.value === "all" || knnProfile.value === "org") {
    add("department", node.department);
    add("subDepartment", node.subDepartment);
    add("manager", node.managerId);
    add("depth", node.depth);
  }
  if (knnProfile.value === "all" || knnProfile.value === "geo") {
    add("country", node.country);
  }
  if (knnProfile.value === "all" || knnProfile.value === "title") {
    add("title", node.title);
  }
  return new Set(tokens);
}

function knnSimilarity(a, b) {
  const ta = knnTokens(a);
  const tb = knnTokens(b);
  const union = new Set([...ta, ...tb]);
  if (!union.size) return 0;
  let inter = 0;
  ta.forEach((t) => {
    if (tb.has(t)) inter += 1;
  });
  return inter / union.size;
}

const knnMap = computed(() => {
  if (orgLayoutMode.value !== "knn") return new Map();
  const map = new Map();
  const nodes = nodesToRender.value;
  const k = Math.max(1, Math.min(20, Number(knnK.value) || 5));

  nodes.forEach((node) => {
    const ranked = nodes
      .filter((other) => other.id !== node.id)
      .map((other) => ({ id: other.id, score: knnSimilarity(node, other) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, k);
    map.set(node.id, ranked);
  });
  return map;
});

const knnEdges = computed(() => {
  if (orgLayoutMode.value !== "knn") return [];
  const out = [];
  const dedupe = new Set();
  knnMap.value.forEach((neighbors, sourceId) => {
    neighbors.forEach((n) => {
      const key = [sourceId, n.id].sort().join("::");
      if (dedupe.has(key)) return;
      dedupe.add(key);
      out.push({ source: sourceId, target: n.id, score: n.score });
    });
  });
  return out;
});

const edgesToRender = computed(() => {
  if (orgLayoutMode.value === "cluster") return [];
  if (orgLayoutMode.value === "knn") return knnEdges.value;
  return filteredOrgEdges.value;
});
const treeDepartmentOutlines = computed(() => {
  if (orgLayoutMode.value !== "hierarchy_tree") return [];

  const deptSet = new Set(
    nodesToRender.value
      .map((n) => (n.department || "").trim())
      .filter((v) => v !== "")
  );
  const preferSubDept = deptSet.size <= 1;

  const groups = new Map();
  for (const n of nodesToRender.value) {
    const keyRaw = preferSubDept ? (n.subDepartment || n.department || "") : (n.department || "");
    const key = String(keyRaw || "").trim();
    if (!key) continue;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(n);
  }

  const outlines = [];
  groups.forEach((nodes, key) => {
    if (!nodes.length) return;
    const xs = nodes.map((n) => n.x || 0);
    const ys = nodes.map((n) => n.y || 0);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    outlines.push({
      key,
      color: groupColor(key),
      x: minX - 36,
      y: minY - 32,
      w: Math.max(72, maxX - minX + 72),
      h: Math.max(72, maxY - minY + 64),
      count: nodes.length,
    });
  });
  return outlines.sort((a, b) => a.key.localeCompare(b.key));
});

const radialDepartmentLegend = computed(() => {
  if (!(orgLayoutMode.value === "hierarchy" && orgHierarchyGroupByDepartment.value)) return [];
  const counts = new Map();
  for (const node of nodesToRender.value) {
    const key = String(node.department || node.subDepartment || "Unassigned").trim() || "Unassigned";
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([key, count]) => ({ key, count, color: groupColor(key) }))
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
});

const orgSelectedChainIds = computed(() => {
  if (!selectedOrgNodeId.value) return new Set();
  return new Set(orgParentChain(selectedOrgNodeId.value).map((n) => n.id));
});
const orgSelectedChainEdgeKeys = computed(() => {
  const keys = new Set();
  const chain = orgParentChain(selectedOrgNodeId.value || "");
  for (let i = 0; i < chain.length - 1; i += 1) {
    const child = chain[i];
    const parent = chain[i + 1];
    keys.add(`${parent.id}-${child.id}`);
  }
  return keys;
});

const selectedKnnNeighbors = computed(() => {
  const out = new Set();
  const selectedId = selectedOrgNodeId.value;
  if (!selectedId || orgLayoutMode.value !== "knn") return out;
  for (const n of knnMap.value.get(selectedId) || []) {
    out.add(n.id);
  }
  return out;
});

function orgBaseX() {
  return 700;
}

function orgBaseY() {
  return orgLayoutMode.value === "hierarchy_tree" ? 110 : 700;
}

function orgNodeX(node) {
  return orgBaseX() + orgPanX.value + (node.x || 0) * orgMapZoom.value;
}

function orgNodeY(node) {
  return orgBaseY() + orgPanY.value + (node.y || 0) * orgMapZoom.value;
}

function orgNodeRadius(node) {
  const isSelected = selectedOrgNodeId.value === node.id;
  const isKnnNeighbor = orgLayoutMode.value === "knn" && selectedKnnNeighbors.value.has(node.id);
  const base = isSelected ? 10 : (isKnnNeighbor ? 8 : 7);
  return Math.max(4, base + Math.min(4, (node.directReports || 0) / 5));
}

function scoreColor(score) {
  if (score === undefined || score === null || score === "") return "#94a3b8";
  const value = Number(score);
  if (!Number.isFinite(value)) return "#94a3b8";
  if (value >= 8) return "#22c55e";
  if (value >= 6) return "#84cc16";
  if (value >= 4) return "#f59e0b";
  return "#ef4444";
}

function orgMetricValue(node, key) {
  const metrics = node.metrics || {};
  const metricValue = metrics[key];
  if (metricValue !== undefined && metricValue !== null && metricValue !== "") return metricValue;
  const nodeValue = node[key];
  if (nodeValue !== undefined && nodeValue !== null && nodeValue !== "") return nodeValue;
  return undefined;
}

function showOrgLabels() {
  if (orgLayoutMode.value === "hierarchy_tree") return orgMapZoom.value >= 1;
  return orgMapZoom.value >= 1.5;
}

function orgNodeFill(node) {
  if (selectedOrgNodeId.value === node.id) return "#22c55e";
  if (orgColorMode.value === "engagement") return scoreColor(orgMetricValue(node, "engagement"));
  if (orgLayoutMode.value === "knn") {
    if (selectedKnnNeighbors.value.has(node.id)) return "#f59e0b";
    return node.groupColor || groupColor(clusterKeyForNode(node));
  }
  if (orgLayoutMode.value === "cluster") return node.groupColor || groupColor(clusterKeyForNode(node));
  if (orgLayoutMode.value === "hierarchy" && orgHierarchyGroupByDepartment.value) {
    return groupColor(node.department || node.subDepartment || "Unassigned");
  }
  if (orgSelectedChainIds.value.has(node.id)) return "#38bdf8";
  return "#60a5fa";
}

function orgParentChain(nodeId) {
  const byId = new Map(orgMap.value.nodes.map((n) => [n.id, n]));
  const chain = [];
  let current = byId.get(nodeId);
  const guard = new Set();
  while (current && !guard.has(current.id)) {
    guard.add(current.id);
    chain.push(current);
    if (!current.parentId) break;
    current = byId.get(current.parentId);
  }
  return chain;
}

function dateStartIso(value) {
  const date = String(value || "").trim();
  return date ? `${date}T00:00:00.000Z` : "";
}

function dateEndIso(value) {
  const date = String(value || "").trim();
  return date ? `${date}T23:59:59.999Z` : "";
}

function buildAnswersParams({ includePaging = true, skipOverride, limitOverride, includeManager = true } = {}) {
  const params = new URLSearchParams();
  if (includePaging) {
    params.set("limit", String(limitOverride ?? limit.value));
    params.set("skip", String(skipOverride ?? skip.value));
  }
  if (search.value.trim()) params.set("search", search.value.trim());
  if (employeeId.value.trim()) params.set("employee_id", employeeId.value.trim());
  if (questionId.value.trim()) params.set("question_id", questionId.value.trim());
  if (minScore.value.trim()) params.set("min_score", minScore.value.trim());
  if (maxScore.value.trim()) params.set("max_score", maxScore.value.trim());
  if (answeredFrom.value.trim()) params.set("answered_from", dateStartIso(answeredFrom.value));
  if (answeredTo.value.trim()) params.set("answered_to", dateEndIso(answeredTo.value));
  if (hasComment.value) params.set("has_comment", hasComment.value);
  if (department.value.trim()) params.set("department", department.value.trim());
  if (subDepartment.value.trim()) params.set("sub_department", subDepartment.value.trim());
  if (includeManager && managerId.value.trim()) params.set("manager_id", managerId.value.trim());
  return params;
}

function csvCell(value) {
  const text = value == null ? "" : String(value);
  if (/[,"\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function answersToCsv(rows) {
  const headers = [
    "answerId",
    "answerScore",
    "questionId",
    "questionText",
    "answerComment",
    "responseAnsweredAt",
    "department",
    "subDepartment",
    "country",
  ];

  const lines = [headers.join(",")];
  for (const item of rows) {
    const employeeIdValue = item?.attributes?.employeeId || "";
    const record = employeeRecord(employeeIdValue);
    const line = [
      item?.attributes?.answerId || item?._id || "",
      item?.attributes?.answerScore ?? "",
      item?.attributes?.questionId ?? "",
      item?.attributes?.questionText || "",
      item?.attributes?.answerComment || "",
      item?.attributes?.responseAnsweredAt || "",
      record?.attributes?.Department || record?.attributes?.department || "",
      record?.attributes?.["Sub-Department"] || record?.attributes?.sub_department || record?.attributes?.["sub-department"] || "",
      record?.attributes?.Country || record?.attributes?.country || "",
    ];
    lines.push(line.map(csvCell).join(","));
  }

  return lines.join("\n");
}

async function exportFilteredAnswersCsv() {
  if (activeView.value !== "answers_export" || exportingCsv.value) return;
  exportingCsv.value = true;
  error.value = "";
  try {
    const pageSize = 500;
    let cursor = 0;
    let expectedTotal = null;
    const allItems = [];

    while (expectedTotal === null || cursor < expectedTotal) {
      const params = buildAnswersParams({ includePaging: true, skipOverride: cursor, limitOverride: pageSize });
      const res = await fetch(`${API_BASE}/answers_export?${params.toString()}`);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      const chunk = payload.items || [];
      if (expectedTotal === null) expectedTotal = payload.total || 0;
      allItems.push(...chunk);
      if (!chunk.length) break;
      cursor += chunk.length;
    }

    const employeeIds = Array.from(new Set(allItems.map((it) => it?.attributes?.employeeId).filter(Boolean)));
    await Promise.all(employeeIds.map((id) => fetchEmployeeCached(id, { silent: true })));

    const csv = answersToCsv(allItems);
    const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `answers-export-${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    exportingCsv.value = false;
  }
}

async function exportManagerQuestionCsv() {
  if (activeView.value !== "answers_export" || exportingCsv.value) return;
  if (!answeredFrom.value.trim() || !answeredTo.value.trim()) {
    error.value = "Set Answered from and Answered to before generating the manager question CSV.";
    return;
  }
  exportingCsv.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams();
    params.set("start_date", answeredFrom.value.trim());
    params.set("end_date", answeredTo.value.trim());
    if (department.value.trim()) params.set("department", department.value.trim());
    if (subDepartment.value.trim()) params.set("sub_department", subDepartment.value.trim());
    if (managerId.value.trim()) params.set("manager_id", managerId.value.trim());

    const res = await fetch(`${API_BASE}/answers_export/manager_question_csv?${params.toString()}`);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `manager-question-export-${answeredFrom.value}-to-${answeredTo.value}.csv`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    exportingCsv.value = false;
  }
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({
      limit: String(limit.value),
      skip: String(skip.value),
    });

    if (activeView.value === "org_map") {
      const orgParams = new URLSearchParams();
      if (orgMapDepartment.value.trim()) orgParams.set("department", orgMapDepartment.value.trim());
      if (orgMapSubDepartment.value.trim()) orgParams.set("sub_department", orgMapSubDepartment.value.trim());
      if (orgMapManagerFocus.value.trim()) orgParams.set("manager_id", orgMapManagerFocus.value.trim());
      const res = await fetch(`${API_BASE}/org_map?${orgParams.toString()}`);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      orgMap.value = {
        nodes: payload.nodes || [],
        edges: payload.edges || [],
        stats: payload.stats || {},
        rootId: payload.rootId || null,
      };
      birthdayGroups.value = [];
      birthdaysTotal.value = 0;
      birthdaysStats.value = { employeesScanned: 0, employeesWithBirthday: 0, source: "employees" };
      items.value = [];
      total.value = orgMap.value.nodes.length;
      uniqueEmployees.value = orgMap.value.nodes.length;
      if (!selectedOrgNodeId.value && orgMap.value.rootId) {
        selectedOrgNodeId.value = orgMap.value.rootId;
      }
      return;
    }

    if (activeView.value === "employee_birthdays") {
      const res = await fetch(`${API_BASE}/employees/birthdays`);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      birthdayGroups.value = payload.departments || [];
      birthdaysTotal.value = payload.total || 0;
      birthdaysStats.value = payload.stats || { employeesScanned: 0, employeesWithBirthday: 0, source: "employees" };
      employeeStartDates.value = [];
      items.value = [];
      total.value = birthdaysTotal.value;
      uniqueEmployees.value = birthdaysTotal.value;
      return;
    }

    if (activeView.value === "employee_start_dates") {
      const startParams = new URLSearchParams({
        limit: String(limit.value),
        skip: String(skip.value),
      });
      if (department.value.trim()) startParams.set("department", department.value.trim());
      if (subDepartment.value.trim()) startParams.set("sub_department", subDepartment.value.trim());
      if (managerId.value.trim()) startParams.set("manager_id", managerId.value.trim());
      if (startDateSearch.value.trim()) startParams.set("search", startDateSearch.value.trim());
      const res = await fetch(`${API_BASE}/employees/start-dates?${startParams.toString()}`);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      employeeStartDates.value = payload.items || [];
      birthdayGroups.value = [];
      birthdaysTotal.value = 0;
      birthdaysStats.value = { employeesScanned: 0, employeesWithBirthday: 0, source: "employees" };
      items.value = [];
      total.value = payload.total || 0;
      uniqueEmployees.value = payload.unique_employees || payload.total || 0;
      return;
    }

    if (activeView.value === "org_headcount") {
      const hcParams = new URLSearchParams();
      if (department.value.trim()) hcParams.set("department", department.value.trim());
      if (subDepartment.value.trim()) hcParams.set("sub_department", subDepartment.value.trim());
      const res = await fetch(`${API_BASE}/org_headcount?${hcParams.toString()}`);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      orgHeadcount.value = {
        totalHeadcount: payload.totalHeadcount || 0,
        managerCount: payload.managerCount || 0,
        rows: payload.rows || [],
        managers: payload.managers || [],
        stats: payload.stats || {},
      };
      orgHeadcountManagerOptions.value = (payload.managers || []).map((m) => ({
        id: String(m.id || ""),
        name: m.name || m.id || "",
        label: `${m.name || m.id || "Unknown"} (${m.id || ""})`,
      })).filter((m) => m.id);
      syncOrgHeadcountManagerSelection();
      items.value = [];
      total.value = orgHeadcount.value.totalHeadcount;
      uniqueEmployees.value = orgHeadcount.value.totalHeadcount;
      return;
    }
    if (activeView.value === "answers_export") {
      if (search.value.trim()) params.set("search", search.value.trim());
      if (employeeId.value.trim()) params.set("employee_id", employeeId.value.trim());
      if (questionId.value.trim()) params.set("question_id", questionId.value.trim());
      if (minScore.value.trim()) params.set("min_score", minScore.value.trim());
      if (maxScore.value.trim()) params.set("max_score", maxScore.value.trim());
      if (answeredFrom.value.trim()) params.set("answered_from", dateStartIso(answeredFrom.value));
      if (answeredTo.value.trim()) params.set("answered_to", dateEndIso(answeredTo.value));
      if (hasComment.value) params.set("has_comment", hasComment.value);
      if (department.value.trim()) params.set("department", department.value.trim());
      if (subDepartment.value.trim()) params.set("sub_department", subDepartment.value.trim());
      if (managerId.value.trim()) params.set("manager_id", managerId.value.trim());
    }
    if (activeView.value === "scores_contexts") {
      if (grade.value.trim()) params.set("grade", grade.value.trim());
      if (impact.value.trim()) params.set("impact", impact.value.trim());
      if (timeFrom.value.trim()) params.set("time_from", timeFrom.value.trim());
      if (timeTo.value.trim()) params.set("time_to", timeTo.value.trim());
      if (department.value.trim()) params.set("department", department.value.trim());
      if (subDepartment.value.trim()) params.set("sub_department", subDepartment.value.trim());
      if (managerId.value.trim()) params.set("manager_id", managerId.value.trim());
    }
    if (activeView.value === "scores_by_driver") {
      if (driverId.value.trim()) params.set("driver_id", driverId.value.trim());
      if (grade.value.trim()) params.set("grade", grade.value.trim());
      if (timeFrom.value.trim()) params.set("time_from", timeFrom.value.trim());
      if (timeTo.value.trim()) params.set("time_to", timeTo.value.trim());
      if (department.value.trim()) params.set("department", department.value.trim());
      if (subDepartment.value.trim()) params.set("sub_department", subDepartment.value.trim());
      if (managerId.value.trim()) params.set("manager_id", managerId.value.trim());
    }
    const res = await fetch(`${API_BASE}/${activeView.value}?${params.toString()}`);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    const payload = await res.json();
    items.value = payload.items || [];
    total.value = payload.total || 0;
    uniqueEmployees.value = payload.unique_employees || 0;
    if (activeView.value === "answers_export") {
      updateManagerOptions();
    } else {
      managerOptions.value = [];
      managerLoading.value = false;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
    items.value = [];
    birthdayGroups.value = [];
    birthdaysTotal.value = 0;
    birthdaysStats.value = { employeesScanned: 0, employeesWithBirthday: 0, source: "employees" };
    employeeStartDates.value = [];
    orgHeadcount.value = { totalHeadcount: 0, managerCount: 0, rows: [], managers: [], stats: {} };
    total.value = 0;
    uniqueEmployees.value = 0;
    managerOptions.value = [];
    managerLoading.value = false;
  } finally {
    loading.value = false;
  }
}

async function fetchEmployeeCached(employeeIdValue, { silent = false } = {}) {
  if (!employeeIdValue) return null;
  if (employeeCache.value.has(employeeIdValue)) {
    return employeeCache.value.get(employeeIdValue);
  }
  if (!silent) {
    hoverLoading.value = true;
  }
  employeeErrors.value.delete(employeeIdValue);
  try {
    const res = await fetch(`${API_BASE}/employees/${employeeIdValue}`);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    const payload = await res.json();
    const employee = payload.employee || null;
    employeeCache.value.set(employeeIdValue, employee);
    return employee;
  } catch (err) {
    employeeErrors.value.set(
      employeeIdValue,
      err instanceof Error ? err.message : String(err)
    );
    return null;
  } finally {
    if (!silent) {
      hoverLoading.value = false;
    }
  }
}

async function onEmailHover(employeeIdValue) {
  if (!employeeIdValue) return;
  hoverEmployeeId.value = String(employeeIdValue);
  await fetchEmployeeCached(employeeIdValue);
}

function employeeRecord(employeeIdValue) {
  return employeeCache.value.get(employeeIdValue);
}

function employeeAttr(employeeIdValue, keys) {
  const employee = employeeRecord(employeeIdValue);
  const attrs = employee?.attributes || {};
  for (const key of keys) {
    const value = attrs[key];
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      return value;
    }
  }
  return "—";
}

function employeeManagerId(employeeIdValue) {
  const employee = employeeRecord(employeeIdValue);
  return (
    employee?.relationships?.Manager?.data?.id ||
    employee?.relationships?.manager?.data?.id ||
    employee?.attributes?.manager?.data?.id ||
    "—"
  );
}

function displayEmail() {
  return ANON_EMAIL;
}

function answerScoreValue(item) {
  const raw = item?.attributes?.answerScore;
  const score = Number(raw);
  return Number.isFinite(score) ? score : null;
}

function answerScoreClass(item) {
  const score = answerScoreValue(item);
  if (score == null) return "score-neutral";
  if (score >= 8) return "score-good";
  if (score >= 5) return "score-mid";
  return "score-low";
}

function answerCardClass(item) {
  if (activeView.value !== "answers_export") return "";
  const score = answerScoreValue(item);
  if (score == null) return "";
  return score <= 4 ? "card-low-sentiment" : "";
}

function addChip(inputRef, listRef) {
  const value = String(inputRef.value || "").trim();
  if (!value) return;
  if (!listRef.value.includes(value)) listRef.value.push(value);
  inputRef.value = "";
}

function removeChip(listRef, value) {
  listRef.value = listRef.value.filter((item) => item !== value);
}

function addSelectedDepartment() {
  const value = String(birthdayDepartmentPick.value || "").trim();
  if (!value) return;
  if (!birthdaySelectedDepartments.value.includes(value)) birthdaySelectedDepartments.value.push(value);
}

function resetBirthdayFilters() {
  birthdaySelectedDepartments.value = [];
  birthdayMonth.value = "";
  birthdayNameSearch.value = "";
  birthdayDepartmentPick.value = "";
}

function onAnswersManagerChange() {
  if (managerId.value === ORPHANED_MANAGER_ID && !hasComment.value) {
    hasComment.value = "true";
  }
}

function syncOrgHeadcountManagerSelection() {
  const q = orgHeadcountManagerQuery.value.trim();
  if (!q) {
    managerId.value = "";
    return;
  }
  const exact = orgHeadcountManagerOptions.value.find((opt) => opt.label === q || String(opt.id) === q);
  managerId.value = exact ? String(exact.id) : "";
}

function updateOrgHeadcountManagerOptions() {
  if (activeView.value !== "org_headcount") return;
  orgHeadcountManagerLoading.value = false;
  orgHeadcountManagerOptions.value = (orgHeadcount.value.managers || []).map((m) => ({
    id: String(m.id || ""),
    name: m.name || m.id || "",
    label: `${m.name || m.id || "Unknown"} (${m.id || ""})`,
  })).filter((m) => m.id);
  syncOrgHeadcountManagerSelection();
}

async function updateManagerOptions() {
  if (activeView.value !== "answers_export") {
    managerOptions.value = [];
    managerLoading.value = false;
    return;
  }
  const requestId = ++managerRequestId;
  managerLoading.value = true;
  try {
    const params = new URLSearchParams();
    if (search.value.trim()) params.set("search", search.value.trim());
    if (employeeId.value.trim()) params.set("employee_id", employeeId.value.trim());
    if (questionId.value.trim()) params.set("question_id", questionId.value.trim());
    if (minScore.value.trim()) params.set("min_score", minScore.value.trim());
    if (maxScore.value.trim()) params.set("max_score", maxScore.value.trim());
    if (answeredFrom.value.trim()) params.set("answered_from", dateStartIso(answeredFrom.value));
    if (answeredTo.value.trim()) params.set("answered_to", dateEndIso(answeredTo.value));
    if (hasComment.value) params.set("has_comment", hasComment.value);
    if (department.value.trim()) params.set("department", department.value.trim());
    if (subDepartment.value.trim()) params.set("sub_department", subDepartment.value.trim());
    const cacheKey = params.toString();
    if (managerCache.value.has(cacheKey)) {
      managerOptions.value = managerCache.value.get(cacheKey);
      return;
    }
    const res = await fetch(`${API_BASE}/answers_export/managers?${cacheKey}`);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    const payload = await res.json();
    if (requestId !== managerRequestId) {
      return;
    }
    managerOptions.value = payload.items || [];
    managerCache.value.set(cacheKey, managerOptions.value);
  } catch (err) {
    managerOptions.value = [];
  } finally {
    if (requestId === managerRequestId) {
      managerLoading.value = false;
    }
  }
}


async function loadEmployeeFacets() {
  try {
    const res = await fetch(`${API_BASE}/employees/facets`);
    if (!res.ok) return;
    const payload = await res.json();
    departmentOptions.value = payload.departments || [];
    subDepartmentOptions.value = payload.sub_departments || [];
  } catch (_err) {
    departmentOptions.value = [];
    subDepartmentOptions.value = [];
  }
}

function resetAndLoad() {
  skip.value = 0;
  load();
}

function loadPeopleOrgPreset() {
  activeView.value = "org_map";
  selectedOrgDepartments.value = ["General and Administrative"];
  selectedOrgSubDepartments.value = ["People"];
  orgMapDepartment.value = "General and Administrative";
  orgMapSubDepartment.value = "People";
  orgMapManagerFocus.value = "";
  orgLayoutMode.value = "hierarchy_tree";
  orgTreeSeparateDepartments.value = false;
  orgColorMode.value = "department";
  selectedOrgNodeId.value = "";
  resetOrgPan();
  resetAndLoad();
}

function focusOnSelectedManager() {
  if (!selectedOrgNodeId.value) return;
  orgMapManagerFocus.value = selectedOrgNodeId.value;
  resetAndLoad();
}

function clearOrgFocus() {
  orgMapManagerFocus.value = "";
  resetAndLoad();
}

function resetOrgPan() {
  orgPanX.value = 0;
  orgPanY.value = 0;
}

function onFullscreenChange() {
  orgFullscreen.value = document.fullscreenElement === orgMapContainerRef.value;
}

async function toggleOrgFullscreen() {
  const target = orgMapContainerRef.value;
  if (!target) return;

  if (document.fullscreenElement === target) {
    await document.exitFullscreen();
    return;
  }

  if (document.fullscreenElement) {
    await document.exitFullscreen();
  }
  await target.requestFullscreen();
}

function onOrgPointerDown(event) {
  if (event.button !== 0) return;
  orgDragging.value = true;
  orgDidDrag.value = false;
  orgDragStartX = event.clientX;
  orgDragStartY = event.clientY;
  orgPanStartX = orgPanX.value;
  orgPanStartY = orgPanY.value;
}

function onOrgPointerMove(event) {
  if (!orgDragging.value) return;
  const dx = event.clientX - orgDragStartX;
  const dy = event.clientY - orgDragStartY;
  if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
    orgDidDrag.value = true;
  }
  orgPanX.value = orgPanStartX + dx;
  orgPanY.value = orgPanStartY + dy;
}

function onOrgPointerUp() {
  orgDragging.value = false;
  setTimeout(() => {
    orgDidDrag.value = false;
  }, 0);
}

function clampZoom(value) {
  // lower bound only; no upper cap so zoom-in is effectively unbounded.
  return Math.max(0.05, value);
}

function onOrgWheel(event) {
  if (activeView.value !== "org_map") return;
  event.preventDefault();

  const svg = orgCanvasRef.value;
  if (!svg) return;

  const rect = svg.getBoundingClientRect();
  const pointerX = event.clientX - rect.left;
  const pointerY = event.clientY - rect.top;

  const oldZoom = orgMapZoom.value;
  const zoomFactor = event.deltaY < 0 ? 1.1 : 0.9;
  const newZoom = clampZoom(oldZoom * zoomFactor);
  if (newZoom === oldZoom) return;

  const bx = orgBaseX();
  const by = orgBaseY();
  const worldX = (pointerX - bx - orgPanX.value) / oldZoom;
  const worldY = (pointerY - by - orgPanY.value) / oldZoom;

  orgMapZoom.value = newZoom;
  orgPanX.value = pointerX - bx - worldX * newZoom;
  orgPanY.value = pointerY - by - worldY * newZoom;
}

function onOrgNodeClick(nodeId) {
  if (orgDidDrag.value) return;
  selectedOrgNodeId.value = nodeId;

  // In focused mode, clicking a node drills into that manager's subtree
  // so their direct/indirect reports become the visible graph.
  if (orgMapManagerFocus.value && orgMapManagerFocus.value !== nodeId) {
    orgMapManagerFocus.value = nodeId;
    resetAndLoad();
  }
}

function prevPage() {
  if (hasPrev.value) {
    skip.value = Math.max(0, skip.value - limit.value);
    load();
  }
}

function nextPage() {
  if (hasNext.value) {
    skip.value += limit.value;
    load();
  }
}

watch(selectedDepartments, (vals) => {
  department.value = vals.join(",");
});
watch(selectedSubDepartments, (vals) => {
  subDepartment.value = vals.join(",");
});
watch(selectedOrgDepartments, (vals) => {
  orgMapDepartment.value = vals.join(",");
});
watch(selectedOrgSubDepartments, (vals) => {
  orgMapSubDepartment.value = vals.join(",");
});

watch(orgMapSearch, (value) => {
  if (orgSearchDebounceTimer) {
    clearTimeout(orgSearchDebounceTimer);
  }
  orgSearchDebounceTimer = setTimeout(() => {
    debouncedOrgMapSearch.value = value;
  }, 250);
});

watch(activeView, () => {
  if (activeView.value !== "answers_export" && managerId.value === ORPHANED_MANAGER_ID) {
    managerId.value = "";
  }
  resetAndLoad();
});
watch(limit, () => resetAndLoad());

onMounted(() => {
  document.addEventListener("fullscreenchange", onFullscreenChange);
  debouncedOrgMapSearch.value = orgMapSearch.value;
  loadEmployeeFacets();
  load();
});

onBeforeUnmount(() => {
  document.removeEventListener("fullscreenchange", onFullscreenChange);
  if (orgSearchDebounceTimer) clearTimeout(orgSearchDebounceTimer);
});
</script>

<template>
  <div class="page">
    <header class="header">
      <div>
        <h1>Peakon Browser</h1>
        <p class="subtle">API: {{ API_BASE }}</p>
      </div>
      <div class="controls">
        <label>
          Page size
          <select v-model.number="limit">
            <option :value="25">25</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
            <option :value="200">200</option>
          </select>
        </label>
      </div>
    </header>

    <nav class="tabs">
      <button
        v-for="view in views"
        :key="view.id"
        :class="['tab', { active: activeView === view.id }]"
        @click="activeView = view.id"
      >
        {{ view.label }}
      </button>
    </nav>

    <section class="filters">
      <div v-if="activeView === 'answers_export'" class="filters-row">
        <label>
          Search text
          <input v-model="search" placeholder="question, comment, email" />
        </label>
        <label>
          Employee ID
          <input v-model="employeeId" placeholder="33742176" />
        </label>
        <label>
          Question ID
          <input v-model="questionId" placeholder="1577046" />
        </label>
        <label>
          Min score
          <input v-model="minScore" placeholder="0" />
        </label>
        <label>
          Max score
          <input v-model="maxScore" placeholder="10" />
        </label>
        <label>
          Answered from
          <input v-model="answeredFrom" type="date" />
        </label>
        <label>
          Answered to
          <input v-model="answeredTo" type="date" />
        </label>
        <label>
          Has comment
          <select v-model="hasComment">
            <option value="">Any</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
        </label>
        <label>
          Department(s)
          <div class="row-inline">
            <input
              v-model="departmentInput"
              list="department-options"
              placeholder="Add department"
              @keydown.enter.prevent="addChip(departmentInput, selectedDepartments)"
            />
            <button type="button" @click="addChip(departmentInput, selectedDepartments)" :disabled="!departmentInput.trim()">Add</button>
          </div>
          <div class="chip-row">
            <button type="button" class="chip" v-for="dep in selectedDepartments" :key="`dep-${dep}`" @click="removeChip(selectedDepartments, dep)">
              {{ dep }} ✕
            </button>
          </div>
        </label>
        <label>
          Sub-department(s)
          <div class="row-inline">
            <input
              v-model="subDepartmentInput"
              list="subdepartment-options"
              placeholder="Add sub-department"
              @keydown.enter.prevent="addChip(subDepartmentInput, selectedSubDepartments)"
            />
            <button type="button" @click="addChip(subDepartmentInput, selectedSubDepartments)" :disabled="!subDepartmentInput.trim()">Add</button>
          </div>
          <div class="chip-row">
            <button type="button" class="chip" v-for="sub in selectedSubDepartments" :key="`sub-${sub}`" @click="removeChip(selectedSubDepartments, sub)">
              {{ sub }} ✕
            </button>
          </div>
        </label>
        <label>
          Manager
          <select v-model="managerId" @change="onAnswersManagerChange">
            <option value="">Any</option>
            <option :value="ORPHANED_MANAGER_ID">Orphaned comments (&lt;5 employees / manager)</option>
            <option v-if="managerLoading" disabled>Loading managers...</option>
            <option v-else-if="visibleManagerOptions.length === 0" disabled>No managers on page</option>
            <option
              v-for="manager in visibleManagerOptions"
              :key="manager.id"
              :value="manager.id"
            >
              {{ manager.label }} ({{ manager.count ?? 0 }})
            </option>
          </select>
        </label>
      </div>

      <div v-else-if="activeView === 'org_map'" class="filters-row">
        <label>
          Search people
          <input v-model="orgMapSearch" placeholder="name, id, email, department" />
        </label>
        <label>
          Department filter(s)
          <input
            v-model="orgMapDepartmentInput"
            list="department-options"
            placeholder="Add department + Enter"
            @keydown.enter.prevent="addChip(orgMapDepartmentInput, selectedOrgDepartments)"
          />
          <div class="chip-row">
            <button type="button" class="chip" v-for="dep in selectedOrgDepartments" :key="`org-dep-${dep}`" @click="removeChip(selectedOrgDepartments, dep)">
              {{ dep }} ✕
            </button>
          </div>
        </label>
        <label>
          Sub-department filter(s)
          <input
            v-model="orgMapSubDepartmentInput"
            list="subdepartment-options"
            placeholder="Add sub-department + Enter"
            @keydown.enter.prevent="addChip(orgMapSubDepartmentInput, selectedOrgSubDepartments)"
          />
          <div class="chip-row">
            <button type="button" class="chip" v-for="sub in selectedOrgSubDepartments" :key="`org-sub-${sub}`" @click="removeChip(selectedOrgSubDepartments, sub)">
              {{ sub }} ✕
            </button>
          </div>
        </label>
        <label>
          People preset
          <button type="button" class="preset-button" @click="loadPeopleOrgPreset">Load People org</button>
        </label>
        <label>
          Manager subtree ID
          <input v-model="orgMapManagerFocus" placeholder="optional manager id" />
        </label>
        <label>
          Layout
          <select v-model="orgLayoutMode">
            <option value="hierarchy_tree">Hierarchy tree</option>
            <option value="hierarchy">Hierarchy radial</option>
            <option value="cluster">Clustered groups</option>
            <option value="knn">KNN similarity</option>
          </select>
        </label>
        <label>
          Group clusters by
          <select v-model="orgClusterBy" :disabled="orgLayoutMode !== 'cluster'">
            <option value="department">Department</option>
            <option value="subDepartment">Sub-department</option>
            <option value="manager">Manager</option>
            <option value="country">Country</option>
            <option value="title">Title</option>
          </select>
        </label>
        <label>
          Node color
          <select v-model="orgColorMode">
            <option value="department">Department / layout</option>
            <option value="engagement">Engagement score ready</option>
          </select>
        </label>
        <label>
          Cluster spread
          <select v-model.number="orgClusterSpread" :disabled="orgLayoutMode !== 'cluster' && orgLayoutMode !== 'knn'">
            <option :value="1.2">Tight</option>
            <option :value="1.8">Balanced</option>
            <option :value="2.5">Wide</option>
            <option :value="3.2">Very wide</option>
          </select>
        </label>
        <label>
          Radial layer gap
          <select v-model.number="orgRadialLayerGap" :disabled="orgLayoutMode !== 'hierarchy' || !orgHierarchyGroupByDepartment">
            <option :value="0.8">Tight</option>
            <option :value="1.2">Balanced</option>
            <option :value="1.8">Wide</option>
            <option :value="2.4">Very wide</option>
          </select>
        </label>
        <label>
          K neighbors
          <select v-model.number="knnK" :disabled="orgLayoutMode !== 'knn'">
            <option :value="3">3</option>
            <option :value="5">5</option>
            <option :value="8">8</option>
            <option :value="12">12</option>
            <option :value="16">16</option>
          </select>
        </label>
        <label>
          KNN feature profile
          <select v-model="knnProfile" :disabled="orgLayoutMode !== 'knn'">
            <option value="all">All (org + title + geo)</option>
            <option value="org">Org structure</option>
            <option value="title">Title-centric</option>
            <option value="geo">Location-centric</option>
          </select>
        </label>
        <label>
          Tree horizontal spread
          <select v-model.number="orgTreeSpreadX" :disabled="orgLayoutMode !== 'hierarchy_tree'">
            <option :value="1.0">Compact</option>
            <option :value="1.6">Balanced</option>
            <option :value="2.4">Wide</option>
            <option :value="3.2">Very wide</option>
          </select>
        </label>
        <label>
          Tree vertical spread
          <select v-model.number="orgTreeSpreadY" :disabled="orgLayoutMode !== 'hierarchy_tree'">
            <option :value="1.2">Compact</option>
            <option :value="2.4">Balanced</option>
            <option :value="3.6">Tall</option>
            <option :value="4.8">Very tall</option>
            <option :value="6.0">Extreme</option>
          </select>
        </label>
        <label>
          Zoom
          <select v-model.number="orgMapZoom">
            <option :value="0.5">50%</option>
            <option :value="0.75">75%</option>
            <option :value="1">100%</option>
            <option :value="1.5">150%</option>
            <option :value="2">200%</option>
          </select>
        </label>
        <label class="toggle-inline">
          <input type="checkbox" v-model="orgHideUnassigned" />
          Hide unassigned dept
        </label>
        <label class="toggle-inline" v-if="orgLayoutMode === 'hierarchy'">
          <input type="checkbox" v-model="orgHierarchyGroupByDepartment" />
          Group radial by dept + colorize
        </label>
        <label class="toggle-inline" v-if="orgLayoutMode === 'hierarchy_tree'">
          <input type="checkbox" v-model="orgTreeSeparateDepartments" />
          Separate dept bands
        </label>
      </div>

      <div v-else-if="activeView === 'org_headcount'" class="filters-row">
        <label>
          Department(s)
          <div class="row-inline">
            <input
              v-model="departmentInput"
              list="department-options"
              placeholder="Add department"
              @keydown.enter.prevent="addChip(departmentInput, selectedDepartments)"
            />
            <button type="button" @click="addChip(departmentInput, selectedDepartments)" :disabled="!departmentInput.trim()">Add</button>
          </div>
          <div class="chip-row">
            <button type="button" class="chip" v-for="dep in selectedDepartments" :key="`hc-dep-${dep}`" @click="removeChip(selectedDepartments, dep)">
              {{ dep }} ✕
            </button>
          </div>
        </label>
        <label>
          Sub-department(s)
          <div class="row-inline">
            <input
              v-model="subDepartmentInput"
              list="subdepartment-options"
              placeholder="Add sub-department"
              @keydown.enter.prevent="addChip(subDepartmentInput, selectedSubDepartments)"
            />
            <button type="button" @click="addChip(subDepartmentInput, selectedSubDepartments)" :disabled="!subDepartmentInput.trim()">Add</button>
          </div>
          <div class="chip-row">
            <button type="button" class="chip" v-for="sub in selectedSubDepartments" :key="`hc-sub-${sub}`" @click="removeChip(selectedSubDepartments, sub)">
              {{ sub }} ✕
            </button>
          </div>
        </label>
        <label>
          Manager (typeahead, optional)
          <div class="row-inline">
            <input
              v-model="orgHeadcountManagerQuery"
              list="org-headcount-manager-options"
              placeholder="Type manager name"
              @change="syncOrgHeadcountManagerSelection"
              @input="syncOrgHeadcountManagerSelection"
            />
            <button type="button" @click="updateOrgHeadcountManagerOptions" :disabled="orgHeadcountManagerLoading">
              {{ orgHeadcountManagerLoading ? 'Loading…' : 'Refresh' }}
            </button>
            <button type="button" @click="orgHeadcountManagerQuery=''; managerId=''" :disabled="!orgHeadcountManagerQuery && !managerId">Clear</button>
          </div>
          <div class="subtle" v-if="managerId">Selected manager ID: {{ managerId }}</div>
        </label>
      </div>

      <div v-else-if="activeView === 'employee_birthdays'" class="filters-row">
        <label>
          Department selector
          <div class="row-inline">
            <select v-model="birthdayDepartmentPick">
              <option value="">Choose department…</option>
              <option v-for="opt in departmentOptions" :key="`bday-pick-${opt}`" :value="opt">{{ opt }}</option>
            </select>
            <button type="button" @click="addSelectedDepartment" :disabled="!birthdayDepartmentPick">Add</button>
          </div>
          <div class="chip-row">
            <button type="button" class="chip" v-for="dep in birthdaySelectedDepartments" :key="`bday-dep-${dep}`" @click="removeChip(birthdaySelectedDepartments, dep)">
              {{ dep }} ✕
            </button>
          </div>
        </label>
        <label>
          Month
          <select v-model="birthdayMonth">
            <option value="">All months</option>
            <option value="01">January</option>
            <option value="02">February</option>
            <option value="03">March</option>
            <option value="04">April</option>
            <option value="05">May</option>
            <option value="06">June</option>
            <option value="07">July</option>
            <option value="08">August</option>
            <option value="09">September</option>
            <option value="10">October</option>
            <option value="11">November</option>
            <option value="12">December</option>
          </select>
        </label>
        <label>
          Name contains
          <input v-model="birthdayNameSearch" placeholder="Type a name" />
        </label>
      </div>

      <div v-else-if="activeView === 'employee_start_dates'" class="filters-row">
        <label>
          Search people
          <input v-model="startDateSearch" placeholder="name, title, department, id" />
        </label>
        <label>
          Department(s)
          <div class="row-inline">
            <input
              v-model="departmentInput"
              list="department-options"
              placeholder="Add department"
              @keydown.enter.prevent="addChip(departmentInput, selectedDepartments)"
            />
            <button type="button" @click="addChip(departmentInput, selectedDepartments)" :disabled="!departmentInput.trim()">Add</button>
          </div>
          <div class="chip-row">
            <button type="button" class="chip" v-for="dep in selectedDepartments" :key="`start-dep-${dep}`" @click="removeChip(selectedDepartments, dep)">
              {{ dep }} ✕
            </button>
          </div>
        </label>
        <label>
          Sub-department(s)
          <div class="row-inline">
            <input
              v-model="subDepartmentInput"
              list="subdepartment-options"
              placeholder="Add sub-department"
              @keydown.enter.prevent="addChip(subDepartmentInput, selectedSubDepartments)"
            />
            <button type="button" @click="addChip(subDepartmentInput, selectedSubDepartments)" :disabled="!subDepartmentInput.trim()">Add</button>
          </div>
          <div class="chip-row">
            <button type="button" class="chip" v-for="sub in selectedSubDepartments" :key="`start-sub-${sub}`" @click="removeChip(selectedSubDepartments, sub)">
              {{ sub }} ✕
            </button>
          </div>
        </label>
      </div>

      <div v-else class="filters-row">
        <label v-if="activeView === 'scores_by_driver'">
          Driver ID
          <input v-model="driverId" placeholder="accomplishment" />
        </label>
        <label>
          Grade
          <input v-model="grade" placeholder="neutral" />
        </label>
        <label v-if="activeView === 'scores_contexts'">
          Impact
          <input v-model="impact" placeholder="low" />
        </label>
        <label>
          Department(s)
          <div class="row-inline">
            <input
              v-model="departmentInput"
              list="department-options"
              placeholder="Add department"
              @keydown.enter.prevent="addChip(departmentInput, selectedDepartments)"
            />
            <button type="button" @click="addChip(departmentInput, selectedDepartments)" :disabled="!departmentInput.trim()">Add</button>
          </div>
          <div class="chip-row">
            <button type="button" class="chip" v-for="dep in selectedDepartments" :key="`scores-dep-${dep}`" @click="removeChip(selectedDepartments, dep)">
              {{ dep }} ✕
            </button>
          </div>
        </label>
        <label>
          Sub-department(s)
          <div class="row-inline">
            <input
              v-model="subDepartmentInput"
              list="subdepartment-options"
              placeholder="Add sub-department"
              @keydown.enter.prevent="addChip(subDepartmentInput, selectedSubDepartments)"
            />
            <button type="button" @click="addChip(subDepartmentInput, selectedSubDepartments)" :disabled="!subDepartmentInput.trim()">Add</button>
          </div>
          <div class="chip-row">
            <button type="button" class="chip" v-for="sub in selectedSubDepartments" :key="`scores-sub-${sub}`" @click="removeChip(selectedSubDepartments, sub)">
              {{ sub }} ✕
            </button>
          </div>
        </label>
        <label>
          Time from
          <input v-model="timeFrom" placeholder="2025-11-01" />
        </label>
        <label>
          Time to
          <input v-model="timeTo" placeholder="2025-12-01" />
        </label>
      </div>

      <datalist id="department-options">
        <option v-for="opt in departmentOptions" :key="`dept-${opt}`" :value="opt" />
      </datalist>
      <datalist id="subdepartment-options">
        <option v-for="opt in subDepartmentOptions" :key="`subdept-${opt}`" :value="opt" />
      </datalist>
      <datalist id="org-headcount-manager-options">
        <option v-for="opt in orgHeadcountManagerOptions" :key="`hc-manager-${opt.id}`" :value="opt.label" />
      </datalist>

      <div class="action-row">
        <button class="primary" @click="resetAndLoad">{{ activeView === 'employee_birthdays' ? 'Refresh data' : 'Apply' }}</button>
        <button v-if="activeView === 'answers_export'" @click="exportFilteredAnswersCsv" :disabled="exportingCsv || loading">
          {{ exportingCsv ? 'Exporting CSV…' : 'Export filtered CSV' }}
        </button>
        <button v-if="activeView === 'answers_export'" @click="exportManagerQuestionCsv" :disabled="exportingCsv || loading">
          Manager question CSV
        </button>
        <button v-if="activeView === 'employee_birthdays'" @click="resetBirthdayFilters">Reset filters</button>
        <button v-if="activeView === 'org_map'" @click="focusOnSelectedManager" :disabled="!selectedOrgNodeId">Focus selected subtree</button>
        <button v-if="activeView === 'org_map'" @click="clearOrgFocus" :disabled="!orgMapManagerFocus">Clear focus</button>
        <button v-if="activeView === 'org_map'" @click="resetOrgPan">Recenter</button>
        <button v-if="activeView === 'org_map'" @click="toggleOrgFullscreen">{{ orgFullscreen ? 'Exit fullscreen' : 'Fullscreen' }}</button>
      </div>
    </section>

    <section v-if="activeView !== 'org_map' && activeView !== 'employee_birthdays' && activeView !== 'org_headcount'" class="pager">
      <button :disabled="!hasPrev || loading" @click="prevPage">Prev</button>
      <span>{{ pageRange }}</span>
      <span v-if="activeView === 'answers_export'">
        {{ uniqueEmployees }} employees and {{ total }} answers
      </span>
      <span v-else-if="activeView === 'employee_start_dates'">
        {{ uniqueEmployees }} employees with hire/start dates
      </span>
      <button :disabled="!hasNext || loading" @click="nextPage">Next</button>
    </section>

    <section v-else-if="activeView === 'org_map'" class="pager">
      <span>{{ nodesToRender.length }} shown / {{ orgMap.stats?.employees || 0 }} total employees</span>
      <span>Depth {{ orgMap.stats?.maxDepth ?? 0 }}</span>
      <span>Orphans {{ orgMap.stats?.orphans ?? 0 }}</span>
      <span v-if="orgColorMode === 'engagement'">Engagement scores {{ orgMap.stats?.nodesWithEngagement ?? 0 }}</span>
    </section>

    <section v-else-if="activeView === 'org_headcount'" class="pager">
      <span>Total headcount: {{ orgHeadcount.totalHeadcount || 0 }}</span>
      <span>Managers in scope: {{ orgHeadcount.managerCount || 0 }}</span>
      <span v-if="managerId">Showing subtree headcount: {{ orgHeadcountRowsVisible.length }}</span>
      <span>Depth {{ orgHeadcount.stats?.maxDepth ?? 0 }}</span>
    </section>

    <section v-else class="pager">
      <span>{{ filteredBirthdaysTotal }} employees with birthdays</span>
      <span>{{ filteredBirthdayGroups.length }} departments</span>
      <span>Scanned {{ birthdaysStats.employeesScanned || 0 }} employees</span>
      <span>Source {{ birthdaysStats.source || 'employees' }}</span>
    </section>

    <section v-if="loading" class="status">Loading…</section>
    <section v-else-if="error" class="status error">{{ error }}</section>

    <section ref="orgMapContainerRef" v-else-if="activeView === 'org_map'" :class="['org-layout', { fullscreen: orgFullscreen }]">
      <div class="org-canvas-wrap card">
        <svg
          ref="orgCanvasRef"
          class="org-canvas"
          :class="{ dragging: orgDragging }"
          viewBox="0 0 1400 1400"
          @wheel="onOrgWheel"
          @pointerdown="onOrgPointerDown"
          @pointermove="onOrgPointerMove"
          @pointerup="onOrgPointerUp"
          @pointerleave="onOrgPointerUp"
        >
          <g v-if="orgLayoutMode === 'cluster' || orgLayoutMode === 'knn'">
            <g v-for="group in clusterGroups" :key="`group-${group.key}`">
              <circle
                :cx="orgNodeX({ x: group.cx, y: 0 })"
                :cy="orgNodeY({ x: 0, y: group.cy })"
                :r="Math.max(22, group.r * orgMapZoom)"
                :fill="group.color"
                fill-opacity="0.08"
                :stroke="group.color"
                stroke-opacity="0.45"
                stroke-width="2"
                stroke-dasharray="6 6"
              />
              <text
                :x="orgNodeX({ x: group.cx, y: 0 })"
                :y="orgNodeY({ x: 0, y: group.cy }) - Math.max(26, group.r * orgMapZoom + 8)"
                class="org-group-label"
              >
                {{ group.key }} ({{ group.count }})
              </text>
            </g>
          </g>

          <g v-if="orgLayoutMode === 'hierarchy_tree'">
            <g v-for="group in treeDepartmentOutlines" :key="`tree-dept-${group.key}`">
              <rect
                :x="orgNodeX({ x: group.x, y: 0 })"
                :y="orgNodeY({ x: 0, y: group.y })"
                :width="Math.max(30, group.w * orgMapZoom)"
                :height="Math.max(30, group.h * orgMapZoom)"
                rx="10"
                ry="10"
                :fill="group.color"
                fill-opacity="0.1"
                :stroke="group.color"
                stroke-opacity="0.75"
                stroke-width="2.5"
                stroke-dasharray=""
              />
              <text
                :x="orgNodeX({ x: group.x + group.w / 2, y: 0 })"
                :y="orgNodeY({ x: 0, y: group.y }) - 8"
                class="org-group-label"
              >
                {{ group.key }} ({{ group.count }})
              </text>
            </g>
          </g>

          <line
            v-for="edge in edgesToRender"
            :key="`${edge.source}-${edge.target}`"
            :x1="orgNodeX(orgNodeById.get(edge.source) || {})"
            :y1="orgNodeY(orgNodeById.get(edge.source) || {})"
            :x2="orgNodeX(orgNodeById.get(edge.target) || {})"
            :y2="orgNodeY(orgNodeById.get(edge.target) || {})"
            :stroke="orgLayoutMode === 'knn'
              ? ((selectedOrgNodeId && (edge.source === selectedOrgNodeId || edge.target === selectedOrgNodeId)) ? '#f59e0b' : '#475569')
              : (orgSelectedChainEdgeKeys.has(`${edge.source}-${edge.target}`) ? '#22c55e' : '#334155')"
            :stroke-width="orgLayoutMode === 'knn'
              ? (0.8 + ((edge.score || 0) * 2.6))
              : (orgSelectedChainEdgeKeys.has(`${edge.source}-${edge.target}`) ? 2.4 : (orgLayoutMode === 'hierarchy_tree' ? 1.4 : 1))"
            :stroke-opacity="orgLayoutMode === 'knn' ? (0.25 + ((edge.score || 0) * 0.7)) : 1"
          />
          <g
            v-for="node in nodesToRender"
            :key="node.id"
            class="org-node"
            @click.stop="onOrgNodeClick(node.id)"
          >
            <circle
              :cx="orgNodeX(node)"
              :cy="orgNodeY(node)"
              :r="orgNodeRadius(node)"
              :fill="orgNodeFill(node)"
            />
            <text
              v-if="showOrgLabels() || selectedOrgNodeId === node.id"
              :x="orgNodeX(node) + 10"
              :y="orgNodeY(node) - 10"
              class="org-label"
            >
              {{ node.label }}
            </text>
          </g>
        </svg>
      </div>

      <aside class="org-panel card" v-if="selectedOrgNode || radialDepartmentLegend.length">
        <template v-if="selectedOrgNode">
          <h3>{{ selectedOrgNode.label }}</h3>
          <p class="subtle">ID: {{ selectedOrgNode.id }}</p>
          <p><strong>Dept:</strong> {{ selectedOrgNode.department || '—' }}</p>
          <p><strong>Sub-dept:</strong> {{ selectedOrgNode.subDepartment || '—' }}</p>
          <p><strong>Title:</strong> {{ selectedOrgNode.title || '—' }}</p>
          <p><strong>Email:</strong> {{ selectedOrgNode.email || '—' }}</p>
          <p><strong>Direct reports:</strong> {{ selectedOrgNode.directReports ?? 0 }}</p>
          <p><strong>Subtree size:</strong> {{ selectedOrgNode.subtreeSize ?? 1 }}</p>
          <p v-if="orgColorMode === 'engagement'"><strong>Engagement:</strong> {{ orgMetricValue(selectedOrgNode, 'engagement') ?? 'No score yet' }}</p>
          <div class="action-row compact">
            <button @click="focusOnSelectedManager">Focus this subtree</button>
          </div>

          <div v-if="orgLayoutMode === 'knn'">
            <strong>Nearest neighbors (k={{ knnK }}):</strong>
            <ul>
              <li v-for="n in (knnMap.get(selectedOrgNode.id) || [])" :key="`knn-${selectedOrgNode.id}-${n.id}`">
                {{ orgNodeById.get(n.id)?.label || n.id }} — {{ (n.score * 100).toFixed(0) }}%
              </li>
            </ul>
          </div>

          <div v-else>
            <strong>Chain to root:</strong>
            <ul>
              <li v-for="node in orgParentChain(selectedOrgNode.id)" :key="`chain-${node.id}`">
                {{ node.label }} ({{ node.id }})
              </li>
            </ul>
          </div>
        </template>

        <div v-if="orgColorMode === 'engagement'" class="org-legend">
          <strong>Engagement color scale</strong>
          <ul>
            <li class="org-legend-row"><span class="org-legend-dot" style="background-color: #ef4444"></span><span>Low (&lt;4)</span></li>
            <li class="org-legend-row"><span class="org-legend-dot" style="background-color: #f59e0b"></span><span>Mixed (4-5.9)</span></li>
            <li class="org-legend-row"><span class="org-legend-dot" style="background-color: #84cc16"></span><span>Good (6-7.9)</span></li>
            <li class="org-legend-row"><span class="org-legend-dot" style="background-color: #22c55e"></span><span>High (8+)</span></li>
            <li class="org-legend-row"><span class="org-legend-dot" style="background-color: #94a3b8"></span><span>No score yet</span></li>
          </ul>
          <p class="subtle">Uses the latest available employee engagement mean from score contexts; gray means no score joined for that employee.</p>
        </div>

        <div v-if="radialDepartmentLegend.length" class="org-legend">
          <strong>Department legend</strong>
          <ul>
            <li v-for="entry in radialDepartmentLegend" :key="`legend-${entry.key}`" class="org-legend-row">
              <span class="org-legend-dot" :style="{ backgroundColor: entry.color }"></span>
              <span>{{ entry.key }}</span>
              <span class="subtle">{{ entry.count }}</span>
            </li>
          </ul>
        </div>
      </aside>
    </section>

    <section v-else-if="activeView === 'org_headcount'" class="list">
      <article class="card">
        <div class="card-header">
          <div>
            <div class="id">Manager rollup</div>
            <div class="meta">Sorted by team size in selected scope</div>
          </div>
        </div>
        <div v-if="orgHeadcountManagersVisible.length" class="table-wrap">
          <table class="mini-table">
            <thead>
              <tr>
                <th>Manager</th>
                <th>Team size</th>
                <th>Direct reports</th>
                <th>Department</th>
                <th>Sub-department</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in orgHeadcountManagersVisible" :key="`mgr-${m.id}`">
                <td>{{ m.name }}</td>
                <td>{{ m.teamSizeInScope }}</td>
                <td>{{ m.directReports }}</td>
                <td>{{ m.department || '—' }}</td>
                <td>{{ m.subDepartment || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="card-row"><span>No managers found for current filter scope.</span></div>
      </article>

      <article class="card">
        <div class="card-header">
          <div>
            <div class="id">Org roster (nested by manager)</div>
            <div class="meta">Indented by reporting depth, with counts</div>
          </div>
        </div>
        <div v-if="orgHeadcountRowsVisible.length" class="table-wrap">
          <table class="mini-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>ID</th>
                <th>Depth</th>
                <th>Team size</th>
                <th>Direct reports</th>
                <th>Department</th>
                <th>Sub-department</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in orgHeadcountRowsVisible" :key="`row-${row.id}`">
                <td>
                  <span :style="{ paddingLeft: `${(row.depth || 0) * 14}px` }">{{ row.name }}</span>
                </td>
                <td>{{ row.id }}</td>
                <td>{{ row.depth }}</td>
                <td>{{ row.subtreeSize }}</td>
                <td>{{ row.directReports }}</td>
                <td>{{ row.department || '—' }}</td>
                <td>{{ row.subDepartment || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="card-row"><span>No employees found for current filter scope.</span></div>
      </article>
    </section>

    <section v-else-if="activeView === 'employee_birthdays'" class="list">
      <article v-for="group in filteredBirthdayGroups" :key="`birthday-group-${group.department}`" class="card">
        <div class="card-header">
          <div>
            <div class="id">{{ group.department }}</div>
            <div class="meta">{{ group.count }} birthdays</div>
          </div>
        </div>
        <div class="card-row" v-for="emp in group.employees" :key="`birthday-emp-${group.department}-${emp.id}`">
          <span class="label">{{ emp.birthday }}</span>
          <span>{{ emp.name }}</span>
        </div>
      </article>
      <article v-if="filteredBirthdayGroups.length === 0" class="card">
        <div class="card-row">
          <span>No birthdays found for current filters.</span>
        </div>
      </article>
    </section>

    <section v-else-if="activeView === 'employee_start_dates'" class="list">
      <article class="card">
        <div class="card-header">
          <div>
            <div class="id">Employee roster by hire date</div>
            <div class="meta">Sorted by hire date first, then start date</div>
          </div>
        </div>
        <div v-if="employeeStartDates.length" class="table-wrap">
          <table class="mini-table">
            <thead>
              <tr>
                <th>Hire date</th>
                <th>Start date</th>
                <th>Name</th>
                <th>ID</th>
                <th>Department</th>
                <th>Sub-department</th>
                <th>Title</th>
                <th>Manager ID</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in employeeStartDates" :key="`start-${row.id}`">
                <td>{{ row.hireDate || '—' }}</td>
                <td>{{ row.startDate || '—' }}</td>
                <td>{{ row.name }}</td>
                <td>{{ row.id }}</td>
                <td>{{ row.department || '—' }}</td>
                <td>{{ row.subDepartment || '—' }}</td>
                <td>{{ row.title || '—' }}</td>
                <td>{{ row.managerId || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="card-row"><span>No employees with hire/start dates found for current filters.</span></div>
      </article>
    </section>

    <section v-else class="list">
      <article
        v-for="item in items"
        :key="item._id"
        :class="['card', answerCardClass(item)]"
      >
        <div v-if="activeView === 'answers_export'" class="card-grid">
          <div class="card-header">
            <div>
              <div class="id">Answer {{ item?.attributes?.answerId || item._id }}</div>
              <div class="meta">
                <span class="email" @mouseenter="onEmailHover(item?.attributes?.employeeId)">
                  {{ displayEmail() }}
                </span>
                <div class="popover">
                  <div
                    v-if="hoverLoading && hoverEmployeeId === String(item?.attributes?.employeeId || '')"
                    class="popover-row"
                  >
                    Loading…
                  </div>
                  <div
                    v-else-if="employeeCache.get(item?.attributes?.employeeId)"
                    class="popover-grid"
                  >
                    <div class="popover-row">
                      <span class="label">Department</span>
                      <span>{{
                        employeeAttr(item?.attributes?.employeeId, ["Department", "department"])
                      }}</span>
                    </div>
                    <div class="popover-row">
                      <span class="label">Sub-department</span>
                      <span>{{
                        employeeAttr(item?.attributes?.employeeId, ["Sub-Department", "sub_department", "sub-department"])
                      }}</span>
                    </div>
                    <div class="popover-row">
                      <span class="label">Country</span>
                      <span>{{
                        employeeAttr(item?.attributes?.employeeId, ["Country", "country"])
                      }}</span>
                    </div>
                    <div class="popover-row">
                      <span class="label">Comp grade</span>
                      <span>{{
                        employeeAttr(item?.attributes?.employeeId, ["Compensation Grade", "compensation_grade"])
                      }}</span>
                    </div>
                    <div class="popover-row">
                      <span class="label">Manager ID</span>
                      <span>{{ employeeManagerId(item?.attributes?.employeeId) }}</span>
                    </div>
                  </div>
                  <div
                    v-else-if="employeeErrors.get(item?.attributes?.employeeId)"
                    class="popover-row error"
                  >
                    {{ employeeErrors.get(item?.attributes?.employeeId) }}
                  </div>
                  <div v-else class="popover-row">No employee data</div>
                </div>
              </div>
            </div>
            <span :class="['badge', 'score', answerScoreClass(item)]">{{ item?.attributes?.answerScore ?? "n/a" }}</span>
          </div>
          <div class="card-row">
            <span class="label">Question</span>
            <span>{{ item?.attributes?.questionText || "—" }}</span>
          </div>
          <div class="card-row">
            <span class="label">Answered</span>
            <span>{{ item?.attributes?.responseAnsweredAt || "—" }}</span>
          </div>
          <div v-if="item?.attributes?.answerComment" class="card-row">
            <span class="label">Comment</span>
            <span>{{ item.attributes.answerComment }}</span>
          </div>
        </div>

        <div v-else-if="activeView === 'scores_contexts'" class="card-grid">
          <div class="card-header">
            <div>
              <div class="id">Context {{ item._id }}</div>
              <div class="meta">{{ item?.attributes?.scores?.time || "—" }}</div>
            </div>
            <span class="badge">{{ item?.attributes?.grade || "—" }}</span>
          </div>
          <div class="card-row">
            <span class="label">Impact</span>
            <span>{{ item?.attributes?.impact || "—" }}</span>
          </div>
          <div class="card-row">
            <span class="label">Mean</span>
            <span>{{ item?.attributes?.scores?.mean ?? "—" }}</span>
          </div>
          <div class="card-row">
            <span class="label">Favorable</span>
            <span>{{ item?.attributes?.scores?.favorable?.score ?? "—" }}</span>
          </div>
          <div class="card-row">
            <span class="label">NPS</span>
            <span>{{ item?.attributes?.scores?.nps?.score ?? "—" }}</span>
          </div>
        </div>

        <div v-else class="card-grid">
          <div class="card-header">
            <div>
              <div class="id">{{ item?.driver_id || "Driver" }}</div>
              <div class="meta">{{ item?.attributes?.scores?.time || "—" }}</div>
            </div>
            <span class="badge">{{ item?.attributes?.grade || "—" }}</span>
          </div>
          <div class="card-row">
            <span class="label">Score ID</span>
            <span>{{ item?._id }}</span>
          </div>
          <div class="card-row">
            <span class="label">Mean</span>
            <span>{{ item?.attributes?.scores?.mean ?? "—" }}</span>
          </div>
          <div class="card-row">
            <span class="label">Impact</span>
            <span>{{ item?.attributes?.impact || "—" }}</span>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>
