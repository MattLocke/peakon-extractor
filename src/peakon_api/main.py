from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo import DESCENDING

from .db import get_db
from .org_map import build_org_map_payload

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


def _answers_export_query(
    *,
    employee_id: Optional[str],
    question_id: Optional[str],
    min_score: Optional[int],
    max_score: Optional[int],
    answered_from: Optional[str],
    answered_to: Optional[str],
    search: Optional[str],
    has_comment: Optional[bool],
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

    return query


def _employee_manager_id(employee: Dict[str, Any]) -> Optional[str]:
    relationships = employee.get("relationships") or {}
    if isinstance(relationships, dict):
        for key in ("Manager", "manager"):
            rel = relationships.get(key) or {}
            if isinstance(rel, dict):
                data = rel.get("data") or {}
                if isinstance(data, dict):
                    mgr_id = data.get("id")
                    if mgr_id is not None and str(mgr_id).strip() != "":
                        return str(mgr_id)
    attrs = employee.get("attributes") or {}
    manager = attrs.get("manager")
    if isinstance(manager, dict):
        data = manager.get("data") or {}
        if isinstance(data, dict):
            mgr_id = data.get("id")
            if mgr_id is not None and str(mgr_id).strip() != "":
                return str(mgr_id)
    return None


def _employee_name(employee: Dict[str, Any]) -> Optional[str]:
    attrs = employee.get("attributes") or {}
    first = attrs.get("First name") or attrs.get("first_name") or attrs.get("firstName")
    last = attrs.get("Last name") or attrs.get("last_name") or attrs.get("lastName")
    if first or last:
        return f"{first or ''} {last or ''}".strip()
    for key in (
        "Full name",
        "full_name",
        "fullName",
        "Name",
        "name",
        "Display name",
        "display_name",
        "displayName",
    ):
        value = attrs.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _employee_department(employee: Dict[str, Any]) -> Optional[str]:
    attrs = employee.get("attributes") or {}
    for key in ("Department", "department"):
        value = attrs.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _csv_values(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _employee_filter_query(
    department: Optional[str],
    sub_department: Optional[str],
    manager_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    conditions = []

    department_values = _csv_values(department)
    if department_values:
        department_or = []
        for dep in department_values:
            pattern = {"$regex": re.escape(dep), "$options": "i"}
            department_or.append({"attributes.Department": pattern})
            department_or.append({"attributes.department": pattern})
        conditions.append({"$or": department_or})

    sub_department_values = _csv_values(sub_department)
    if sub_department_values:
        sub_department_or = []
        for sub_dep in sub_department_values:
            pattern = {"$regex": re.escape(sub_dep), "$options": "i"}
            sub_department_or.append({"attributes.Sub-Department": pattern})
            sub_department_or.append({"attributes.sub_department": pattern})
            sub_department_or.append({"attributes.sub-department": pattern})
        conditions.append({"$or": sub_department_or})

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
    query = _answers_export_query(
        employee_id=employee_id,
        question_id=question_id,
        min_score=min_score,
        max_score=max_score,
        answered_from=answered_from,
        answered_to=answered_to,
        search=search,
        has_comment=has_comment,
    )
    emp_id = _parse_int(employee_id)
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


@app.get("/answers_export/managers")
def list_answers_export_managers(
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
    query = _answers_export_query(
        employee_id=employee_id,
        question_id=question_id,
        min_score=min_score,
        max_score=max_score,
        answered_from=answered_from,
        answered_to=answered_to,
        search=search,
        has_comment=has_comment,
    )
    emp_id = _parse_int(employee_id)
    emp_filter = _employee_filter_query(department, sub_department, manager_id)
    db = get_db()
    if emp_filter:
        employee_ids = [doc["_id"] for doc in db.employees.find(emp_filter, {"_id": 1})]
        if emp_id is not None:
            if emp_id not in employee_ids:
                return {"items": [], "total": 0}
        else:
            if not employee_ids:
                return {"items": [], "total": 0}
            query["attributes.employeeId"] = {"$in": employee_ids}

    answer_employee_ids = db.answers_export.distinct("attributes.employeeId", query)
    if not answer_employee_ids:
        return {"items": [], "total": 0}

    employees = list(
        db.employees.find(
            {"_id": {"$in": answer_employee_ids}},
            {"_id": 1, "attributes": 1, "relationships": 1},
        )
    )
    manager_ids: set[str] = set()
    manager_counts: Dict[str, int] = {}
    for employee in employees:
        manager_value = _employee_manager_id(employee)
        if manager_value:
            manager_str = str(manager_value)
            manager_ids.add(manager_str)
            manager_counts[manager_str] = manager_counts.get(manager_str, 0) + 1

    if not manager_ids:
        return {"items": [], "total": 0}

    manager_lookup_ids: set[Any] = set()
    for manager_id_value in manager_ids:
        manager_lookup_ids.add(manager_id_value)
        parsed_id = _parse_int(manager_id_value)
        if parsed_id is not None:
            manager_lookup_ids.add(parsed_id)

    managers = list(
        db.employees.find(
            {"_id": {"$in": list(manager_lookup_ids)}},
            {"_id": 1, "attributes": 1},
        )
    )
    manager_docs_by_id = {str(manager.get("_id")): manager for manager in managers}
    manager_items: list[Dict[str, Any]] = []
    for manager_id_value in sorted(manager_ids):
        manager_doc = manager_docs_by_id.get(manager_id_value)
        name = _employee_name(manager_doc) if manager_doc else None
        dept = _employee_department(manager_doc) if manager_doc else None
        label = name or manager_id_value
        if dept:
            label = f"{label} - {dept}"
        manager_items.append(
            {
                "id": manager_id_value,
                "label": label,
                "name": name,
                "department": dept,
                "count": manager_counts.get(manager_id_value, 0),
            }
        )

    manager_items.sort(key=lambda item: item["label"])
    return {"items": manager_items, "total": len(manager_items)}


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


@app.get("/employees/facets")
def employee_facets() -> Dict[str, List[str]]:
    db = get_db()
    departments = sorted(
        [
            value
            for value in db.employees.distinct("attributes.Department")
            if value is not None and str(value).strip() != ""
        ]
    )
    departments_alt = sorted(
        [
            value
            for value in db.employees.distinct("attributes.department")
            if value is not None and str(value).strip() != ""
        ]
    )
    sub_departments = sorted(
        [
            value
            for value in db.employees.distinct("attributes.Sub-Department")
            if value is not None and str(value).strip() != ""
        ]
    )
    sub_departments_alt = sorted(
        [
            value
            for value in db.employees.distinct("attributes.sub_department")
            if value is not None and str(value).strip() != ""
        ]
    )

    department_values = sorted({str(v).strip() for v in (departments + departments_alt) if str(v).strip()})
    sub_department_values = sorted(
        {str(v).strip() for v in (sub_departments + sub_departments_alt) if str(v).strip()}
    )
    return {
        "departments": department_values,
        "sub_departments": sub_department_values,
    }


@app.get("/employees/{employee_id}")
def get_employee(employee_id: str) -> Dict[str, Any]:
    db = get_db()
    emp_id = _parse_int(employee_id)
    query: Dict[str, Any] = {"_id": emp_id} if emp_id is not None else {"_id": employee_id}
    doc = db.employees.find_one(query)
    if not doc:
        return {"employee": None}
    return {"employee": _serialize(doc)}


@app.get("/org_map")
def org_map(department: Optional[str] = None, manager_id: Optional[str] = None) -> Dict[str, Any]:
    db = get_db()
    query: Dict[str, Any] = {}

    department_values = _csv_values(department)
    if department_values:
        query["$or"] = []
        for dep in department_values:
            pattern = {"$regex": re.escape(dep), "$options": "i"}
            query["$or"].append({"attributes.Department": pattern})
            query["$or"].append({"attributes.department": pattern})

    employees = list(db.employees.find(query, {"_id": 1, "attributes": 1, "relationships": 1}))
    payload = build_org_map_payload(employees)

    if manager_id:
        manager_str = str(manager_id)
        node_lookup = {node["id"]: node for node in payload["nodes"]}
        if manager_str not in node_lookup:
            payload["nodes"] = []
            payload["edges"] = []
            payload["stats"]["renderedNodes"] = 0
            payload["stats"]["renderedEdges"] = 0
            return payload

        keep: set[str] = set([manager_str])
        children_by_parent: Dict[str, List[str]] = {}
        for edge in payload["edges"]:
            children_by_parent.setdefault(edge["source"], []).append(edge["target"])

        queue = [manager_str]
        while queue:
            parent = queue.pop(0)
            for child in children_by_parent.get(parent, []):
                if child not in keep:
                    keep.add(child)
                    queue.append(child)

        payload["nodes"] = [node for node in payload["nodes"] if node["id"] in keep]
        payload["edges"] = [edge for edge in payload["edges"] if edge["source"] in keep and edge["target"] in keep]
        payload["rootId"] = manager_str
        payload["stats"]["renderedNodes"] = len(payload["nodes"])
        payload["stats"]["renderedEdges"] = len(payload["edges"])

    return _serialize(payload)
