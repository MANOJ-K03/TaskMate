"""TaskMate REST API (FastAPI + SQLite)."""
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from . import database as db

APP_DIR = Path(__file__).resolve().parent

Priority = Literal["Low", "Medium", "High"]
Status = Literal["Pending", "In Progress", "Completed"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="TaskMate", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


# ---------- input models ----------
class TaskIn(BaseModel):
    title: str
    description: Optional[str] = None
    category_id: Optional[int] = None
    priority: Priority = "Medium"
    status: Status = "Pending"
    due_date: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required")
        if len(v) > 120:
            raise ValueError("Title must be 120 characters or fewer")
        return v

    @field_validator("due_date")
    @classmethod
    def due_date_format(cls, v):
        if v in (None, ""):
            return None
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("Due date must be in YYYY-MM-DD format")
        return v


class CategoryIn(BaseModel):
    name: str
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Category name is required")
        return v


# ---------- helpers ----------
def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return date.today().isoformat()


# JOIN: category name comes from the categories table, not from the task row.
TASK_SELECT = """
SELECT t.id, t.title, t.description, t.category_id, c.name AS category,
       t.priority, t.status, t.due_date, t.created_at, t.updated_at,
       CASE WHEN t.status != 'Completed' AND t.due_date IS NOT NULL
                 AND t.due_date < ? THEN 1 ELSE 0 END AS overdue
FROM tasks t
LEFT JOIN categories c ON c.id = t.category_id
"""


def fetch_task(conn: sqlite3.Connection, task_id: int) -> dict:
    row = conn.execute(TASK_SELECT + " WHERE t.id = ?", (today(), task_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return dict(row)


def log_activity(conn, task_id, action, details=None):
    conn.execute(
        "INSERT INTO task_activity (task_id, action, details, created_at) VALUES (?, ?, ?, ?)",
        (task_id, action, details, now()),
    )


# ---------- tasks ----------
@app.get("/api/tasks")
def list_tasks(
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    priority: Optional[Priority] = None,
    status: Optional[Status] = None,
    sort: Literal["due_asc", "due_desc", "newest"] = "due_asc",
    conn: sqlite3.Connection = Depends(db.get_db),
):
    where, params = [], [today()]
    if search and search.strip():
        escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("t.title LIKE ? ESCAPE '\\'")
        params.append(f"%{escaped}%")
    if category_id is not None:
        where.append("t.category_id = ?")
        params.append(category_id)
    if priority:
        where.append("t.priority = ?")
        params.append(priority)
    if status:
        where.append("t.status = ?")
        params.append(status)
    order = {
        "due_asc": "t.due_date IS NULL, t.due_date ASC, t.id ASC",   # tasks without a date go last
        "due_desc": "t.due_date IS NULL, t.due_date DESC, t.id ASC",
        "newest": "t.id DESC",
    }[sort]
    sql = TASK_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + order
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    return fetch_task(conn, task_id)


@app.post("/api/tasks", status_code=201)
def create_task(body: TaskIn, conn: sqlite3.Connection = Depends(db.get_db)):
    stamp = now()
    try:
        with conn:  # one transaction: task row + activity row, or neither
            cur = conn.execute(
                "INSERT INTO tasks (title, description, category_id, priority, status, due_date,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (body.title, body.description, body.category_id, body.priority,
                 body.status, body.due_date, stamp, stamp),
            )
            log_activity(conn, cur.lastrowid, "Task created", f"Created '{body.title}'")
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Category does not exist")
    return fetch_task(conn, cur.lastrowid)


@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, body: TaskIn, conn: sqlite3.Connection = Depends(db.get_db)):
    old = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if old is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    new = body.model_dump()
    changed = [f for f in new if (old[f] or None) != (new[f] or None)]
    try:
        with conn:
            conn.execute(
                "UPDATE tasks SET title = ?, description = ?, category_id = ?, priority = ?,"
                " status = ?, due_date = ?, updated_at = ? WHERE id = ?",
                (body.title, body.description, body.category_id, body.priority,
                 body.status, body.due_date, now(), task_id),
            )
            log_activity(conn, task_id, "Task updated",
                         "Changed: " + ", ".join(changed) if changed else "No field changes")
            if "status" in changed and body.status == "Completed":
                log_activity(conn, task_id, "Task marked completed")
            elif "status" in changed and old["status"] == "Completed":
                log_activity(conn, task_id, "Task reopened", f"Status set to {body.status}")
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Category does not exist")
    return fetch_task(conn, task_id)


@app.patch("/api/tasks/{task_id}/complete")
def complete_task(task_id: int, completed: bool = True, conn: sqlite3.Connection = Depends(db.get_db)):
    """completed=true marks the task Completed; completed=false reopens it as Pending."""
    if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    new_status = "Completed" if completed else "Pending"
    with conn:
        conn.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                     (new_status, now(), task_id))
        log_activity(conn, task_id, "Task marked completed" if completed else "Task reopened")
    return fetch_task(conn, task_id)


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    with conn:  # history record and DELETE succeed or fail together
        row = conn.execute("SELECT id, title FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        log_activity(conn, task_id, "Task deleted", f"Deleted task #{row['id']}: '{row['title']}'")
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return Response(status_code=204)


@app.get("/api/tasks/{task_id}/activity")
def task_activity(task_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    fetch_task(conn, task_id)  # 404 if the task does not exist
    rows = conn.execute(
        "SELECT id, task_id, action, details, created_at FROM task_activity"
        " WHERE task_id = ? ORDER BY id DESC", (task_id,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/activity")
def recent_activity(limit: int = Query(15, ge=1, le=100), conn: sqlite3.Connection = Depends(db.get_db)):
    """Latest events across all tasks, including deleted ones."""
    rows = conn.execute(
        "SELECT id, task_id, action, details, created_at FROM task_activity"
        " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---------- categories ----------
@app.get("/api/categories")
def list_categories(conn: sqlite3.Connection = Depends(db.get_db)):
    rows = conn.execute("SELECT id, name, description FROM categories ORDER BY name").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/categories", status_code=201)
def create_category(body: CategoryIn, conn: sqlite3.Connection = Depends(db.get_db)):
    try:
        with conn:
            cur = conn.execute("INSERT INTO categories (name, description) VALUES (?, ?)",
                               (body.name, body.description))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="A category with this name already exists")
    return {"id": cur.lastrowid, "name": body.name, "description": body.description}


# ---------- statistics ----------
@app.get("/api/stats")
def stats(conn: sqlite3.Connection = Depends(db.get_db)):
    counts = {"Pending": 0, "In Progress": 0, "Completed": 0}
    for r in conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"):
        counts[r["status"]] = r["n"]
    overdue = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE status != 'Completed'"
        " AND due_date IS NOT NULL AND due_date < ?", (today(),)).fetchone()[0]
    total = sum(counts.values())
    return {
        "total": total,
        "pending": counts["Pending"],
        "in_progress": counts["In Progress"],
        "completed": counts["Completed"],
        "overdue": overdue,
        "completion_percent": round(counts["Completed"] * 100 / total, 1) if total else 0.0,
    }


# ---------- database insights ----------
INSIGHT_QUERIES = [
    ("Tasks with their category names (JOIN)",
     "SELECT t.id, t.title, c.name AS category\nFROM tasks t\nLEFT JOIN categories c ON c.id = t.category_id\nORDER BY t.id DESC LIMIT 5;",
     "Joins each task to its category through the foreign key, so the name is stored once."),
    ("Tasks per category (GROUP BY + COUNT)",
     "SELECT c.name, COUNT(t.id) AS tasks\nFROM categories c\nLEFT JOIN tasks t ON t.category_id = c.id\nGROUP BY c.id\nORDER BY tasks DESC;",
     "Counts tasks for every category, including categories that have none yet."),
    ("Tasks by priority and status (GROUP BY)",
     "SELECT priority, status, COUNT(*) AS tasks\nFROM tasks\nGROUP BY priority, status\nORDER BY priority, status;",
     "Groups rows on two columns and counts each combination."),
    ("Overdue tasks (WHERE + date comparison)",
     "SELECT id, title, due_date\nFROM tasks\nWHERE status != 'Completed'\n  AND due_date IS NOT NULL\n  AND due_date < date('now', 'localtime')\nORDER BY due_date;",
     "Finds unfinished tasks whose due date has passed."),
    ("Activity events by type (GROUP BY + COUNT)",
     "SELECT action, COUNT(*) AS events\nFROM task_activity\nGROUP BY action\nORDER BY events DESC;",
     "Summarises the history table by kind of event."),
]


@app.get("/api/insights")
def insights(conn: sqlite3.Connection = Depends(db.get_db)):
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    relationships = []
    for t in tables:
        for fk in conn.execute(f"PRAGMA foreign_key_list({t})"):  # t comes from sqlite_master, not user input
            relationships.append({"from": f"{t}.{fk['from']}", "to": f"{fk['table']}.{fk['to']}",
                                  "on_delete": fk["on_delete"]})
    def grouped(col):
        return {r[col]: r["n"] for r in conn.execute(f"SELECT {col}, COUNT(*) AS n FROM tasks GROUP BY {col}")}
    queries = []
    for title, sql, why in INSIGHT_QUERIES:
        cur = conn.execute(sql)
        queries.append({"title": title, "sql": sql, "explanation": why,
                        "rows": [dict(r) for r in cur.fetchall()]})
    return {
        "database": db.DB_PATH.name,
        "tables": tables,
        "relationships": relationships,
        "task_count": conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
        "category_count": conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0],
        "by_status": grouped("status"),
        "by_priority": grouped("priority"),
        "queries": queries,
    }


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(APP_DIR / "templates" / "index.html")
