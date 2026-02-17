from peakon_api.org_map import build_org_map_payload


def test_build_org_map_payload_basic_hierarchy():
    employees = [
        {
            "_id": 1,
            "attributes": {"First name": "CEO", "Last name": "One", "Department": "Exec"},
            "relationships": {},
        },
        {
            "_id": 2,
            "attributes": {"First name": "Mgr", "Last name": "Two", "Department": "Ops"},
            "relationships": {"Manager": {"data": {"id": "1"}}},
        },
        {
            "_id": 3,
            "attributes": {"First name": "IC", "Last name": "Three", "Department": "Ops"},
            "relationships": {"Manager": {"data": {"id": "2"}}},
        },
    ]

    payload = build_org_map_payload(employees)

    assert payload["stats"]["employees"] == 3
    assert payload["stats"]["renderedEdges"] == 2
    assert payload["rootId"] == "1"

    nodes = {n["id"]: n for n in payload["nodes"]}
    assert nodes["1"]["depth"] == 0
    assert nodes["2"]["depth"] == 1
    assert nodes["3"]["depth"] == 2


def test_build_org_map_payload_orphan_detection():
    employees = [
        {
            "_id": 10,
            "attributes": {"First name": "Solo", "Last name": "Person"},
            "relationships": {"Manager": {"data": {"id": "9999"}}},
        }
    ]

    payload = build_org_map_payload(employees)
    assert payload["stats"]["orphans"] == 1
    assert payload["anomalies"]["orphans"][0]["id"] == "10"
