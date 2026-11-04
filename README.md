# TaskMate: A Task Management Application Using SQLite

Python FastAPI backend, SQLite database, plain HTML/CSS/JavaScript frontend.

## Install (Windows, PowerShell or Command Prompt)

```
cd TaskMate
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Start

```
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 in your browser. The database file `taskmate.db` is created
automatically in the project folder on first start.

## Test

```
python -m pytest -v
```

Tests use a temporary database and never touch `taskmate.db`.

The case-study report is in `report/CASE_STUDY_REPORT.md`.
