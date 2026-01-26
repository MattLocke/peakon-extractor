from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient

from peakon_ingest.config import get_settings


@lru_cache
def _settings():
    return get_settings()


@lru_cache
def _client() -> MongoClient:
    settings = _settings()
    return MongoClient(settings.mongo_uri)


def get_db():
    settings = _settings()
    return _client()[settings.mongo_db]
