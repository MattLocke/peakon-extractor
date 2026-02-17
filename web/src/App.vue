<script setup>
import { computed, onMounted, ref, watch } from "vue";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const views = [
  { id: "answers_export", label: "Answers Export" },
  { id: "scores_contexts", label: "Scores Contexts" },
  { id: "scores_by_driver", label: "Scores By Driver" },
  { id: "org_map", label: "Org Map Explorer" },
];

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
const managerId = ref("");
const grade = ref("");
const impact = ref("");
const timeFrom = ref("");
const timeTo = ref("");
const ANON_EMAIL = "user@pax8.com";
const managerOptions = ref([]);
const managerLoading = ref(false);
const managerCache = ref(new Map());
const orgMap = ref({ nodes: [], edges: [], stats: {}, rootId: null });
const orgMapSearch = ref("");
const orgMapDepartment = ref("");
const orgMapManagerFocus = ref("");
const orgMapZoom = ref(1);
const orgPanX = ref(0);
const orgPanY = ref(0);
const orgDragging = ref(false);
const orgDidDrag = ref(false);
const selectedOrgNodeId = ref("");
let managerRequestId = 0;
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

const selectedOrgNode = computed(() => {
  if (!selectedOrgNodeId.value) return null;
  return orgMap.value.nodes.find((node) => node.id === selectedOrgNodeId.value) || null;
});

const filteredOrgNodes = computed(() => {
  const q = orgMapSearch.value.trim().toLowerCase();
  if (!q) return orgMap.value.nodes;
  return orgMap.value.nodes.filter((node) => {
    return [node.label, node.id, node.email, node.department, node.title]
      .filter(Boolean)
      .some((v) => String(v).toLowerCase().includes(q));
  });
});

const orgNodeById = computed(() => new Map(orgMap.value.nodes.map((n) => [n.id, n])));
const filteredOrgNodeIds = computed(() => new Set(filteredOrgNodes.value.map((n) => n.id)));
const filteredOrgEdges = computed(() =>
  orgMap.value.edges.filter(
    (edge) => filteredOrgNodeIds.value.has(edge.source) && filteredOrgNodeIds.value.has(edge.target)
  )
);
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

function orgNodeX(node) {
  return 700 + orgPanX.value + (node.x || 0) * orgMapZoom.value;
}

function orgNodeY(node) {
  return 700 + orgPanY.value + (node.y || 0) * orgMapZoom.value;
}

function orgNodeRadius(node) {
  const base = selectedOrgNodeId.value === node.id ? 10 : 7;
  return Math.max(4, base + Math.min(4, (node.directReports || 0) / 5));
}

function showOrgLabels() {
  return orgMapZoom.value >= 1.5;
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
      items.value = [];
      total.value = orgMap.value.nodes.length;
      uniqueEmployees.value = orgMap.value.nodes.length;
      if (!selectedOrgNodeId.value && orgMap.value.rootId) {
        selectedOrgNodeId.value = orgMap.value.rootId;
      }
      return;
    }
    if (activeView.value === "answers_export") {
      if (search.value.trim()) params.set("search", search.value.trim());
      if (employeeId.value.trim()) params.set("employee_id", employeeId.value.trim());
      if (questionId.value.trim()) params.set("question_id", questionId.value.trim());
      if (minScore.value.trim()) params.set("min_score", minScore.value.trim());
      if (maxScore.value.trim()) params.set("max_score", maxScore.value.trim());
      if (answeredFrom.value.trim()) params.set("answered_from", answeredFrom.value.trim());
      if (answeredTo.value.trim()) params.set("answered_to", answeredTo.value.trim());
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
    }
    if (activeView.value === "scores_by_driver") {
      if (driverId.value.trim()) params.set("driver_id", driverId.value.trim());
      if (grade.value.trim()) params.set("grade", grade.value.trim());
      if (timeFrom.value.trim()) params.set("time_from", timeFrom.value.trim());
      if (timeTo.value.trim()) params.set("time_to", timeTo.value.trim());
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
    if (answeredFrom.value.trim()) params.set("answered_from", answeredFrom.value.trim());
    if (answeredTo.value.trim()) params.set("answered_to", answeredTo.value.trim());
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


function resetAndLoad() {
  skip.value = 0;
  load();
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

function onOrgNodeClick(nodeId) {
  if (orgDidDrag.value) return;
  selectedOrgNodeId.value = nodeId;
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

watch([activeView, limit], () => resetAndLoad());

onMounted(() => load());
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
          <input v-model="answeredFrom" placeholder="2025-11-01T00:00:00Z" />
        </label>
        <label>
          Answered to
          <input v-model="answeredTo" placeholder="2025-12-01T00:00:00Z" />
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
          Department
          <input v-model="department" placeholder="Partner Support" />
        </label>
        <label>
          Sub-department
          <input v-model="subDepartment" placeholder="Service Delivery" />
        </label>
        <label>
          Manager
          <select v-model="managerId">
            <option value="">Any</option>
            <option v-if="managerLoading" disabled>Loading managers...</option>
            <option v-else-if="managerOptions.length === 0" disabled>No managers on page</option>
            <option
              v-for="manager in managerOptions"
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
          Department filter
          <input v-model="orgMapDepartment" placeholder="Partner Support" />
        </label>
        <label>
          Manager subtree ID
          <input v-model="orgMapManagerFocus" placeholder="optional manager id" />
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
          Time from
          <input v-model="timeFrom" placeholder="2025-11-01" />
        </label>
        <label>
          Time to
          <input v-model="timeTo" placeholder="2025-12-01" />
        </label>
      </div>

      <div class="action-row">
        <button class="primary" @click="resetAndLoad">Apply</button>
        <button v-if="activeView === 'org_map'" @click="focusOnSelectedManager" :disabled="!selectedOrgNodeId">Focus selected subtree</button>
        <button v-if="activeView === 'org_map'" @click="clearOrgFocus" :disabled="!orgMapManagerFocus">Clear focus</button>
        <button v-if="activeView === 'org_map'" @click="resetOrgPan">Recenter</button>
      </div>
    </section>

    <section v-if="activeView !== 'org_map'" class="pager">
      <button :disabled="!hasPrev || loading" @click="prevPage">Prev</button>
      <span>{{ pageRange }}</span>
      <span v-if="activeView === 'answers_export'">
        {{ uniqueEmployees }} employees and {{ total }} answers
      </span>
      <button :disabled="!hasNext || loading" @click="nextPage">Next</button>
    </section>

    <section v-else class="pager">
      <span>{{ filteredOrgNodes.length }} shown / {{ orgMap.stats?.employees || 0 }} total employees</span>
      <span>Depth {{ orgMap.stats?.maxDepth ?? 0 }}</span>
      <span>Orphans {{ orgMap.stats?.orphans ?? 0 }}</span>
    </section>

    <section v-if="loading" class="status">Loading…</section>
    <section v-else-if="error" class="status error">{{ error }}</section>

    <section v-else-if="activeView === 'org_map'" class="org-layout">
      <div class="org-canvas-wrap card">
        <svg
          class="org-canvas"
          :class="{ dragging: orgDragging }"
          viewBox="0 0 1400 1400"
          @pointerdown="onOrgPointerDown"
          @pointermove="onOrgPointerMove"
          @pointerup="onOrgPointerUp"
          @pointerleave="onOrgPointerUp"
        >
          <line
            v-for="edge in filteredOrgEdges"
            :key="`${edge.source}-${edge.target}`"
            :x1="orgNodeX(orgNodeById.get(edge.source) || {})"
            :y1="orgNodeY(orgNodeById.get(edge.source) || {})"
            :x2="orgNodeX(orgNodeById.get(edge.target) || {})"
            :y2="orgNodeY(orgNodeById.get(edge.target) || {})"
            :stroke="orgSelectedChainEdgeKeys.has(`${edge.source}-${edge.target}`) ? '#22c55e' : '#334155'"
            :stroke-width="orgSelectedChainEdgeKeys.has(`${edge.source}-${edge.target}`) ? 2.4 : 1"
          />
          <g
            v-for="node in filteredOrgNodes"
            :key="node.id"
            class="org-node"
            @click.stop="onOrgNodeClick(node.id)"
          >
            <circle
              :cx="orgNodeX(node)"
              :cy="orgNodeY(node)"
              :r="orgNodeRadius(node)"
              :fill="selectedOrgNodeId === node.id ? '#22c55e' : (orgSelectedChainIds.has(node.id) ? '#38bdf8' : '#60a5fa')"
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

      <aside class="org-panel card" v-if="selectedOrgNode">
        <h3>{{ selectedOrgNode.label }}</h3>
        <p class="subtle">ID: {{ selectedOrgNode.id }}</p>
        <p><strong>Dept:</strong> {{ selectedOrgNode.department || '—' }}</p>
        <p><strong>Title:</strong> {{ selectedOrgNode.title || '—' }}</p>
        <p><strong>Email:</strong> {{ selectedOrgNode.email || '—' }}</p>
        <p><strong>Direct reports:</strong> {{ selectedOrgNode.directReports ?? 0 }}</p>
        <p><strong>Subtree size:</strong> {{ selectedOrgNode.subtreeSize ?? 1 }}</p>
        <div class="action-row compact">
          <button @click="focusOnSelectedManager">Focus this subtree</button>
        </div>

        <div>
          <strong>Chain to root:</strong>
          <ul>
            <li v-for="node in orgParentChain(selectedOrgNode.id)" :key="`chain-${node.id}`">
              {{ node.label }} ({{ node.id }})
            </li>
          </ul>
        </div>
      </aside>
    </section>

    <section v-else class="list">
      <article
        v-for="item in items"
        :key="item._id"
        class="card"
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
            <span class="badge score">{{ item?.attributes?.answerScore ?? "n/a" }}</span>
          </div>
          <div class="card-row">
            <span class="label">Employee</span>
            <span>{{ item?.attributes?.employeeId || "—" }}</span>
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
