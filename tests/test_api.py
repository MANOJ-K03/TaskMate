"""Automated tests. Every test uses its own temporary SQLite file, never taskmate.db."""
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import database as db
from app.main import app


@pytest.fixture()
def db_file(tmp_path, monkeypatch):
    path = tmp_path / "test_taskmate.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture()
def client(db_file):
    with TestClient(app) as c:  # entering the context runs init_db() on the temp file
        yield c


def make(client, **over):
    body = {"title": "Write report", "description": "Draft section 1", "category_id": 1,
            "priority": "High", "status": "Pending", "due_date": "2030-01-15"}
    body.update(over)
    r = client.post("/api/tasks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_task(client):
    t = make(client)
    assert t["id"] == 1 and t["title"] == "Write report" and t["status"] == "Pending"


def test_create_requires_title(client):
    assert client.post("/api/tasks", json={"title": "   "}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x", "priority": "Urgent"}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x", "due_date": "15-01-2030"}).status_code == 422


def test_retrieve_tasks(client):
    make(client, title="A"); make(client, title="B")
    assert [t["title"] for t in client.get("/api/tasks?sort=newest").json()] == ["B", "A"]
    assert client.get("/api/tasks/1").json()["title"] == "A"
    assert client.get("/api/tasks/999").status_code == 404


def test_edit_task_does_not_duplicate(client):
    make(client)
    r = client.put("/api/tasks/1", json={"title": "Write final report", "priority": "Low",
                                         "status": "In Progress", "category_id": 2})
    assert r.status_code == 200 and r.json()["title"] == "Write final report"
    assert r.json()["category"] == "Project"
    assert len(client.get("/api/tasks").json()) == 1
    assert client.put("/api/tasks/999", json={"title": "x"}).status_code == 404


def test_delete_task_keeps_history(client):
    make(client)
    assert client.delete("/api/tasks/1").status_code == 204
    assert client.get("/api/tasks/1").status_code == 404
    assert client.delete("/api/tasks/1").status_code == 404
    actions = [a["action"] for a in client.get("/api/activity").json()]
    assert "Task deleted" in actions and "Task created" in actions  # history survived the delete


def test_search_tasks(client):
    make(client, title="Database case study"); make(client, title="Buy groceries")
    make(client, title="100% done_check")
    assert [t["title"] for t in client.get("/api/tasks?search=case").json()] == ["Database case study"]
    assert len(client.get("/api/tasks?search=zzz").json()) == 0
    assert [t["title"] for t in client.get("/api/tasks?search=100%25").json()] == ["100% done_check"]
    assert len(client.get("/api/tasks?search=%25").json()) == 1  # % is literal, not a wildcard


def test_filter_and_sort(client):
    make(client, title="a", category_id=1, priority="High", status="Pending", due_date="2030-03-01")
    make(client, title="b", category_id=2, priority="Low", status="Completed", due_date="2030-01-01")
    make(client, title="c", category_id=2, priority="Low", status="Pending", due_date=None)
    titles = lambda q: [t["title"] for t in client.get("/api/tasks" + q).json()]
    assert titles("?category_id=2&sort=newest") == ["c", "b"]
    assert titles("?priority=High") == ["a"]
    assert titles("?status=Completed") == ["b"]
    assert titles("?priority=Low&status=Pending") == ["c"]
    assert titles("?sort=due_asc") == ["b", "a", "c"]   # no-date task last
    assert titles("?sort=due_desc") == ["a", "b", "c"]


def test_complete_and_reopen(client):
    make(client)
    assert client.patch("/api/tasks/1/complete").json()["status"] == "Completed"
    assert client.patch("/api/tasks/1/complete?completed=false").json()["status"] == "Pending"
    assert client.patch("/api/tasks/999/complete").status_code == 404
    actions = [a["action"] for a in client.get("/api/tasks/1/activity").json()]
    assert actions[:2] == ["Task reopened", "Task marked completed"]


def test_dashboard_statistics(client):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    make(client, status="Pending", due_date=yesterday)            # overdue
    make(client, status="In Progress", due_date="2099-01-01")
    make(client, status="Completed", due_date=yesterday)          # done, so not overdue
    make(client, status="Completed", due_date=None)
    s = client.get("/api/stats").json()
    assert s == {"total": 4, "pending": 1, "in_progress": 1, "completed": 2,
                 "overdue": 1, "completion_percent": 50.0}


def test_stats_empty(client):
    assert client.get("/api/stats").json()["completion_percent"] == 0.0


def test_join_returns_category_name(client):
    make(client, category_id=1); make(client, category_id=None)
    tasks = {t["id"]: t["category"] for t in client.get("/api/tasks").json()}
    assert tasks == {1: "Study", 2: None}


def test_categories(client):
    assert [c["name"] for c in client.get("/api/categories").json()] == ["Personal", "Project", "Study", "Work"]
    assert client.post("/api/categories", json={"name": "Health"}).status_code == 201
    assert client.post("/api/categories", json={"name": "Health"}).status_code == 409
    assert client.post("/api/categories", json={"name": " "}).status_code == 422


def test_activity_recorded(client):
    make(client)
    client.put("/api/tasks/1", json={"title": "Renamed", "priority": "High", "status": "Pending",
                                     "category_id": 1, "due_date": "2030-01-15", "description": "Draft section 1"})
    rows = client.get("/api/tasks/1/activity").json()
    assert [r["action"] for r in rows] == ["Task updated", "Task created"]
    assert "title" in rows[0]["details"]
    assert client.get("/api/tasks/999/activity").status_code == 404


def test_foreign_key_behaviour(client, db_file):
    # API: unknown category is rejected
    r = client.post("/api/tasks", json={"title": "x", "category_id": 999})
    assert r.status_code == 400
    assert client.get("/api/tasks").json() == []  # nothing half-saved (transaction rolled back)
    # Database level: a category that is in use cannot be deleted
    make(client, category_id=1)
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM categories WHERE id = 1")
    conn.close()


def test_check_constraints(db_file):
    db.init_db()
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tasks (title, priority, status, created_at, updated_at)"
                     " VALUES ('x', 'Urgent', 'Pending', 'now', 'now')")
    conn.close()


def test_insights(client):
    make(client)
    d = client.get("/api/insights").json()
    assert d["database"] == "test_taskmate.db"
    assert d["tables"] == ["categories", "task_activity", "tasks"]
    assert d["task_count"] == 1 and d["category_count"] == 4
    assert {"from": "tasks.category_id", "to": "categories.id", "on_delete": "NO ACTION"} in d["relationships"]
    assert d["by_status"] == {"Pending": 1}


def test_persistence_after_restart(db_file):
    with TestClient(app) as first:
        first.post("/api/tasks", json={"title": "Survive restart", "priority": "Low", "status": "Pending"})
    # the first "server" is now shut down; start a brand-new one on the same file
    with TestClient(app) as second:
        titles = [t["title"] for t in second.get("/api/tasks").json()]
    assert titles == ["Survive restart"]
