# Peakon → MongoDB Ingestor (Docker + Python)

This project ingests Peakon API data into MongoDB on a weekly cadence.

It pulls and stores:
- Answers export (paginated)
- Employees (paginated)
- Engagement drivers
- Context scores (engagement)
- Driver score contexts for each driver id returned by the drivers endpoint

> **Security note:** Answers and employees can contain PII (emails, comments, demographics). Make sure your storage and access comply with your internal policies.

## Quick start (Docker)

1) Copy env file:
```bash
cp .env.example .env
```

2) Set your Peakon application token in `.env`:
- `PEAKON_APP_TOKEN=...`

3) Start services:
```bash
docker compose up --build
```

By default, the container runs once at startup **and** then schedules weekly runs (configurable).

## Browse UI (Vue + Vite)

This repo includes a lightweight browser UI and API.

1) Start services (same as above):
```bash
docker compose up --build
```

2) Open the UI:
- `http://localhost:5173`

The UI talks to a small API layer at `http://localhost:8000` (configurable via `VITE_API_BASE`).

Filters are available in the UI for:
- Answers export: search text, employee ID, question ID, score range, answered date range, department/sub-department/manager
- Scores contexts: grade, impact, time range, department/sub-department (employee-scoped)
- Scores by driver: driver ID, grade, time range, department/sub-department (employee-scoped)
- Org Map Explorer: employee graph from manager relationships with search + zoom + detail panel

## Configuration

Key environment variables (see `.env.example`):
- `PEAKON_BASE_URL` (default: `https://pax8inc.peakon.com/api/v1`)
- `PEAKON_APP_TOKEN` (required) - exchanged for a bearer token via `/auth/application`
- `PEAKON_COMPANY_ID` (default: `22182`)
- `PEAKON_ENGAGEMENT_GROUP` (default: `engagement`)
- `MONGO_URI` (default: `mongodb://mongo:27017`)
- `MONGO_DB` (default: `peakon`)
- `SCHEDULE_CRON` (default: `0 3 * * 1` = Mondays at 03:00)
- `RUN_ON_START` (default: `true`)
- `FULL_SYNC` (default: `false`) - if false, uses stored cursors when available

## Running locally (no Docker)

Requires Python 3.11+ and MongoDB.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export PYTHONPATH=src
export $(cat .env | xargs)  # or use a dotenv loader
python -m peakon_ingest.cli ingest
```

## Collections created

- `auth_tokens` – bearer token cache
- `sync_state` – cursors for incremental paging (best-effort)
- `drivers_catalog` – static driver mapping list (seeded)
- `drivers` – drivers endpoint items
- `employees` – employees endpoint items
- `answers_export` – answers export items
- `scores_contexts` – context score items
- `scores_by_driver` – score items by driver
- `ingestion_runs` – run metadata and stats

## Notes on pagination

Endpoints that paginate are followed by chasing `links.next` until absent.
If `FULL_SYNC=false`, the ingestor will store a best-effort cursor per endpoint and try to resume from there on the next run.

## Development

```bash
pytest -q
```
