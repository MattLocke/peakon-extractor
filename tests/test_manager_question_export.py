import csv
import io

from peakon_api import main


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None, projection=None):
        query = query or {}
        in_ids = None
        if isinstance(query.get("_id"), dict):
            in_ids = set(query["_id"].get("$in", []))
        attr_date = query.get("attributes.responseAnsweredAt", {})
        out = []
        for doc in self.docs:
            if in_ids is not None and doc.get("_id") not in in_ids:
                continue
            answered_at = (doc.get("attributes") or {}).get("responseAnsweredAt")
            if attr_date:
                if answered_at < attr_date.get("$gte", answered_at):
                    continue
                if answered_at > attr_date.get("$lte", answered_at):
                    continue
            out.append(doc)
        return out


class FakeDb:
    def __init__(self, answers, employees, catalog):
        self.answers_export = FakeCollection(answers)
        self.employees = FakeCollection(employees)
        self.drivers_catalog = FakeCollection(catalog)


def manager_employee(emp_id, manager_id):
    return {
        "_id": emp_id,
        "relationships": {"Manager": {"data": {"id": str(manager_id)}}},
        "attributes": {},
    }


def answer(answer_id, emp_id, question_id, score, text, driver_id=1527181):
    return {
        "_id": answer_id,
        "attributes": {
            "answerId": answer_id,
            "employeeId": emp_id,
            "questionId": question_id,
            "questionText": {"en": text, "de": "nicht verwendet"},
            "answerScore": score,
            "responseAnsweredAt": "2026-01-15",
            "driverId": driver_id,
        },
    }


def test_manager_question_csv_groups_by_manager_question_and_suppresses_small_groups(monkeypatch):
    answers = [
        answer(100 + i, i, 9001, score, "My manager supports me")
        for i, score in enumerate([8, 9, 7, 10, 6], start=1)
    ]
    answers += [
        answer(200 + i, i, 9001, 10, "My manager supports me")
        for i in range(6, 10)
    ]
    employees = [manager_employee(i, 500) for i in range(1, 6)] + [manager_employee(i, 501) for i in range(6, 10)]
    catalog = [{"_id": 1527181, "category": "Engagement", "driver": "Management Support", "subdriver": "Coaching"}]
    monkeypatch.setattr(main, "get_db", lambda: FakeDb(answers, employees, catalog))

    response = main.export_manager_question_csv(start_date="2026-01-01", end_date="2026-01-31", min_respondents=5)
    rows = list(csv.DictReader(io.StringIO(response.body.decode())))

    assert len(rows) == 1
    assert rows[0]["managerId"] == "500"
    assert rows[0]["questionId"] == "9001"
    assert rows[0]["questionText"] == "My manager supports me"
    assert rows[0]["respondentCount"] == "5"
    assert rows[0]["score"] == "8.0"
    assert rows[0]["category"] == "Engagement"
    assert rows[0]["driver"] == "Management Support"
    assert rows[0]["subDriver"] == "Coaching"
