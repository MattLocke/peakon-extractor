<script setup>
import { computed, onMounted, ref, watch } from "vue";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const views = [
  { id: "answers_export", label: "Answers Export" },
  { id: "scores_contexts", label: "Scores Contexts" },
  { id: "scores_by_driver", label: "Scores By Driver" },
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

const hasPrev = computed(() => skip.value > 0);
const hasNext = computed(() => skip.value + limit.value < total.value);
const pageRange = computed(() => {
  const start = total.value === 0 ? 0 : skip.value + 1;
  const end = Math.min(skip.value + limit.value, total.value);
  return `${start}-${end} of ${total.value}`;
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({
      limit: String(limit.value),
      skip: String(skip.value),
    });
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
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
    items.value = [];
    total.value = 0;
    uniqueEmployees.value = 0;
  } finally {
    loading.value = false;
  }
}

async function fetchEmployee(employeeIdValue) {
  if (!employeeIdValue) return null;
  if (employeeCache.value.has(employeeIdValue)) {
    return employeeCache.value.get(employeeIdValue);
  }
  hoverLoading.value = true;
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
    hoverLoading.value = false;
  }
}

async function onEmailHover(employeeIdValue) {
  if (!employeeIdValue) return;
  hoverEmployeeId.value = String(employeeIdValue);
  await fetchEmployee(employeeIdValue);
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

function resetAndLoad() {
  skip.value = 0;
  load();
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
          Manager ID
          <input v-model="managerId" placeholder="29375652" />
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

      <button class="primary" @click="resetAndLoad">Apply</button>
    </section>

    <section class="pager">
      <button :disabled="!hasPrev || loading" @click="prevPage">Prev</button>
      <span>{{ pageRange }}</span>
      <span v-if="activeView === 'answers_export'">
        {{ uniqueEmployees }} employees and {{ total }} answers
      </span>
      <button :disabled="!hasNext || loading" @click="nextPage">Next</button>
    </section>

    <section v-if="loading" class="status">Loading…</section>
    <section v-else-if="error" class="status error">{{ error }}</section>
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
                  {{ item?.attributes?.accountEmail || "Unknown email" }}
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
