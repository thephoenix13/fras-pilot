"""
Web dashboard: attendance portal on the local network.
Run with: uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload
"""

import io
import os
import sqlite3
import sys

import pandas as pd
import yaml
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with open("config.yaml") as f:
    config = yaml.safe_load(f)

DB_PATH = config["paths"]["attendance_db"]

app = FastAPI(title="FRAS Dashboard")
templates = Jinja2Templates(directory="web/templates")


def query_db(sql: str, params: tuple = ()) -> list[dict]:
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    date: str = Query(default=None),
    classroom: str = Query(default=None),
    subject: str = Query(default=None),
):
    filters, params = [], []
    if date:
        filters.append("date = ?")
        params.append(date)
    if classroom:
        filters.append("classroom = ?")
        params.append(classroom)
    if subject:
        filters.append("subject = ?")
        params.append(subject)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    records = query_db(f"SELECT * FROM attendance {where} ORDER BY date DESC, session DESC", tuple(params))

    dates = query_db("SELECT DISTINCT date FROM attendance ORDER BY date DESC")
    classrooms = query_db("SELECT DISTINCT classroom FROM attendance")
    subjects = query_db("SELECT DISTINCT subject FROM attendance")

    return templates.TemplateResponse("index.html", {
        "request": request,
        "records": records,
        "dates": [r["date"] for r in dates],
        "classrooms": [r["classroom"] for r in classrooms],
        "subjects": [r["subject"] for r in subjects],
        "filters": {"date": date, "classroom": classroom, "subject": subject},
    })


@app.get("/export/csv")
def export_csv(
    date: str = Query(default=None),
    subject: str = Query(default=None),
):
    filters, params = [], []
    if date:
        filters.append("date = ?")
        params.append(date)
    if subject:
        filters.append("subject = ?")
        params.append(subject)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    records = query_db(f"SELECT student_id, name, classroom, subject, session, date, status, detections FROM attendance {where} ORDER BY date, student_id", tuple(params))

    df = pd.DataFrame(records)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    filename = f"attendance_{date or 'all'}_{subject or 'all'}.csv"
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/summary")
def summary(request: Request, response_class=HTMLResponse):
    rows = query_db("""
        SELECT date, subject, classroom,
               COUNT(*) as total,
               SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) as present
        FROM attendance
        GROUP BY date, subject, classroom
        ORDER BY date DESC
    """)
    for r in rows:
        r["pct"] = round(r["present"] / r["total"] * 100, 1) if r["total"] else 0

    return templates.TemplateResponse("summary.html", {"request": request, "rows": rows})
