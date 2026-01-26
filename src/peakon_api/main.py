from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo import DESCENDING

from .db import get_db

app = FastAPI(title="Peakon Browse API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _serialize(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


def _list_collection(
    name: str,
    *,
    limit: int,
    skip: int,
    filter_query: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    db = get_db()
    coll = db[name]
    query = filter_query or {}
    cursor = coll.find(query).sort("_id", DESCENDING).skip(skip).limit(limit)
    items = [_serialize(doc) for doc in cursor]
    total = coll.count_documents(query)
    return {"items": items, "total": total, "skip": skip, "limit": limit}


def _iso_range(field: str, start: Optional[str], end: Optional[str]) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if start:
        query["$gte"] = start
    if end:
        query["$lte"] = end
    if not query:
        return {}
    return {field: query}


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _validate_iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except Exception:
        return None


def _employee_filter_query(
    department: Optional[str],
    sub_department: Optional[str],
    manager_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    conditions = []

    if department:
        pattern = {"$regex": re.escape(department), "$options": "i"}
        conditions.append(
            {
                "$or": [
                    {"attributes.Department": pattern},
                    {"attributes.department": pattern},
                ]
            }
        )

    if sub_department:
        pattern = {"$regex": re.escape(sub_department), "$options": "i"}
        conditions.append(
            {
                "$or": [
                    {"attributes.Sub-Department": pattern},
                    {"attributes.sub_department": pattern},
                    {"attributes.sub-department": pattern},
                ]
            }
        )

    if manager_id:
        manager_value = str(_parse_int(manager_id) or manager_id)
        conditions.append(
            {
                "$or": [
                    {"relationships.Manager.data.id": manager_value},
                    {"relationships.manager.data.id": manager_value},
                ]
            }
        )

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/answers_export")
def list_answers_export(
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    employee_id: Optional[str] = None,
    question_id: Optional[str] = None,
    min_score: Optional[int] = Query(None, ge=0, le=10),
    max_score: Optional[int] = Query(None, ge=0, le=10),
    answered_from: Optional[str] = None,
    answered_to: Optional[str] = None,
    search: Optional[str] = None,
    department: Optional[str] = None,
    sub_department: Optional[str] = None,
    manager_id: Optional[str] = None,
    has_comment: Optional[bool] = None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    emp_id = _parse_int(employee_id)
    q_id = _parse_int(question_id)
    if emp_id is not None:
        query["attributes.employeeId"] = emp_id
    if q_id is not None:
        query["attributes.questionId"] = q_id
    if min_score is not None or max_score is not None:
        score_query: Dict[str, Any] = {}
        if min_score is not None:
            score_query["$gte"] = min_score
        if max_score is not None:
            score_query["$lte"] = max_score
        query["attributes.answerScore"] = score_query
    start = _validate_iso(answered_from)
    end = _validate_iso(answered_to)
    query.update(_iso_range("attributes.responseAnsweredAt", start, end))
    if search:
        query["$or"] = [
            {"attributes.questionText": {"$regex": search, "$options": "i"}},
            {"attributes.answerComment": {"$regex": search, "$options": "i"}},
            {"attributes.accountEmail": {"$regex": search, "$options": "i"}},
        ]

    comment_filter: Optional[Dict[str, Any]] = None
    if has_comment is True:
        comment_filter = {"attributes.answerComment": {"$exists": True, "$nin": ["", None]}}
    elif has_comment is False:
        comment_filter = {
            "$or": [
                {"attributes.answerComment": {"$exists": False}},
                {"attributes.answerComment": None},
                {"attributes.answerComment": ""},
            ]
        }

    if comment_filter:
        if "$or" in query:
            or_clause = query.pop("$or")
            and_parts = [{"$or": or_clause}, comment_filter]
            if query:
                and_parts.append(query)
            query = {"$and": and_parts}
        else:
            if query:
                query = {"$and": [query, comment_filter]}
            else:
                query = comment_filter
    emp_filter = _employee_filter_query(department, sub_department, manager_id)
    if emp_filter:
        db = get_db()
        employee_ids = [doc["_id"] for doc in db.employees.find(emp_filter, {"_id": 1})]
        if emp_id is not None:
            if emp_id not in employee_ids:
                return {"items": [], "total": 0, "skip": skip, "limit": limit, "unique_employees": 0}
        else:
            if not employee_ids:
                return {"items": [], "total": 0, "skip": skip, "limit": limit, "unique_employees": 0}
            query["attributes.employeeId"] = {"$in": employee_ids}
    result = _list_collection("answers_export", limit=limit, skip=skip, filter_query=query)
    db = get_db()
    result["unique_employees"] = len(db.answers_export.distinct("attributes.employeeId", query))
    return result


@app.get("/scores_contexts")
def list_scores_contexts(
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    grade: Optional[str] = None,
    impact: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if grade:
        query["attributes.grade"] = grade
    if impact:
        query["attributes.impact"] = impact
    start = _validate_iso(time_from)
    end = _validate_iso(time_to)
    query.update(_iso_range("attributes.scores.time", start, end))
    return _list_collection("scores_contexts", limit=limit, skip=skip, filter_query=query)


@app.get("/scores_by_driver")
def list_scores_by_driver(
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    driver_id: Optional[str] = None,
    grade: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if driver_id:
        query["driver_id"] = driver_id
    if grade:
        query["attributes.grade"] = grade
    start = _validate_iso(time_from)
    end = _validate_iso(time_to)
    query.update(_iso_range("attributes.scores.time", start, end))
    return _list_collection("scores_by_driver", limit=limit, skip=skip, filter_query=query)


@app.get("/employees/{employee_id}")
def get_employee(employee_id: str) -> Dict[str, Any]:
    db = get_db()
    emp_id = _parse_int(employee_id)
    query: Dict[str, Any] = {"_id": emp_id} if emp_id is not None else {"_id": employee_id}
    doc = db.employees.find_one(query)
    if not doc:
        return {"employee": None}
    return {"employee": _serialize(doc)}
