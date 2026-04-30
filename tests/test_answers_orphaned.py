from peakon_api.main import (
    ANSWERS_ORPHANED_MANAGER_ID,
    MANAGER_VISIBILITY_THRESHOLD,
    _is_orphaned_manager_filter,
    _orphaned_employee_ids,
)


def _employee(employee_id, manager_id=None):
    relationships = {}
    if manager_id is not None:
        relationships = {"Manager": {"data": {"id": str(manager_id)}}}
    return {"_id": employee_id, "attributes": {}, "relationships": relationships}


def test_orphaned_manager_filter_aliases():
    assert _is_orphaned_manager_filter(ANSWERS_ORPHANED_MANAGER_ID)
    assert _is_orphaned_manager_filter("orphaned")
    assert not _is_orphaned_manager_filter("12345")


def test_orphaned_employee_ids_include_groups_below_visibility_threshold():
    employees = [
        *[_employee(i, "small") for i in range(1, MANAGER_VISIBILITY_THRESHOLD)],
        *[_employee(i, "visible") for i in range(10, 10 + MANAGER_VISIBILITY_THRESHOLD)],
        _employee(99, None),
    ]

    orphaned_ids = _orphaned_employee_ids(employees)
    orphaned_int_ids = {value for value in orphaned_ids if isinstance(value, int)}

    assert orphaned_int_ids == set(range(1, MANAGER_VISIBILITY_THRESHOLD))
