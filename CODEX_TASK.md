# CODING TASK: Peakon → MongoDB weekly ingestor (Docker + Python)

Use this document as the authoritative implementation brief.

## Goal

Build a Python service (Dockerized) that downloads Peakon data weekly and stores it in MongoDB. It must:
- Authenticate via `/auth/application` using a user-provided `token` (application token) and store the resulting bearer token.
- Fetch multiple API endpoints (some paginated) and persist results to Mongo with idempotent upserts.
- Run in a Docker container and support a weekly cadence (cron-like schedule inside the container).
- Be resilient: retries, logging, reasonable error handling.

Source requirements + endpoint examples are in `local python version.md`.

## Inputs (configuration)

All configuration is via environment variables:

### Peakon
- `PEAKON_BASE_URL` (default: `https://pax8inc.peakon.com/api/v1`)
- `PEAKON_APP_TOKEN` (required): provided by the user; exchanged for bearer token.
- `PEAKON_COMPANY_ID` (default: `22182`)
- `PEAKON_ENGAGEMENT_GROUP` (default: `engagement`)
- `PEAKON_PER_PAGE` (default: `10000`)
- `HTTP_TIMEOUT_SECONDS` (default: `60`)

### Mongo
- `MONGO_URI` (default: `mongodb://mongo:27017`)
- `MONGO_DB` (default: `peakon`)

### Scheduling
- `SCHEDULE_CRON` (default: `0 3 * * 1` i.e., Mondays 03:00)
- `RUN_ON_START` (default: `true`)
- `FULL_SYNC` (default: `false`)

### Logging
- `LOG_LEVEL` (default: `INFO`)

## Authentication

Endpoint:
- `POST {PEAKON_BASE_URL}/auth/application` with parameter `token=<PEAKON_APP_TOKEN>`

Implementation requirements:
- Try JSON body first: `{ "token": "<...>" }`
- If Peakon rejects it, fallback to `application/x-www-form-urlencoded`.
- Parse bearer token from the response with tolerant parsing (token location not specified in the source doc):
  - Accept `{"token": "..."}` OR `{"access_token": "..."}` OR `{"data": {"attributes": {"token": "..."}}}` etc.
- Store token in Mongo collection `auth_tokens`:
  - `_id`: f"{base_url}::application"
  - `bearer_token`, `obtained_at`
- Requests must send `Authorization: Bearer <token>`.

Refresh behavior:
- If request returns 401 once, re-auth and retry that request once.

## Endpoints to ingest

1) Answers export (pagination)
- `GET {base}/answers/export?per_page=10000`
- Follow `links.next` until missing.

Store each `data[]` item to `answers_export` with idempotent upsert keyed by:
- `_id = int(attributes.answerId)` if present, else fallback to `id`.

Track cursor for best-effort incremental runs:
- Maintain `sync_state` doc with `_id="answers_export"` containing `last_answer_id` (max seen) and `updated_at`.
- If `FULL_SYNC=false` and `last_answer_id` exists, start the first request with `continuation=<last_answer_id>` (best effort).

2) Employees (pagination)
- `GET {base}/employees`
- Follow `links.next` until missing (or support `page` pagination if `links.next` is absent but a `meta` pagination exists).

Store each `data[]` item to `employees` keyed by:
- `_id = int(id)` (string in payload, but store as int if parseable)

Cursor:
- `sync_state` `_id="employees"` with `last_employee_id` (max seen). Best-effort use `continuation` if supported.

3) Drivers
- `GET {base}/engagement/drivers`
- Store each driver item to `drivers` keyed by `_id = id` (string driver id like `accomplishment`).

Also seed the static driver catalog from the CSV list in the source doc into `drivers_catalog` keyed by `_id = numeric Id`.

4) Contexts (engagement context)
- `GET {base}/scores/contexts/company_{company_id}/group/{engagement_group}`
- Store each `data[]` item to `scores_contexts`.
- Key: `_id = f"{engagement_group}::{item['id']}::{item['attributes']['scores']['time']}"` when possible; otherwise store raw with a generated stable hash.

5) Scores by driver id
For each driver id from (3), call:
- `GET {base}/scores/contexts/company_{company_id}/group/{driver_id}`

Store items to `scores_by_driver`:
- Key: `_id = f"{driver_id}::{item['id']}::{item['attributes']['scores']['time']}"` when possible.

## Data model philosophy

- Prefer storing the raw API objects (the `data[]` items) largely unchanged.
- Add metadata fields:
  - `fetched_at` (UTC ISO string)
  - `run_id` (UUID)
  - `endpoint` (string)
  - `source_url` (string)
- Use Mongo upserts and unique indexes to ensure idempotency.

## Execution modes (CLI)

Provide a `typer` CLI with:

- `ingest` : run one ingestion cycle now
- `daemon` : run scheduler; if `RUN_ON_START=true`, run once immediately then schedule weekly

Both should exit non-zero on fatal configuration errors (missing app token, Mongo unreachable, etc.)

## Error handling

- Use retries with exponential backoff for transient HTTP failures (>=500, network).
- Respect `Retry-After` for 429 if present.
- Log progress: pages fetched, docs upserted per endpoint.
- Persist run stats to `ingestion_runs`:
  - `_id` run_id
  - `started_at`, `finished_at`, `status` (success/failure)
  - counts per collection
  - last error message (if any)

## Docker requirements

- Provide `Dockerfile` and `docker-compose.yml` (Mongo + ingestor).
- Ingestor container should default to running `daemon`.
- All runtime config is via `.env`.

## Acceptance criteria

A) `docker compose up --build` starts Mongo and the ingestor.
B) With valid `PEAKON_APP_TOKEN`, running `python -m peakon_ingest.cli ingest` results in documents inserted into:
   - `answers_export`, `employees`, `drivers`, `scores_contexts`, `scores_by_driver`
C) Re-running `ingest` does not create duplicates (upsert behavior).
D) Pagination is followed until no `links.next`.
E) Weekly scheduling works (cron expression configurable via env).

## Nice-to-haves (do if easy)

- Add a `--full-sync/--incremental` flag to `ingest` that overrides env.
- Add `--dry-run` that fetches but does not write, printing counts.
- Add `pytest` tests for:
  - pagination link chasing
  - token parsing fallback
  - Mongo upsert keying logic
