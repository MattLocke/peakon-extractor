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


def test_org_map_filter_query_accepts_people_subdepartment():
    from peakon_api.main import _employee_filter_query

    query = _employee_filter_query("General and Administrative", "People", None)

    assert "$and" in query
    assert any("attributes.Department" in option for option in query["$and"][0]["$or"])
    assert any("attributes.Sub-Department" in option for option in query["$and"][1]["$or"])


class ScoreCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None, projection=None):
        query = query or {}
        allowed = set()
        for clause in query.get("$or", []):
            for _field, condition in clause.items():
                allowed.update(str(v) for v in condition.get("$in", []))
        if not allowed:
            return list(self.docs)
        out = []
        for doc in self.docs:
            attrs = doc.get("attributes") or {}
            emp_id = attrs.get("employeeId") or attrs.get("employee_id") or doc.get("employeeId") or doc.get("employee_id")
            if str(emp_id) in allowed:
                out.append(doc)
        return out


class ScoreDb:
    def __init__(self, scores, answers=None):
        self.scores_contexts = ScoreCollection(scores)
        self.answers_export = ScoreCollection(answers or [])


def test_engagement_scores_by_employee_uses_latest_mean():
    from peakon_api.main import _engagement_scores_by_employee

    db = ScoreDb([
        {"_id": "old", "attributes": {"employeeId": 1, "scores": {"mean": 4.2, "time": "2026-01"}}},
        {"_id": "new", "attributes": {"employeeId": "1", "scores": {"mean": 7.6, "time": "2026-02"}}},
        {"_id": "missing", "attributes": {"employeeId": 2, "scores": {"time": "2026-02"}}},
    ])

    scores = _engagement_scores_by_employee(db, [1, 2])

    assert scores["1"] == {"engagement": 7.6, "time": "2026-02", "source": "scores_contexts"}
    assert "2" not in scores


def test_engagement_scores_by_employee_falls_back_to_answer_scores():
    from peakon_api.main import _engagement_scores_by_employee

    db = ScoreDb([], [
        {"_id": "a1", "attributes": {"employeeId": 1, "answerScore": 8, "responseAnsweredAt": "2026-01-01"}},
        {"_id": "a2", "attributes": {"employeeId": "1", "answerScore": 6, "responseAnsweredAt": "2026-02-01"}},
        {"_id": "a3", "attributes": {"employeeId": 2, "answerScore": "", "responseAnsweredAt": "2026-02-01"}},
    ])

    scores = _engagement_scores_by_employee(db, [1, 2])

    assert scores["1"] == {
        "engagement": 7.0,
        "time": "2026-02-01",
        "source": "answers_export",
        "responseCount": 2,
    }
    assert "2" not in scores


def test_autonomy_scores_by_employee_falls_back_to_matching_answer_hierarchy():
    from peakon_api.main import _autonomy_scores_by_employee

    db = ScoreDb([], [
        {
            "_id": "a1",
            "attributes": {
                "employeeId": 1,
                "answerScore": 9,
                "responseAnsweredAt": "2026-01-01",
                "subDriver": "Autonomy",
            },
        },
        {
            "_id": "a2",
            "attributes": {
                "employeeId": "1",
                "answerScore": 5,
                "responseAnsweredAt": "2026-02-01",
                "driver": "Autonomy",
            },
        },
        {
            "_id": "a3",
            "attributes": {
                "employeeId": 1,
                "answerScore": 1,
                "responseAnsweredAt": "2026-02-01",
                "driver": "Recognition",
            },
        },
    ])

    scores = _autonomy_scores_by_employee(db, [1])

    assert scores["1"] == {
        "autonomy": 7.0,
        "time": "2026-02-01",
        "source": "answers_export",
        "responseCount": 2,
    }
