#!/usr/bin/env python3
"""Probe likely Peakon API endpoints for question/driver/subdriver metadata.

Usage inside Docker:
  python scripts/probe_peakon_question_metadata.py

The goal is to find an endpoint that bridges answers_export.attributes.questionId
(numeric) to driver/subdriver metadata.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import httpx

from peakon_ingest.config import get_settings
from peakon_ingest.http import PeakonClient


CANDIDATE_PATHS = [
    "/questions",
    "/engagement/questions",
    "/engagement/questions?per_page=100",
    "/engagement/drivers/questions",
    "/engagement/drivers/questions?per_page=100",
    "/engagement/drivers/{driver_id}/questions",
    "/engagement/drivers/{driver_id}/questions?per_page=100",
    "/drivers/{driver_id}/questions",
    "/drivers/{driver_id}/questions?per_page=100",
    "/scores/questions/company_{company_id}/group/{driver_id}",
    "/scores/questions/company_{company_id}/group/{driver_id}?per_page=100",
    "/question-library",
    "/question_library",
    "/survey/questions",
    "/surveys/questions",
    "/surveys/templates",
]


def truncate(value: Any, limit: int) -> Any:
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return value
    return text[:limit] + "…"


def find_key_paths(value: Any, needle: str, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if needle.lower() in str(key).lower():
                paths.append(path)
            paths.extend(find_key_paths(child, needle, path))
    elif isinstance(value, list):
        for i, child in enumerate(value[:5]):
            paths.extend(find_key_paths(child, needle, f"{prefix}[{i}]"))
    return paths


async def probe_path(client: PeakonClient, path: str, *, sample_chars: int) -> dict[str, Any]:
    try:
        payload = await client.get_json_with_reauth_on_401(path)
    except httpx.HTTPStatusError as exc:
        response = exc.response
        return {
            "path": path,
            "ok": False,
            "status": response.status_code if response is not None else None,
            "body": (response.text[:300] if response is not None else ""),
        }
    except Exception as exc:
        return {"path": path, "ok": False, "error": str(exc)}

    data = payload.get("data") if isinstance(payload, dict) else None
    first = None
    if isinstance(data, list) and data:
        first = data[0]
    elif isinstance(data, dict):
        first = data

    haystack = first if first is not None else payload
    return {
        "path": path,
        "ok": True,
        "dataType": type(data).__name__,
        "dataCount": len(data) if isinstance(data, list) else None,
        "idExamples": [item.get("id") for item in data[:5] if isinstance(item, dict)] if isinstance(data, list) else [],
        "questionKeyPaths": find_key_paths(haystack, "question"),
        "driverKeyPaths": find_key_paths(haystack, "driver"),
        "subdriverKeyPaths": find_key_paths(haystack, "subdriver"),
        "sample": truncate(haystack, sample_chars),
    }


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Probe likely Peakon question metadata endpoints.")
    parser.add_argument("--driver-id", default="engagement", help="Driver slug to substitute into driver-specific candidate paths")
    parser.add_argument("--sample-chars", type=int, default=1200, help="Max chars for successful endpoint sample payloads")
    parser.add_argument("--all", action="store_true", help="Print all results, including 404/422 failures")
    args = parser.parse_args()

    settings = get_settings()
    client = PeakonClient(settings.peakon_base_url, settings.peakon_app_token, settings.http_timeout_seconds)
    try:
        results = []
        for template in CANDIDATE_PATHS:
            path = template.format(company_id=settings.peakon_company_id, driver_id=args.driver_id)
            result = await probe_path(client, path, sample_chars=args.sample_chars)
            if args.all or result.get("ok"):
                results.append(result)
        print(json.dumps({"baseUrl": settings.peakon_base_url, "results": results}, indent=2, default=str, ensure_ascii=False))
    finally:
        await client.aclose()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
