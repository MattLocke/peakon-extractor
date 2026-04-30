#!/usr/bin/env python3
"""Audit manager-question CSV hierarchy lookup coverage.

Usage:
  PYTHONPATH=src python scripts/audit_manager_question_lookup.py --start 2026-01-01 --end 2026-03-31
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from typing import Any

from peakon_api.db import get_db
from peakon_api.main import _answer_driver_id, _as_lookup_ids, _english_text, _nested_value


def end_bound(value: str) -> str:
    return f"{value}T23:59:59.999999Z" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else value


def as_id_set(value: Any) -> set[Any]:
    return set(_as_lookup_ids(value))





def scalar_attrs(doc: dict[str, Any]) -> dict[str, Any]:
    attrs = doc.get("attributes") or {}
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
    return out


def subdriver_keys(payload: Any, limit: int = 30) -> list[str]:
    if isinstance(payload, dict):
        return [str(key) for key in list(payload.keys())[:limit]]
    if isinstance(payload, list):
        keys: list[str] = []
        for item in payload[:limit]:
            if isinstance(item, dict):
                for candidate in ("id", "key", "name", "label", "slug"):
                    if item.get(candidate) not in (None, ""):
                        keys.append(str(item.get(candidate)))
                        break
            else:
                keys.append(str(item))
        return keys
    return []

def truncate_jsonish(value: Any, *, max_chars: int = 1200) -> Any:
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= max_chars:
        return value
    return text[:max_chars] + "…"


def raw_subdriver_payload(doc: dict[str, Any]) -> Any:
    attrs = doc.get("attributes") or {}
    for path in ("subdriver", "scores.subdrivers", "changes.previous.subdrivers", "changes.first.subdrivers"):
        value = _nested_value(attrs, path)
        if value not in (None, "", [], {}):
            return value
    return None

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

def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Peakon sub-driver lookup coverage for manager question CSV exports.")
    parser.add_argument("--start", required=True, help="Inclusive responseAnsweredAt start date/timestamp")
    parser.add_argument("--end", required=True, help="Inclusive responseAnsweredAt end date/timestamp")
    parser.add_argument("--sample", type=int, default=10, help="Number of sample missing IDs to print")
    parser.add_argument("--missing-csv", help="Optional path to write missing questionId examples for lookup-table completion")
    args = parser.parse_args()

    db = get_db()
    query = {
        "attributes.responseAnsweredAt": {
            "$gte": args.start,
            "$lte": end_bound(args.end),
        }
    }

    catalog_docs = list(db.drivers_catalog.find({}, {"_id": 1, "category": 1, "driver": 1, "subdriver": 1, "subDriver": 1}))
    catalog_by_id = {str(doc.get("_id")): doc for doc in catalog_docs}
    catalog_subdriver_docs = [doc for doc in catalog_docs if doc.get("subdriver") or doc.get("subDriver")]

    raw_driver_docs = list(db.drivers.find({}, {"_id": 1, "id": 1, "attributes": 1, "relationships": 1}).limit(200))
    raw_driver_ids = [str(doc.get("_id") or doc.get("id")) for doc in raw_driver_docs]
    raw_driver_subdriver_paths: Counter[str] = Counter()
    raw_driver_question_paths: Counter[str] = Counter()
    raw_subdriver_examples = []
    for doc in raw_driver_docs:
        for path in find_key_paths(doc, "subdriver"):
            raw_driver_subdriver_paths[path] += 1
        for path in find_key_paths(doc, "question"):
            raw_driver_question_paths[path] += 1
        payload = raw_subdriver_payload(doc)
        if payload not in (None, "", [], {}) and len(raw_subdriver_examples) < args.sample:
            raw_subdriver_examples.append({
                "driverId": str(doc.get("_id") or doc.get("id") or ""),
                "scalarAttributes": scalar_attrs(doc),
                "subdriverKeys": subdriver_keys(payload),
                "subdriverPayloadExample": truncate_jsonish(payload),
            })

    answers_seen = 0
    driver_ids: Counter[str] = Counter()
    question_ids: Counter[str] = Counter()
    matched_by_driver = 0
    matched_by_question = 0
    matched_with_subdriver = 0
    payload_subdriver = 0
    no_lookup_key = 0
    missing_driver_ids: Counter[str] = Counter()
    missing_question_ids: Counter[str] = Counter()
    question_text_examples: dict[str, Counter[str]] = {}

    cursor = db.answers_export.find(query, {"attributes": 1, "relationships": 1})
    for answer in cursor:
        answers_seen += 1
        attrs = answer.get("attributes") or {}
        driver_id = _answer_driver_id(answer)
        question_id = attrs.get("questionId")
        payload_sub = _nested_value(attrs, "subDriver", "subdriver", "subDriverName", "questionSubDriver")
        if payload_sub:
            payload_subdriver += 1
        if driver_id not in (None, ""):
            driver_ids[str(driver_id)] += 1
        if question_id not in (None, ""):
            question_ids[str(question_id)] += 1
        if driver_id in (None, "") and question_id in (None, ""):
            no_lookup_key += 1
            continue

        driver_doc = catalog_by_id.get(str(driver_id)) if driver_id not in (None, "") else None
        question_doc = catalog_by_id.get(str(question_id)) if question_id not in (None, "") else None
        doc = driver_doc or question_doc
        if driver_doc:
            matched_by_driver += 1
        elif driver_id not in (None, ""):
            missing_driver_ids[str(driver_id)] += 1
        if question_doc:
            matched_by_question += 1
        elif question_id not in (None, ""):
            question_key = str(question_id)
            missing_question_ids[question_key] += 1
            question_text = _english_text(attrs.get("questionText") or attrs.get("question") or "")
            if question_text:
                question_text_examples.setdefault(question_key, Counter())[question_text] += 1
        if doc and (doc.get("subdriver") or doc.get("subDriver")):
            matched_with_subdriver += 1

    report = {
        "window": {"start": args.start, "end": args.end},
        "driversCatalog": {
            "totalDocs": len(catalog_docs),
            "docsWithSubdriver": len(catalog_subdriver_docs),
            "subdriverExamples": catalog_subdriver_docs[: args.sample],
        },
        "rawDriversCollection": {
            "sampledDocs": len(raw_driver_docs),
            "sampleIds": raw_driver_ids[: args.sample],
            "subdriverKeyPaths": raw_driver_subdriver_paths.most_common(args.sample),
            "questionKeyPaths": raw_driver_question_paths.most_common(args.sample),
            "subdriverPayloadExamples": raw_subdriver_examples,
        },
        "answersExport": {
            "answersSeen": answers_seen,
            "answersWithDriverId": sum(driver_ids.values()),
            "uniqueDriverIds": len(driver_ids),
            "answersWithQuestionId": sum(question_ids.values()),
            "uniqueQuestionIds": len(question_ids),
            "answersWithPayloadSubdriver": payload_subdriver,
            "answersWithoutAnyLookupKey": no_lookup_key,
        },
        "lookupCoverage": {
            "answersMatchedByDriverId": matched_by_driver,
            "answersMatchedByQuestionId": matched_by_question,
            "answersMatchedToCatalogSubdriver": matched_with_subdriver,
            "pctAnswersMatchedToCatalogSubdriver": round((matched_with_subdriver / answers_seen) * 100, 2) if answers_seen else 0,
        },
        "samples": {
            "topDriverIdsInAnswers": driver_ids.most_common(args.sample),
            "topQuestionIdsInAnswers": question_ids.most_common(args.sample),
            "missingDriverIds": missing_driver_ids.most_common(args.sample),
            "missingQuestionIds": missing_question_ids.most_common(args.sample),
            "missingQuestionTextExamples": [
                {
                    "questionId": question_id,
                    "answerCount": count,
                    "questionText": (question_text_examples.get(question_id) or Counter()).most_common(1)[0][0]
                    if question_text_examples.get(question_id)
                    else "",
                }
                for question_id, count in missing_question_ids.most_common(args.sample)
            ],
        },
    }

    if args.missing_csv:
        with open(args.missing_csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["questionId", "answerCount", "questionText", "category", "driver", "subDriver"])
            for question_id, count in missing_question_ids.most_common():
                examples = question_text_examples.get(question_id) or Counter()
                question_text = examples.most_common(1)[0][0] if examples else ""
                writer.writerow([question_id, count, question_text, "", "", ""])
        report["missingCsv"] = args.missing_csv

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
