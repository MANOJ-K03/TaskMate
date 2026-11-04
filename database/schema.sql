-- TaskMate schema (SQLite). Foreign keys are switched on per connection in app/database.py.

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT,
    category_id INTEGER REFERENCES categories(id),   -- optional: NULL means "no category"
    priority    TEXT NOT NULL CHECK (priority IN ('Low', 'Medium', 'High')),
    status      TEXT NOT NULL CHECK (status IN ('Pending', 'In Progress', 'Completed')),
    due_date    TEXT,                                -- ISO date: YYYY-MM-DD
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- task_id is nullable with ON DELETE SET NULL so that history rows survive
-- after their task is deleted (see report, section 7).
CREATE TABLE IF NOT EXISTS task_activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    details     TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(category_id);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_activity_task  ON task_activity(task_id);

INSERT OR IGNORE INTO categories (name, description) VALUES
    ('Study',    'Classes, assignments and exam preparation'),
    ('Project',  'Project and lab work'),
    ('Personal', 'Personal errands and routines'),
    ('Work',     'Internships and job-related tasks');
