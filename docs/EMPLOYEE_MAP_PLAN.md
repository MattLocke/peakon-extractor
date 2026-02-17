# Employee Org Map Plan (Peakon Extractor)

## Goal
Add a CEO-centered, explorable org map to **peakon-extractor** using employee manager relationships already ingested into MongoDB.

## Current state (good news)
- Ingest pipeline already stores employees in Mongo (`employees` collection).
- API already has employee helpers and manager relationship parsing logic.
- Web app already exists (Vue + Vite), so we can add a new view instead of creating a separate app.

## Proposed architecture

### 1) Backend: add org-map dataset endpoint
Add endpoint:
- `GET /org_map`

Behavior:
- Read all employees from Mongo (`employees`)
- Build graph from manager relationships:
  - node = employee
  - edge = `manager -> employee`
- Compute:
  - `rootId` (CEO/top-most manager)
  - `depth`
  - `directReports`
  - `subtreeSize`
- Handle anomalies:
  - missing manager (orphans)
  - cycles (detect + break/report)
  - duplicate IDs
- Return render-ready payload:
  - nodes with coordinates (`x`,`y`) from radial layout
  - edges
  - stats/anomalies summary

Optional params:
- `?department=...`
- `?max_depth=...`
- `?manager_id=...` (subtree focus)

### 2) Frontend: new Org Map tab in `web/src/App.vue`
Add new tab/view:
- **Org Map Explorer**

MVP UI features:
- pan/zoom canvas
- search by name/email/id
- click node opens side panel:
  - employee details
  - direct reports
  - path to CEO
- fit-to-screen + zoom controls

### 3) Rendering approach
Start simple and reliable:
- Canvas 2D custom renderer (fast enough for ~2k nodes with precomputed coordinates)

Future upgrade path:
- Sigma.js + Graphology for larger graphs and richer interactions.

## Implementation phases

### Phase 1 (MVP)
- [ ] Add `org_map` builder utilities in API layer
- [ ] Add `GET /org_map` endpoint
- [ ] Add Org Map tab in Vue app
- [ ] Add basic pan/zoom/search/side panel
- [ ] Add tests for graph build + anomaly handling

### Phase 2 (polish)
- [ ] Progressive labels by zoom level
- [ ] Cluster/collapse manager groups
- [ ] Department filters and highlighting
- [ ] path-to-CEO highlight

### Phase 3 (scale)
- [ ] Optional precompute cache collection (`org_map_cache`)
- [ ] Incremental refresh after ingestion run
- [ ] Performance telemetry for load/render times

## Data contract for `/org_map`

```json
{
  "generatedAt": "2026-02-17T00:00:00Z",
  "rootId": "12345",
  "stats": {
    "employees": 2000,
    "renderedNodes": 2000,
    "renderedEdges": 1999,
    "maxDepth": 9,
    "orphans": 12,
    "cycleBreaks": 1,
    "duplicates": 0
  },
  "anomalies": {
    "orphans": [{ "id": "...", "managerId": "..." }],
    "cycleBreaks": [{ "managerId": "...", "employeeId": "..." }],
    "duplicates": []
  },
  "nodes": [
    {
      "id": "12345",
      "label": "Jane Doe",
      "email": "...",
      "managerId": null,
      "depth": 0,
      "directReports": 7,
      "subtreeSize": 2000,
      "x": 0,
      "y": 0
    }
  ],
  "edges": [{ "source": "12345", "target": "67890" }]
}
```

## Quick audit notes to address while building
- Tests currently fail for async pagination because `pytest-asyncio` is not installed/configured in this repo environment.
- CORS is currently wide open (`allow_origins=['*']`), acceptable for local internal use but should be restricted for production exposure.
- Org-map endpoint should avoid returning sensitive fields unless needed (principle of least data).

## Suggested first PR scope
1. Add `/org_map` endpoint + graph builder module + tests.
2. Add Org Map tab with canvas explorer in existing Vue app.
3. Keep all changes behind current local/internal usage model (no auth model changes yet).
