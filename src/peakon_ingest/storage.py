from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from typing import Any, Dict, Optional

from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database

logger = logging.getLogger(__name__)


class MongoStorage:
    def __init__(self, mongo_uri: str, db_name: str):
        self.client = MongoClient(mongo_uri)
        self.db: Database = self.client[db_name]

    def ensure_indexes(self) -> None:
        # auth_tokens
        self.db.auth_tokens.create_index([("_id", ASCENDING)])

        # sync_state
        self.db.sync_state.create_index([("_id", ASCENDING)])

        # main collections
        self.db.answers_export.create_index([("_id", ASCENDING)])
        self.db.employees.create_index([("_id", ASCENDING)])
        self.db.drivers.create_index([("_id", ASCENDING)])
        self.db.drivers_catalog.create_index([("_id", ASCENDING)])

        self.db.scores_contexts.create_index([("_id", ASCENDING)])
        self.db.scores_by_driver.create_index([("_id", ASCENDING)])

        self.db.ingestion_runs.create_index([("_id", ASCENDING)])

    # --- auth token cache ---
    def get_cached_bearer(self, cache_id: str) -> Optional[str]:
        doc = self.db.auth_tokens.find_one({"_id": cache_id})
        if doc and isinstance(doc.get("bearer_token"), str):
            return doc["bearer_token"]
        return None

    def set_cached_bearer(self, cache_id: str, bearer_token: str) -> None:
        self.db.auth_tokens.update_one(
            {"_id": cache_id},
            {"$set": {"bearer_token": bearer_token, "obtained_at": dt.datetime.utcnow()}},
            upsert=True,
        )

    # --- sync state ---
    def get_state(self, key: str) -> Dict[str, Any]:
        return self.db.sync_state.find_one({"_id": key}) or {"_id": key}

    def set_state(self, key: str, state: Dict[str, Any]) -> None:
        state = dict(state)
        state["_id"] = key
        state["updated_at"] = dt.datetime.utcnow()
        self.db.sync_state.update_one({"_id": key}, {"$set": state}, upsert=True)

    # --- upserts ---
    def upsert_doc(self, collection: str, _id: Any, doc: Dict[str, Any]) -> None:
        self.db[collection].update_one(
            {"_id": _id},
            {"$set": doc},
            upsert=True,
        )

    def record_run_start(self, run_id: str) -> None:
        self.db.ingestion_runs.update_one(
            {"_id": run_id},
            {"$set": {"started_at": dt.datetime.utcnow(), "status": "running"}},
            upsert=True,
        )

    def record_run_finish(self, run_id: str, status: str, stats: Dict[str, Any]) -> None:
        self.db.ingestion_runs.update_one(
            {"_id": run_id},
            {"$set": {"finished_at": dt.datetime.utcnow(), "status": status, "stats": stats}},
            upsert=True,
        )
