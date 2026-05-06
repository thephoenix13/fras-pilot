"""
Re-runs recognition and attendance logging on already-captured frames.
Use this to test different thresholds without capturing new footage.

Usage:
    python src/rematch.py --frames data/frames/CLASSROOM-122/live_01 --session rematch_01 --subject "1st BCA"
"""

import argparse
import os
import sqlite3
from datetime import date, datetime

import pandas as pd
import yaml

from recognize import recognize_session


def load_config(config_path="config.yaml"):
    with open(config_path) as f:
        return yaml.safe_load(f)


def init_db(db_path):
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


def rematch(frames_dir, session_label, subject, csv_path, config):
    classroom_id = config["camera"]["classroom_id"]
    min_frames   = config["recognition"]["min_frames_for_present"]
    db_path      = config["paths"]["attendance_db"]
    threshold    = config["recognition"]["match_threshold"]

    print(f"\n[rematch] Frames : {frames_dir}")
    print(f"[rematch] Session: {session_label}  Subject: {subject}")
    print(f"[rematch] Threshold: {threshold} (accepts similarity > {round(1 - threshold, 2)})")
    print(f"[rematch] Min frames for Present: {min_frames}\n")

    # Run recognition on existing frames
    frame_results = recognize_session(frames_dir, config)

    # Aggregate detections per student
    detection_counts = {}
    for detections in frame_results.values():
        for det in detections:
            sid = det["student_id"]
            if sid == "UNKNOWN":
                continue
            if sid not in detection_counts:
                detection_counts[sid] = {"name": det["name"], "count": 0}
            detection_counts[sid]["count"] += 1

    # Load roster and apply min-frames rule
    df = pd.read_csv(csv_path)
    df["student_id"] = df["student_id"].astype(str).str.strip()
    roster = {row["student_id"]: row.to_dict() for _, row in df.iterrows()}

    conn = init_db(db_path)
    today = date.today().isoformat()
    now   = datetime.now().isoformat()

    records = []
    for sid, student in roster.items():
        det_info  = detection_counts.get(sid, {})
        det_count = det_info.get("count", 0)
        status    = "Present" if det_count >= min_frames else "Absent"
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

    present = sum(1 for r in records if r[6] == "Present")
    absent  = len(records) - present

    print(f"\n[rematch] Done.")
    print(f"  Present : {present} / {len(records)}")
    print(f"  Absent  : {absent}  / {len(records)}")
    print(f"  Records written to {db_path}")

    if detection_counts:
        print(f"\n  Students detected (top matches):")
        for sid, info in sorted(detection_counts.items(), key=lambda x: -x[1]["count"]):
            print(f"    {sid} — {info['name']} ({info['count']} frame(s))")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames",  required=True, help="Path to existing frames folder")
    parser.add_argument("--session", default=None,  help="Session label for DB record (default: timestamp)")
    parser.add_argument("--subject", default="General")
    parser.add_argument("--csv",     default="data/students.csv")
    parser.add_argument("--config",  default="config.yaml")
    args = parser.parse_args()

    config        = load_config(args.config)
    session_label = args.session or datetime.now().strftime("%Y%m%d_%H%M%S")
    rematch(args.frames, session_label, args.subject, args.csv, config)
