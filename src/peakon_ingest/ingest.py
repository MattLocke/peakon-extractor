from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any, Dict, List, Tuple

import httpx

from .http import PeakonClient
from .pagination import paginate_json
from .storage import MongoStorage
from .drivers_catalog import DRIVERS_CATALOG

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def _safe_int(value: Any) -> Any:
    try:
        return int(value)
    except Exception:
        return value


def _make_meta(endpoint: str, run_id: str, source_url: str) -> Dict[str, Any]:
    return {
        "endpoint": endpoint,
        "run_id": run_id,
        "fetched_at": _utc_iso(),
        "source_url": source_url,
    }


async def seed_drivers_catalog(storage: MongoStorage) -> int:
    count = 0
    for numeric_id, driver, subdriver in DRIVERS_CATALOG:
        doc = {"_id": numeric_id, "driver": driver, "subdriver": subdriver}
        storage.upsert_doc("drivers_catalog", numeric_id, doc)
        count += 1
    return count


async def ingest_answers_export(
    client: PeakonClient,
    storage: MongoStorage,
    *,
    per_page: int,
    full_sync: bool,
    run_id: str,
) -> Tuple[int, int]:
    endpoint = "answers_export"
    base_path = "/answers/export"
    params: Dict[str, Any] = {"per_page": per_page}

    state = storage.get_state(endpoint)
    if not full_sync and state.get("last_answer_id"):
        # Best-effort incremental using continuation
        params["continuation"] = state["last_answer_id"]

    upserted = 0
    max_answer_id: int | None = None

    async for page in paginate_json(client, base_path, first_params=params):
        data = page.get("data") or []
        for item in data:
            attrs = item.get("attributes") or {}
            answer_id = _safe_int(attrs.get("answerId") or item.get("id"))
            if isinstance(answer_id, int):
                max_answer_id = max(max_answer_id or answer_id, answer_id)

            doc = {
                "_id": answer_id,
                **item,
                **_make_meta(endpoint, run_id, base_path),
            }
            storage.upsert_doc(endpoint, answer_id, doc)
            upserted += 1

    if max_answer_id is not None:
        storage.set_state(endpoint, {"last_answer_id": max_answer_id})

    return upserted, (max_answer_id or -1)


async def ingest_employees(
    client: PeakonClient,
    storage: MongoStorage,
    *,
    per_page: int,
    full_sync: bool,
    run_id: str,
) -> Tuple[int, int]:
    endpoint = "employees"
    base_path = "/employees"
    params: Dict[str, Any] = {"per_page": per_page}

    state = storage.get_state(endpoint)
    if not full_sync and state.get("last_employee_id"):
        # Best-effort incremental (may not be supported; harmless if ignored)
        params["continuation"] = state["last_employee_id"]

    upserted = 0
    max_emp_id: int | None = None

    async for page in paginate_json(client, base_path, first_params=params):
        data = page.get("data") or []
        for item in data:
            emp_id = _safe_int(item.get("id"))
            if isinstance(emp_id, int):
                max_emp_id = max(max_emp_id or emp_id, emp_id)

            doc = {
                "_id": emp_id,
                **item,
                **_make_meta(endpoint, run_id, base_path),
            }
            storage.upsert_doc(endpoint, emp_id, doc)
            upserted += 1

    if max_emp_id is not None:
        storage.set_state(endpoint, {"last_employee_id": max_emp_id})

    return upserted, (max_emp_id or -1)


async def ingest_drivers(
    client: PeakonClient,
    storage: MongoStorage,
    *,
    run_id: str,
) -> List[str]:
    endpoint = "drivers"
    path = "/engagement/drivers"
    payload = await client.get_json_with_reauth_on_401(path)

    driver_ids: List[str] = []
    for item in payload.get("data") or []:
        driver_id = item.get("id")
        if isinstance(driver_id, str):
            driver_ids.append(driver_id)

        doc = {
            "_id": driver_id,
            **item,
            **_make_meta(endpoint, run_id, path),
        }
        storage.upsert_doc(endpoint, driver_id, doc)

    return driver_ids


def _score_doc_id(prefix: str, item: Dict[str, Any], time_key: str | None) -> str:
    item_id = item.get("id")
    if time_key:
        return f"{prefix}::{item_id}::{time_key}"
    return f"{prefix}::{item_id}"


async def ingest_contexts(
    client: PeakonClient,
    storage: MongoStorage,
    *,
    company_id: int,
    engagement_group: str,
    run_id: str,
) -> int:
    endpoint = "scores_contexts"
    path = f"/scores/contexts/company_{company_id}/group/{engagement_group}"
    payload = await client.get_json_with_reauth_on_401(path)

    upserted = 0
    for item in payload.get("data") or []:
        attrs = item.get("attributes") or {}
        scores = attrs.get("scores") or {}
        time_key = scores.get("time")
        _id = _score_doc_id(engagement_group, item, time_key)
        doc = {
            "_id": _id,
            **item,
            **_make_meta(endpoint, run_id, path),
        }
        storage.upsert_doc(endpoint, _id, doc)
        upserted += 1

    return upserted


async def ingest_scores_by_driver(
    client: PeakonClient,
    storage: MongoStorage,
    *,
    company_id: int,
    driver_ids: List[str],
    run_id: str,
) -> int:
    endpoint = "scores_by_driver"
    upserted = 0

    for driver_id in driver_ids:
        path = f"/scores/contexts/company_{company_id}/group/{driver_id}"
        try:
            payload = await client.get_json_with_reauth_on_401(path)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 422:
                logger.warning(
                    "Skipping scores_by_driver for driver_id=%s due to 422 response: %s",
                    driver_id,
                    e.response.text[:500],
                )
                continue
            raise

        for item in payload.get("data") or []:
            attrs = item.get("attributes") or {}
            scores = attrs.get("scores") or {}
            time_key = scores.get("time")
            _id = _score_doc_id(driver_id, item, time_key)
            doc = {
                "_id": _id,
                "driver_id": driver_id,
                **item,
                **_make_meta(endpoint, run_id, path),
            }
            storage.upsert_doc(endpoint, _id, doc)
            upserted += 1

    return upserted


async def ingest_all(
    client: PeakonClient,
    storage: MongoStorage,
    *,
    company_id: int,
    engagement_group: str,
    per_page: int,
    full_sync: bool,
) -> Dict[str, Any]:
    run_id = str(uuid.uuid4())
    storage.record_run_start(run_id)

    stats: Dict[str, Any] = {"run_id": run_id}

    try:
        # Token cache bootstrap (optional)
        cache_id = f"{client.base_url}::application"
        cached = storage.get_cached_bearer(cache_id)
        if cached:
            client.set_bearer(cached)
        else:
            tok = await client.ensure_bearer()
            storage.set_cached_bearer(cache_id, tok)

        storage.ensure_indexes()

        stats["drivers_catalog_seeded"] = await seed_drivers_catalog(storage)

        ans_count, last_answer_id = await ingest_answers_export(
            client, storage, per_page=per_page, full_sync=full_sync, run_id=run_id
        )
        stats["answers_upserted"] = ans_count
        stats["answers_last_answer_id"] = last_answer_id

        emp_count, last_emp_id = await ingest_employees(
            client, storage, per_page=per_page, full_sync=full_sync, run_id=run_id
        )
        stats["employees_upserted"] = emp_count
        stats["employees_last_employee_id"] = last_emp_id

        driver_ids = await ingest_drivers(client, storage, run_id=run_id)
        stats["drivers_count"] = len(driver_ids)

        stats["contexts_upserted"] = await ingest_contexts(
            client, storage, company_id=company_id, engagement_group=engagement_group, run_id=run_id
        )

        stats["scores_by_driver_upserted"] = await ingest_scores_by_driver(
            client, storage, company_id=company_id, driver_ids=driver_ids, run_id=run_id
        )

        storage.record_run_finish(run_id, "success", stats)
        return stats

    except Exception as e:
        stats["error"] = str(e)
        logger.exception("Ingestion failed: %s", e)
        storage.record_run_finish(run_id, "failure", stats)
        raise
