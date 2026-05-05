"""
Attendance logger: runs the full capture → recognize → log pipeline for one session.
Applies the 3-frame rule and writes final Present/Absent records to SQLite.

Usage:
    python src/attendance.py --session morning_01 --subject "Mathematics"
"""

import argparse
import os
import sqlite3
from datetime import date, datetime

import yaml

from capture import capture_session
from recognize import recognize_session


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def init_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  TEXT NOT NULL,
            name        TEXT,
            classroom   TEXT,
            subject     TEXT,
            session     TEXT,
            date        TEXT,
            status      TEXT,
            detections  INTEGER,
            created_at  TEXT
        )
    """)
    conn.commit()
    return conn


def load_roster(csv_path: str) -> dict[str, dict]:
    import pandas as pd
    df = pd.read_csv(csv_path)
    return {str(row["student_id"]): row.to_dict() for _, row in df.iterrows()}


def run_session(config: dict, session_label: str, subject: str, csv_path: str) -> None:
    classroom_id = config["camera"]["classroom_id"]
    min_frames = config["recognition"]["min_frames_for_present"]
    db_path = config["paths"]["attendance_db"]
    frames_dir = config["paths"]["frames_dir"]

    # Step 1: Capture frames from live camera
    print(f"\n[session] Starting capture for session: {session_label}")
    capture_session(config, session_label)

    # Step 2: Run recognition on captured frames
    session_frames_dir = os.path.join(frames_dir, classroom_id, session_label)
    print(f"\n[session] Running recognition on captured frames ...")
    frame_results = recognize_session(session_frames_dir, config)

    # Step 3: Aggregate detections per student
    detection_counts: dict[str, dict] = {}
    for detections in frame_results.values():
        for det in detections:
            sid = det["student_id"]
            if sid == "UNKNOWN":
                continue
            if sid not in detection_counts:
                detection_counts[sid] = {"name": det["name"], "count": 0}
            detection_counts[sid]["count"] += 1

    # Step 4: Load roster and apply 3-frame rule
    roster = load_roster(csv_path)
    conn = init_db(db_path)
    today = date.today().isoformat()
    now = datetime.now().isoformat()

    records = []
    for sid, student in roster.items():
        det_info = detection_counts.get(sid, {})
        det_count = det_info.get("count", 0)
        status = "Present" if det_count >= min_frames else "Absent"
        records.append((
            sid,
            student.get("name", ""),
            classroom_id,
            subject,
            session_label,
            today,
            status,
            det_count,
            now,
        ))

    conn.executemany("""
        INSERT INTO attendance (student_id, name, classroom, subject, session, date, status, detections, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    conn.close()

    # Step 5: Print summary
    present = sum(1 for r in records if r[6] == "Present")
    absent = len(records) - present
    print(f"\n[session] Done.")
    print(f"  Present: {present} / {len(records)}")
    print(f"  Absent:  {absent} / {len(records)}")
    print(f"  Records written to {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default=None, help="Session label (default: timestamp)")
    parser.add_argument("--subject", default="General", help="Subject name for this session")
    parser.add_argument("--csv", default="data/students_sample.csv")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    session_label = args.session or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_session(config, session_label, args.subject, args.csv)
