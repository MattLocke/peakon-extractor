from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from math import cos, pi, sin
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class EmployeeNode:
    id: str
    name: str
    email: Optional[str]
    department: Optional[str]
    sub_department: Optional[str]
    country: Optional[str]
    title: Optional[str]
    manager_id: Optional[str]


def _attr(attrs: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = attrs.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _employee_name(attrs: Dict[str, Any], fallback_id: str) -> str:
    first = _attr(attrs, ["First name", "first_name", "firstName"])
    last = _attr(attrs, ["Last name", "last_name", "lastName"])
    if first or last:
        return f"{first or ''} {last or ''}".strip()

    return (
        _attr(
            attrs,
            [
                "Full name",
                "full_name",
                "fullName",
                "Display name",
                "display_name",
                "displayName",
                "Name",
                "name",
            ],
        )
        or fallback_id
    )


def _manager_id(employee: Dict[str, Any]) -> Optional[str]:
    relationships = employee.get("relationships") or {}
    if isinstance(relationships, dict):
        for key in ("Manager", "manager"):
            rel = relationships.get(key) or {}
            if isinstance(rel, dict):
                data = rel.get("data") or {}
                if isinstance(data, dict):
                    manager_id = data.get("id")
                    if manager_id is not None and str(manager_id).strip() != "":
                        return str(manager_id)

    attrs = employee.get("attributes") or {}
    manager = attrs.get("manager")
    if isinstance(manager, dict):
        data = manager.get("data") or {}
        if isinstance(data, dict):
            manager_id = data.get("id")
            if manager_id is not None and str(manager_id).strip() != "":
                return str(manager_id)
    return None


def _coerce_employee(employee: Dict[str, Any]) -> EmployeeNode:
    raw_id = employee.get("_id", employee.get("id"))
    node_id = str(raw_id)
    attrs = employee.get("attributes") or {}

    return EmployeeNode(
        id=node_id,
        name=_employee_name(attrs, node_id),
        email=_attr(attrs, ["Email", "email", "accountEmail"]),
        department=_attr(attrs, ["Department", "department"]),
        sub_department=_attr(attrs, ["Sub-Department", "sub_department", "sub-department"]),
        country=_attr(attrs, ["Country", "country"]),
        title=_attr(attrs, ["Title", "title", "Job title", "job_title"]),
        manager_id=_manager_id(employee),
    )


def build_org_map_payload(employees: List[Dict[str, Any]]) -> Dict[str, Any]:
    nodes_by_id: Dict[str, EmployeeNode] = {}
    duplicates: List[str] = []

    for doc in employees:
        node = _coerce_employee(doc)
        if node.id in nodes_by_id:
            duplicates.append(node.id)
            continue
        nodes_by_id[node.id] = node

    children: Dict[str, List[str]] = defaultdict(list)
    roots: List[str] = []
    orphans: List[Dict[str, str]] = []

    for node in nodes_by_id.values():
        manager_id = node.manager_id
        if not manager_id:
            roots.append(node.id)
            continue
        if manager_id not in nodes_by_id:
            orphans.append({"id": node.id, "managerId": manager_id})
            roots.append(node.id)
            continue
        children[manager_id].append(node.id)

    # If no obvious root, pick deterministically.
    if not roots and nodes_by_id:
        roots = [sorted(nodes_by_id.keys())[0]]

    # Build BFS layers from all roots.
    depth_by_id: Dict[str, int] = {}
    parent_by_id: Dict[str, Optional[str]] = {}
    queue = deque([(root_id, 0, None) for root_id in roots])

    while queue:
        current, depth, parent = queue.popleft()
        if current in depth_by_id:
            continue
        depth_by_id[current] = depth
        parent_by_id[current] = parent
        for child in children.get(current, []):
            queue.append((child, depth + 1, current))

    disconnected = [node_id for node_id in nodes_by_id if node_id not in depth_by_id]
    for node_id in disconnected:
        depth_by_id[node_id] = 0
        parent_by_id[node_id] = None
        roots.append(node_id)

    # Compute subtree sizes with memoized DFS.
    subtree_cache: Dict[str, int] = {}

    def subtree_size(node_id: str, seen: Optional[set[str]] = None) -> int:
        if node_id in subtree_cache:
            return subtree_cache[node_id]
        seen = seen or set()
        if node_id in seen:
            return 1
        seen.add(node_id)
        total = 1
        for child in children.get(node_id, []):
            total += subtree_size(child, seen.copy())
        subtree_cache[node_id] = total
        return total

    layer_members: Dict[int, List[str]] = defaultdict(list)
    for node_id, depth in depth_by_id.items():
        layer_members[depth].append(node_id)

    coords: Dict[str, Tuple[float, float]] = {}
    layer_gap = 170.0
    base_radius = 30.0
    for depth, members in sorted(layer_members.items()):
        members_sorted = sorted(members)
        radius = base_radius + (depth * layer_gap)
        count = len(members_sorted)
        for idx, node_id in enumerate(members_sorted):
            if depth == 0 and count == 1:
                coords[node_id] = (0.0, 0.0)
                continue
            theta = (2 * pi * idx) / max(count, 1)
            coords[node_id] = (radius * cos(theta), radius * sin(theta))

    node_payloads: List[Dict[str, Any]] = []
    for node_id, node in nodes_by_id.items():
        x, y = coords.get(node_id, (0.0, 0.0))
        node_payloads.append(
            {
                "id": node_id,
                "label": node.name,
                "email": node.email,
                "department": node.department,
                "subDepartment": node.sub_department,
                "country": node.country,
                "title": node.title,
                "managerId": node.manager_id,
                "parentId": parent_by_id.get(node_id),
                "depth": depth_by_id.get(node_id, 0),
                "directReports": len(children.get(node_id, [])),
                "subtreeSize": subtree_size(node_id),
                "x": round(x, 2),
                "y": round(y, 2),
            }
        )

    edge_payloads: List[Dict[str, str]] = []
    for manager_id, reports in children.items():
        for report_id in reports:
            edge_payloads.append({"source": manager_id, "target": report_id})

    root_id = sorted(roots)[0] if roots else None

    return {
        "rootId": root_id,
        "stats": {
            "employees": len(nodes_by_id),
            "renderedNodes": len(node_payloads),
            "renderedEdges": len(edge_payloads),
            "maxDepth": max(depth_by_id.values()) if depth_by_id else 0,
            "orphans": len(orphans),
            "duplicates": len(duplicates),
        },
        "anomalies": {
            "orphans": orphans,
            "duplicates": sorted(set(duplicates)),
        },
        "nodes": sorted(node_payloads, key=lambda n: (n["depth"], n["label"])),
        "edges": edge_payloads,
    }
