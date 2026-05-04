from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
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

ANSWERS_ORPHANED_MANAGER_ID = "__orphaned__"
MANAGER_VISIBILITY_THRESHOLD = 5


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


def _id_lookup_values(raw_ids: List[Any]) -> List[Any]:
    out: List[Any] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if value is None:
            return
        key = f"{type(value).__name__}:{value}"
        if key not in seen:
            seen.add(key)
            out.append(value)

    for raw_id in raw_ids:
        add(raw_id)
        raw_str = str(raw_id)
        add(raw_str)
        parsed = _parse_int(raw_str)
        if parsed is not None:
            add(parsed)

    return out


def _validate_iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except Exception:
        return None


def _nested_value(data: Dict[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = data
        found = True
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current.get(part)
            else:
                found = False
                break
        if found and current not in (None, ""):
            return current
    return None


def _english_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("en", "en-US", "en_us", "english", "English", "text", "value"):
            if key in value:
                text = _english_text(value.get(key))
                if text:
                    return text
        for nested in value.values():
            text = _english_text(nested)
            if text:
                return text
    return str(value)


def _as_lookup_ids(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    out = [value, str(value)]
    parsed = _parse_int(str(value))
    if parsed is not None:
        out.append(parsed)
    unique: List[Any] = []
    for item in out:
        if item not in unique:
            unique.append(item)
    return unique


def _answer_driver_id(answer: Dict[str, Any]) -> Any:
    attrs = answer.get("attributes") or {}
    rels = answer.get("relationships") or {}
    return _nested_value(
        attrs,
        "driverId",
        "driverID",
        "engagementDriverId",
        "engagement_driver_id",
        "driver.id",
    ) or _nested_value(
        rels,
        "driver.data.id",
        "Driver.data.id",
        "engagementDriver.data.id",
        "question.data.relationships.driver.data.id",
    )


def _driver_lookup(db: Any, driver_ids: set[Any], question_ids: set[Any]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    ids: List[Any] = []
    for value in list(driver_ids) + list(question_ids):
        ids.extend(_as_lookup_ids(value))
    if not ids:
        return lookup
    try:
        for doc in db.drivers_catalog.find({"_id": {"$in": ids}}):
            lookup[str(doc.get("_id"))] = doc
    except Exception:
        return lookup
    return lookup


def _answer_hierarchy(answer: Dict[str, Any], catalog: Dict[str, Dict[str, Any]]) -> tuple[str, str, str]:
    attrs = answer.get("attributes") or {}
    question_id = attrs.get("questionId")
    driver_id = _answer_driver_id(answer)
    catalog_doc = catalog.get(str(driver_id)) or catalog.get(str(question_id)) or {}

    category = (
        catalog_doc.get("category")
        or _nested_value(attrs, "category", "questionCategory", "group", "engagementGroup")
        or "Engagement"
    )
    driver = catalog_doc.get("driver") or _nested_value(attrs, "driver", "driverName", "questionDriver") or ""
    subdriver = (
        catalog_doc.get("subdriver")
        or catalog_doc.get("subDriver")
        or _nested_value(attrs, "subDriver", "subdriver", "subDriverName", "questionSubDriver")
        or ""
    )
    return str(category or ""), str(driver or ""), str(subdriver or "")


def _csv_response(filename: str, rows: List[List[Any]]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


def _is_orphaned_manager_filter(manager_id: Optional[str]) -> bool:
    return str(manager_id or "").strip().lower() in {ANSWERS_ORPHANED_MANAGER_ID, "orphaned"}


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


def _employee_identifier(employee: Optional[Dict[str, Any]]) -> Optional[str]:
    if not employee:
        return None
    attrs = employee.get("attributes") or {}
    for key in ("identifier", "Identifier"):
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


def _employee_manager_groups(employees: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
    groups: Dict[str, List[Any]] = {}
    for employee in employees:
        manager_value = _employee_manager_id(employee)
        if not manager_value:
            continue
        groups.setdefault(str(manager_value), []).append(employee.get("_id"))
    return groups


def _orphaned_employee_ids(employees: List[Dict[str, Any]]) -> List[Any]:
    raw_ids: List[Any] = []
    for employee_ids in _employee_manager_groups(employees).values():
        if 0 < len(employee_ids) < MANAGER_VISIBILITY_THRESHOLD:
            raw_ids.extend(employee_ids)
    return _id_lookup_values(raw_ids)


def _parse_month_name(month_raw: str) -> Optional[int]:
    m = month_raw.strip().lower()
    months = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sep": 9,
        "sept": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }
    return months.get(m)


def _parse_birthday_value(raw: Any) -> Optional[str]:
    if raw is None:
        return None

    # Occasionally date-like values are nested
    if isinstance(raw, dict):
        for key in ("value", "date", "raw", "display", "formatted"):
            if key in raw:
                parsed = _parse_birthday_value(raw.get(key))
                if parsed:
                    return parsed
        return None

    # Numeric timestamps (seconds/ms since epoch)
    if isinstance(raw, (int, float)):
        try:
            value = float(raw)
            # Ignore plain ages/small integers; accept only realistic epoch ranges.
            if value < 100_000_000:
                return None
            if value > 10_000_000_000:  # probably milliseconds
                value /= 1000.0
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
            return dt.strftime("%m/%d")
        except Exception:
            return None

    s = str(raw).strip()
    if not s:
        return None

    # ISO-like (YYYY-MM-DD or YYYY/MM/DD)
    iso = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if iso:
        month = int(iso.group(2))
        day = int(iso.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{month:02d}/{day:02d}"

    # Slash dates, possibly MM/DD[/YYYY] or DD/MM[/YYYY]
    slash = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", s)
    if slash:
        a = int(slash.group(1))
        b = int(slash.group(2))
        # Prefer MM/DD when valid; fallback to DD/MM when first part > 12
        if 1 <= a <= 12 and 1 <= b <= 31:
            return f"{a:02d}/{b:02d}"
        if 1 <= b <= 12 and 1 <= a <= 31:
            return f"{b:02d}/{a:02d}"

    # Month name formats: "March 7" or "7 March"
    m1 = re.match(r"^([A-Za-z]{3,9})\s+(\d{1,2})(?:,?\s*\d{2,4})?$", s)
    if m1:
        month = _parse_month_name(m1.group(1))
        day = int(m1.group(2))
        if month and 1 <= day <= 31:
            return f"{month:02d}/{day:02d}"

    m2 = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,9})(?:\s+\d{2,4})?$", s)
    if m2:
        day = int(m2.group(1))
        month = _parse_month_name(m2.group(2))
        if month and 1 <= day <= 31:
            return f"{month:02d}/{day:02d}"

    return None


def _employee_birthday_mmdd(employee: Dict[str, Any]) -> Optional[str]:
    attrs = employee.get("attributes") or {}

    # 1) Try canonical/common keys first
    preferred_keys = (
        "Birthday",
        "birthday",
        "Birth date",
        "birth_date",
        "Date of birth",
        "date_of_birth",
        "Birthdate",
        "birthdate",
        "DOB",
        "dob",
        # Some Peakon exports/custom mappings store birth date in an "age" field.
        "Age",
        "age",
    )
    for key in preferred_keys:
        parsed = _parse_birthday_value(attrs.get(key))
        if parsed:
            return parsed

    # 2) Fallback: any attribute key with birth/dob in the name
    for key, value in attrs.items():
        lk = str(key).lower()
        if "birth" in lk or lk == "dob":
            parsed = _parse_birthday_value(value)
            if parsed:
                return parsed

    return None


def _coerce_date_value(raw: Any) -> Optional[tuple[float, str]]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        for key in ("value", "date", "raw", "display", "formatted"):
            parsed = _coerce_date_value(raw.get(key))
            if parsed:
                return parsed
        return None
    if isinstance(raw, (int, float)):
        try:
            value = float(raw)
            if value < 100_000_000:
                return None
            if value > 10_000_000_000:
                value /= 1000.0
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
            return (dt.timestamp(), dt.date().isoformat())
        except Exception:
            return None
    s = str(raw).strip()
    if not s:
        return None
    normalized = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt.timestamp(), dt.date().isoformat())
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return (dt.timestamp(), dt.date().isoformat())
        except Exception:
            continue
    return None


def _employee_date_value(employee: Dict[str, Any], preferred_keys: tuple[str, ...], keywords: tuple[str, ...]) -> Optional[tuple[float, str]]:
    attrs = employee.get("attributes") or {}
    values: List[Any] = [attrs.get(key) for key in preferred_keys]
    for key, value in attrs.items():
        lk = str(key).lower()
        if any(keyword in lk for keyword in keywords):
            values.append(value)

    for raw in values:
        parsed = _coerce_date_value(raw)
        if parsed:
            return parsed
    return None


def _employee_hire_value(employee: Dict[str, Any]) -> Optional[tuple[float, str]]:
    return _employee_date_value(
        employee,
        (
            "Hire date",
            "hire_date",
            "hireDate",
            "Employment start date",
            "employment_start_date",
            "Employment date",
            "employment_date",
        ),
        ("hire", "employment start", "employment date"),
    )


def _employee_start_value(employee: Dict[str, Any]) -> Optional[tuple[float, str]]:
    return _employee_date_value(
        employee,
        (
            "Start date",
            "start_date",
            "startDate",
            "Hire date",
            "hire_date",
            "hireDate",
            "Employment start date",
            "employment_start_date",
            "Employment date",
            "employment_date",
        ),
        ("start", "hire", "employment"),
    )


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


def _employee_ids_matching_filter(
    department: Optional[str],
    sub_department: Optional[str],
    manager_id: Optional[str],
) -> Optional[List[Any]]:
    emp_filter = _employee_filter_query(department, sub_department, manager_id)
    if not emp_filter:
        return None

    db = get_db()
    raw_ids = [doc.get("_id") for doc in db.employees.find(emp_filter, {"_id": 1})]
    if not raw_ids:
        return []

    return _id_lookup_values(raw_ids)


def _apply_employee_scope_filter(
    base_query: Dict[str, Any],
    employee_ids: Optional[List[Any]],
    *,
    id_fields: List[str],
) -> Dict[str, Any]:
    if employee_ids is None:
        return base_query
    if not employee_ids:
        return {"_id": {"$exists": False}}

    id_match = {"$or": [{field: {"$in": employee_ids}} for field in id_fields]}
    if not base_query:
        return id_match
    return {"$and": [base_query, id_match]}


def _answer_employees_for_query(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    db = get_db()
    answer_employee_ids = db.answers_export.distinct("attributes.employeeId", query)
    if not answer_employee_ids:
        return []
    return list(
        db.employees.find(
            {"_id": {"$in": _id_lookup_values(answer_employee_ids)}},
            {"_id": 1, "attributes": 1, "relationships": 1},
        )
    )


def _apply_answers_employee_filters(
    query: Dict[str, Any],
    *,
    department: Optional[str],
    sub_department: Optional[str],
    manager_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    manager_scope = None if _is_orphaned_manager_filter(manager_id) else manager_id
    employee_scope_ids = _employee_ids_matching_filter(department, sub_department, manager_scope)
    if employee_scope_ids is not None:
        if not employee_scope_ids:
            return None
        query = _apply_employee_scope_filter(query, employee_scope_ids, id_fields=["attributes.employeeId"])

    if not _is_orphaned_manager_filter(manager_id):
        return query

    orphaned_ids = _orphaned_employee_ids(_answer_employees_for_query(query))
    if not orphaned_ids:
        return None
    return _apply_employee_scope_filter(query, orphaned_ids, id_fields=["attributes.employeeId"])


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
    if emp_id is not None and not _is_orphaned_manager_filter(manager_id):
        employee_scope_ids = _employee_ids_matching_filter(department, sub_department, manager_id)
        if employee_scope_ids is not None:
            emp_match = [v for v in employee_scope_ids if _parse_int(str(v)) == emp_id or str(v) == str(emp_id)]
            if not emp_match:
                return {"items": [], "total": 0, "skip": skip, "limit": limit, "unique_employees": 0}
            query = _apply_employee_scope_filter(query, emp_match, id_fields=["attributes.employeeId"])
    else:
        scoped_query = _apply_answers_employee_filters(
            query,
            department=department,
            sub_department=sub_department,
            manager_id=manager_id,
        )
        if scoped_query is None:
            return {"items": [], "total": 0, "skip": skip, "limit": limit, "unique_employees": 0}
        query = scoped_query
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
    db = get_db()
    if emp_id is not None and not _is_orphaned_manager_filter(manager_id):
        employee_scope_ids = _employee_ids_matching_filter(department, sub_department, manager_id)
        if employee_scope_ids is not None:
            emp_match = [v for v in employee_scope_ids if _parse_int(str(v)) == emp_id or str(v) == str(emp_id)]
            if not emp_match:
                return {"items": [], "total": 0}
            query = _apply_employee_scope_filter(query, emp_match, id_fields=["attributes.employeeId"])
    else:
        scoped_query = _apply_answers_employee_filters(
            query,
            department=department,
            sub_department=sub_department,
            manager_id=manager_id,
        )
        if scoped_query is None:
            return {"items": [], "total": 0}
        query = scoped_query

    answer_employee_ids = db.answers_export.distinct("attributes.employeeId", query)
    if not answer_employee_ids:
        return {"items": [], "total": 0}

    employees = list(
        db.employees.find(
            {"_id": {"$in": _id_lookup_values(answer_employee_ids)}},
            {"_id": 1, "attributes": 1, "relationships": 1},
        )
    )
    manager_groups = _employee_manager_groups(employees)
    manager_ids = set(manager_groups.keys())
    manager_counts = {manager_id_value: len(employee_ids) for manager_id_value, employee_ids in manager_groups.items()}

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
    orphaned_count = sum(count for count in manager_counts.values() if 0 < count < MANAGER_VISIBILITY_THRESHOLD)
    if orphaned_count:
        manager_items.insert(
            0,
            {
                "id": ANSWERS_ORPHANED_MANAGER_ID,
                "label": f"Orphaned comments (<{MANAGER_VISIBILITY_THRESHOLD} employees / manager)",
                "name": "Orphaned comments",
                "department": None,
                "count": orphaned_count,
                "kind": "orphaned",
                "threshold": MANAGER_VISIBILITY_THRESHOLD,
            },
        )
    return {"items": manager_items, "total": len(manager_items)}


@app.get("/answers_export/manager_question_csv")
def export_manager_question_csv(
    start_date: str = Query(..., description="Inclusive responseAnsweredAt/report start date"),
    end_date: str = Query(..., description="Inclusive responseAnsweredAt/report end date"),
    department: Optional[str] = None,
    sub_department: Optional[str] = None,
    manager_id: Optional[str] = None,
    min_respondents: int = Query(5, ge=1),
) -> Response:
    start = _validate_iso(start_date)
    end = _validate_iso(end_date)
    if not start or not end:
        return _csv_response(
            "manager-question-export-error.csv",
            [["error"], ["start_date and end_date must be ISO-like dates, for example 2026-01-01"]],
        )

    db = get_db()
    query: Dict[str, Any] = {}
    # Date-only end dates should include the whole selected day for ISO timestamp strings.
    end_bound = f"{end}T23:59:59.999999Z" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", end) else end
    query.update(_iso_range("attributes.responseAnsweredAt", start, end_bound))

    employee_scope_ids = _employee_ids_matching_filter(department, sub_department, manager_id)
    if employee_scope_ids is not None:
        if not employee_scope_ids:
            employee_scope_ids = []
        query = _apply_employee_scope_filter(query, employee_scope_ids, id_fields=["attributes.employeeId"])

    answers = list(db.answers_export.find(query, {"attributes": 1, "relationships": 1}))
    employee_ids = {answer.get("attributes", {}).get("employeeId") for answer in answers}
    employee_lookup_ids: set[Any] = set()
    for employee_id_value in employee_ids:
        employee_lookup_ids.update(_as_lookup_ids(employee_id_value))

    employees = list(
        db.employees.find(
            {"_id": {"$in": list(employee_lookup_ids)}},
            {"_id": 1, "attributes": 1, "relationships": 1},
        )
    )
    employees_by_id = {str(employee.get("_id")): employee for employee in employees}

    manager_lookup_ids: set[Any] = set()
    for employee in employees:
        mgr_id = _employee_manager_id(employee)
        for lookup_id in _as_lookup_ids(mgr_id):
            manager_lookup_ids.add(lookup_id)
    manager_docs = list(
        db.employees.find(
            {"_id": {"$in": list(manager_lookup_ids)}},
            {"_id": 1, "attributes": 1},
        )
    ) if manager_lookup_ids else []
    manager_docs_by_id = {str(manager.get("_id")): manager for manager in manager_docs}

    driver_ids = {_answer_driver_id(answer) for answer in answers if _answer_driver_id(answer) not in (None, "")}
    question_ids = {answer.get("attributes", {}).get("questionId") for answer in answers if answer.get("attributes", {}).get("questionId") not in (None, "")}
    catalog = _driver_lookup(db, driver_ids, question_ids)

    grouped: Dict[tuple[str, Any, str, str, str, str], Dict[str, Any]] = defaultdict(
        lambda: {"scores": [], "respondents": set()}
    )

    for answer in answers:
        attrs = answer.get("attributes") or {}
        employee_id_value = attrs.get("employeeId")
        employee = employees_by_id.get(str(employee_id_value))
        if not employee:
            continue
        mgr_id = _employee_manager_id(employee)
        if not mgr_id:
            continue
        if manager_id and str(mgr_id) != str(manager_id):
            continue

        score = attrs.get("answerScore")
        try:
            numeric_score = float(score)
        except Exception:
            continue

        question_id_value = attrs.get("questionId") or attrs.get("answerId") or answer.get("_id")
        question_text = _english_text(attrs.get("questionText") or attrs.get("question") or "")
        category, driver, subdriver = _answer_hierarchy(answer, catalog)
        key = (str(mgr_id), question_id_value, category, driver, subdriver, question_text)
        grouped[key]["scores"].append(numeric_score)
        grouped[key]["respondents"].add(str(employee_id_value))

    headers = [
        "managerId",
        "startDate",
        "endDate",
        "category",
        "driver",
        "subDriver",
        "questionId",
        "questionText",
        "respondentCount",
        "score",
    ]
    rows: List[List[Any]] = [headers]
    for (mgr_id, question_id_value, category, driver, subdriver, question_text), data in sorted(grouped.items()):
        respondent_count = len(data["respondents"])
        if respondent_count < min_respondents:
            continue
        scores = data["scores"]
        avg_score = round(sum(scores) / len(scores), 2) if scores else ""
        manager_identifier = _employee_identifier(manager_docs_by_id.get(str(mgr_id))) or mgr_id
        rows.append([
            manager_identifier,
            start_date,
            end_date,
            category,
            driver,
            subdriver,
            question_id_value,
            question_text,
            respondent_count,
            avg_score,
        ])

    safe_start = re.sub(r"[^0-9A-Za-z_-]+", "-", start_date).strip("-")
    safe_end = re.sub(r"[^0-9A-Za-z_-]+", "-", end_date).strip("-")
    return _csv_response(f"manager-question-export-{safe_start}-to-{safe_end}.csv", rows)


@app.get("/scores_contexts")
def list_scores_contexts(
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    grade: Optional[str] = None,
    impact: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    department: Optional[str] = None,
    sub_department: Optional[str] = None,
    manager_id: Optional[str] = None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if grade:
        query["attributes.grade"] = grade
    if impact:
        query["attributes.impact"] = impact
    start = _validate_iso(time_from)
    end = _validate_iso(time_to)
    query.update(_iso_range("attributes.scores.time", start, end))

    employee_ids = _employee_ids_matching_filter(department, sub_department, manager_id)
    query = _apply_employee_scope_filter(
        query,
        employee_ids,
        id_fields=[
            "attributes.employeeId",
            "attributes.employee_id",
            "employeeId",
            "employee_id",
            "attributes.respondentEmployeeId",
            "attributes.respondent_employee_id",
        ],
    )
    return _list_collection("scores_contexts", limit=limit, skip=skip, filter_query=query)


@app.get("/scores_by_driver")
def list_scores_by_driver(
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    driver_id: Optional[str] = None,
    grade: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    department: Optional[str] = None,
    sub_department: Optional[str] = None,
    manager_id: Optional[str] = None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if driver_id:
        query["driver_id"] = driver_id
    if grade:
        query["attributes.grade"] = grade
    start = _validate_iso(time_from)
    end = _validate_iso(time_to)
    query.update(_iso_range("attributes.scores.time", start, end))

    employee_ids = _employee_ids_matching_filter(department, sub_department, manager_id)
    query = _apply_employee_scope_filter(
        query,
        employee_ids,
        id_fields=[
            "attributes.employeeId",
            "attributes.employee_id",
            "employeeId",
            "employee_id",
            "attributes.respondentEmployeeId",
            "attributes.respondent_employee_id",
        ],
    )
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


@app.get("/employees/birthdays")
def list_employee_birthdays(
    department: Optional[str] = None,
    include_unassigned: bool = True,
) -> Dict[str, Any]:
    db = get_db()
    query: Dict[str, Any] = {}

    department_values = _csv_values(department)
    if department_values:
        query["$or"] = []
        for dep in department_values:
            pattern = {"$regex": re.escape(dep), "$options": "i"}
            query["$or"].append({"attributes.Department": pattern})
            query["$or"].append({"attributes.department": pattern})

    employees = list(db.employees.find(query, {"_id": 1, "attributes": 1}))
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    with_birthdays = 0
    source = "employees"

    for employee in employees:
        mmdd = _employee_birthday_mmdd(employee)
        if not mmdd:
            continue
        with_birthdays += 1

        department_name = _employee_department(employee) or "Unassigned"
        if department_name == "Unassigned" and not include_unassigned:
            continue

        grouped.setdefault(department_name, []).append(
            {
                "id": str(employee.get("_id")),
                "name": _employee_name(employee) or str(employee.get("_id")),
                "birthday": mmdd,
            }
        )

    # Fallback: some datasets carry birthday-like values only in answers_export attrs.
    if with_birthdays == 0:
        source = "answers_export_fallback"
        emp_lookup = {str(emp.get("_id")): emp for emp in employees}
        seen_emp_ids: set[str] = set()
        cursor = db.answers_export.find({}, {"attributes": 1})
        for doc in cursor:
            attrs = (doc or {}).get("attributes") or {}
            emp_id_raw = attrs.get("employeeId") or attrs.get("employee_id")
            if emp_id_raw is None:
                continue
            emp_id = str(emp_id_raw)
            if emp_id in seen_emp_ids:
                continue

            mmdd = _employee_birthday_mmdd({"attributes": attrs})
            if not mmdd:
                continue

            seen_emp_ids.add(emp_id)
            with_birthdays += 1
            employee = emp_lookup.get(emp_id)
            department_name = _employee_department(employee or {}) or "Unassigned"
            if department_name == "Unassigned" and not include_unassigned:
                continue

            grouped.setdefault(department_name, []).append(
                {
                    "id": emp_id,
                    "name": _employee_name(employee or {}) or emp_id,
                    "birthday": mmdd,
                }
            )

    def _mmdd_key(value: str) -> tuple[int, int]:
        month, day = value.split("/")
        return (int(month), int(day))

    departments = []
    for dept_name in sorted(grouped.keys()):
        employees_sorted = sorted(
            grouped[dept_name],
            key=lambda e: (_mmdd_key(e["birthday"]), str(e.get("name") or "").lower()),
        )
        departments.append({"department": dept_name, "count": len(employees_sorted), "employees": employees_sorted})

    total = sum(item["count"] for item in departments)
    return {
        "departments": departments,
        "total": total,
        "stats": {
            "employeesScanned": len(employees),
            "employeesWithBirthday": with_birthdays,
            "source": source,
        },
    }


@app.get("/employees/start-dates")
def list_employee_start_dates(
    limit: int = Query(200, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    department: Optional[str] = None,
    sub_department: Optional[str] = None,
    manager_id: Optional[str] = None,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    db = get_db()
    emp_filter = _employee_filter_query(department, sub_department, manager_id)
    query = emp_filter or {}
    employees = list(db.employees.find(query, {"_id": 1, "attributes": 1, "relationships": 1}))

    rows: List[Dict[str, Any]] = []
    search_lower = (search or "").strip().lower()

    for employee in employees:
        hire_value = _employee_hire_value(employee)
        start_value = _employee_start_value(employee)
        if not hire_value and not start_value:
            continue
        sort_ts, sort_iso = hire_value or start_value  # hire date wins when present
        name = _employee_name(employee) or str(employee.get("_id"))
        department_name = _employee_department(employee)
        attrs = employee.get("attributes") or {}
        sub_department_name = (
            attrs.get("Sub-Department") or attrs.get("sub_department") or attrs.get("sub-department")
        )
        title = (
            attrs.get("Title") or attrs.get("title") or attrs.get("Job title") or attrs.get("job_title")
        )
        if search_lower:
            haystack = " | ".join(
                [
                    str(name or ""),
                    str(employee.get("_id") or ""),
                    str(department_name or ""),
                    str(sub_department_name or ""),
                    str(title or ""),
                    str((hire_value or (None, ""))[1] or ""),
                    str((start_value or (None, ""))[1] or ""),
                ]
            ).lower()
            if search_lower not in haystack:
                continue
        rows.append(
            {
                "id": str(employee.get("_id")),
                "name": name,
                "department": str(department_name).strip() if department_name else None,
                "subDepartment": str(sub_department_name).strip() if sub_department_name else None,
                "title": str(title).strip() if title else None,
                "managerId": _employee_manager_id(employee),
                "hireDate": hire_value[1] if hire_value else None,
                "startDate": start_value[1] if start_value else None,
                "sortDate": sort_iso,
                "sortTimestamp": sort_ts,
            }
        )

    rows.sort(key=lambda row: (-row["sortTimestamp"], str(row.get("name") or "").lower(), row["id"]))
    total = len(rows)
    sliced = rows[skip : skip + limit]
    return {
        "items": sliced,
        "total": total,
        "skip": skip,
        "limit": limit,
        "unique_employees": total,
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


@app.get("/org_headcount")
def org_headcount(
    department: Optional[str] = None,
    sub_department: Optional[str] = None,
    manager_id: Optional[str] = None,
) -> Dict[str, Any]:
    db = get_db()
    emp_filter = _employee_filter_query(department, sub_department, manager_id)
    query = emp_filter or {}

    employees = list(db.employees.find(query, {"_id": 1, "attributes": 1, "relationships": 1}))
    payload = build_org_map_payload(employees)

    node_by_id = {node["id"]: node for node in payload.get("nodes", [])}
    children: Dict[str, List[str]] = {}
    for edge in payload.get("edges", []):
        children.setdefault(edge["source"], []).append(edge["target"])
    for k in list(children.keys()):
        children[k] = sorted(children[k], key=lambda cid: (node_by_id.get(cid, {}).get("label") or ""))

    rows: List[Dict[str, Any]] = []

    def walk(node_id: str, depth: int) -> None:
        node = node_by_id.get(node_id)
        if not node:
            return
        rows.append(
            {
                "id": node["id"],
                "name": node.get("label"),
                "title": node.get("title"),
                "email": node.get("email"),
                "department": node.get("department"),
                "subDepartment": node.get("subDepartment"),
                "managerId": node.get("managerId"),
                "depth": depth,
                "directReports": node.get("directReports", 0),
                "subtreeSize": node.get("subtreeSize", 1),
            }
        )
        for child_id in children.get(node_id, []):
            walk(child_id, depth + 1)

    roots = [n["id"] for n in payload.get("nodes", []) if not n.get("parentId")]
    roots = sorted(roots, key=lambda rid: (node_by_id.get(rid, {}).get("label") or ""))
    for root_id in roots:
        walk(root_id, 0)

    manager_rollup = sorted(
        [
            {
                "id": n["id"],
                "name": n.get("label"),
                "directReports": n.get("directReports", 0),
                "teamSizeInScope": n.get("subtreeSize", 1),
                "department": n.get("department"),
                "subDepartment": n.get("subDepartment"),
            }
            for n in payload.get("nodes", [])
            if int(n.get("directReports", 0) or 0) > 0
        ],
        key=lambda x: (-int(x.get("teamSizeInScope", 0) or 0), x.get("name") or ""),
    )

    return {
        "totalHeadcount": len(payload.get("nodes", [])),
        "managerCount": len(manager_rollup),
        "rows": rows,
        "managers": manager_rollup,
        "stats": payload.get("stats", {}),
    }


@app.get("/org_headcount/managers")
def org_headcount_managers(
    department: Optional[str] = None,
    sub_department: Optional[str] = None,
) -> Dict[str, Any]:
    db = get_db()
    emp_filter = _employee_filter_query(department, sub_department, None)
    query = emp_filter or {}
    employees = list(db.employees.find(query, {"_id": 1, "attributes": 1, "relationships": 1}))
    payload = build_org_map_payload(employees)

    manager_options = sorted(
        [
            {
                "id": n.get("id"),
                "name": n.get("label"),
                "label": f"{n.get('label') or n.get('id')} ({n.get('id')})",
                "teamSizeInScope": n.get("subtreeSize", 1),
                "directReports": n.get("directReports", 0),
            }
            for n in payload.get("nodes", [])
            if int(n.get("directReports", 0) or 0) > 0 and n.get("id")
        ],
        key=lambda x: (-int(x.get("teamSizeInScope", 0) or 0), x.get("name") or ""),
    )
    return {"items": manager_options, "total": len(manager_options)}


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
