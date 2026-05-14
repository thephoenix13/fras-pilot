"""
Live attendance background thread.

Runs in a daemon thread when a session starts. Loop:
  1. Open camera (webcam index 0 or RTSP URL)
  2. Every N seconds: grab a frame, detect faces, match against student DB
  3. Accumulate detection counts per student per hour
  4. Every 60 minutes: snapshot accumulated data → create HourlyReport rows
  5. Continue until stop signal or duration reached
  6. On stop: compute DailyAttendance based on 75% rule
"""

import os
import time
import threading
from datetime import datetime, timedelta
from collections import defaultdict

import cv2
import numpy as np

from django.conf import settings
from django.utils import timezone

# Thread-safe stop signal storage
_active_sessions = {}  # session_pk -> threading.Event (set to stop)
_active_sessions_lock = threading.Lock()


# ── Logging ───────────────────────────────────────────────────────────────

def _append_log(session_pk, msg):
    from .models import LiveSession
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {msg}\n"
    try:
        s = LiveSession.objects.get(pk=session_pk)
        s.log_output = (s.log_output or '') + line
        # Keep log size manageable
        if len(s.log_output) > 100_000:
            s.log_output = s.log_output[-80_000:]
        s.save(update_fields=['log_output'])
    except Exception as e:
        pass
    print(line, end='')


# ── Stop signal API ────────────────────────────────────────────────────────

def stop_session(session_pk):
    with _active_sessions_lock:
        ev = _active_sessions.get(session_pk)
    if ev:
        ev.set()


def is_session_active(session_pk):
    with _active_sessions_lock:
        return session_pk in _active_sessions


# ── Helpers ────────────────────────────────────────────────────────────────

def _open_camera(source_type, rtsp_url):
    """Open webcam (0) or RTSP URL. Returns cv2.VideoCapture or None."""
    if source_type == 'rtsp':
        cap = cv2.VideoCapture(rtsp_url)
    else:
        cap = cv2.VideoCapture(0)  # default webcam
    if not cap.isOpened():
        return None
    return cap


def _flush_hour_to_reports(session, report_number, period_start, period_end,
                          hour_counts, hour_best_confidence, hour_frames, hour_detections,
                          all_students):
    """
    Create HourlyReport + StudentDetection rows for the just-finished hour.
    `hour_counts`: dict[student_pk] -> int (detections this hour)
    `all_students`: list of (pk, name, roll, embs)
    """
    from .models import HourlyReport, StudentDetection, Student

    report = HourlyReport.objects.create(
        session=session,
        report_number=report_number,
        period_start=period_start,
        period_end=period_end,
        frames_processed=hour_frames,
        total_face_detections=hour_detections,
    )

    min_detections = settings.FRAS_CONFIG['attendance']['min_detections_per_hour']

    # Create a StudentDetection row for EVERY student (present or not)
    detections_to_create = []
    for pk, name, roll, _embs in all_students:
        count = hour_counts.get(pk, 0)
        was_present = count >= min_detections
        detections_to_create.append(StudentDetection(
            report=report,
            student_id=pk,
            detection_count=count,
            best_confidence=hour_best_confidence.get(pk, 0.0),
            was_present=was_present,
        ))

    StudentDetection.objects.bulk_create(detections_to_create)
    return report


def _compute_daily_attendance(session):
    """
    After session ends, compute DailyAttendance per student.
    Rule: student must be present in >= 75% of reports.
    """
    from .models import HourlyReport, StudentDetection, DailyAttendance, Student

    reports = HourlyReport.objects.filter(session=session)
    total_reports = reports.count()
    if total_reports == 0:
        return 0

    threshold_pct = settings.FRAS_CONFIG['attendance']['present_threshold_percent']

    # Count how many reports each student was present in
    presence = defaultdict(int)
    for report in reports:
        for det in StudentDetection.objects.filter(report=report, was_present=True):
            presence[det.student_id] += 1

    DailyAttendance.objects.filter(session=session).delete()

    daily_records = []
    students = Student.objects.filter(is_active=True)
    for student in students:
        present_in = presence.get(student.pk, 0)
        pct = (present_in / total_reports * 100) if total_reports else 0
        status = 'Present' if pct >= threshold_pct else 'Absent'
        daily_records.append(DailyAttendance(
            session=session,
            student=student,
            reports_present_in=present_in,
            total_reports=total_reports,
            presence_percentage=pct,
            final_status=status,
        ))

    DailyAttendance.objects.bulk_create(daily_records)
    return len(daily_records)


# ── Main worker thread ─────────────────────────────────────────────────────

def run_live_session(session_pk):
    """
    The big background loop. Should be called in a daemon thread.
    """
    from .models import LiveSession, Student
    from .face_engine import detect_faces, identify, load_all_students

    stop_event = threading.Event()
    with _active_sessions_lock:
        _active_sessions[session_pk] = stop_event

    try:
        session = LiveSession.objects.get(pk=session_pk)
        session.status = 'running'
        session.save(update_fields=['status'])

        cfg = settings.FRAS_CONFIG
        interval = cfg['camera']['frame_interval_seconds']
        report_interval_min = cfg['attendance']['report_interval_minutes']
        det_conf = cfg['recognition']['detection_confidence']

        _append_log(session_pk, f"Starting session — source={session.source_type}, classroom={session.classroom}")
        _append_log(session_pk, f"Frame interval: {interval}s | Report every: {report_interval_min} min")

        # Load student DB into memory once
        student_db = load_all_students()
        _append_log(session_pk, f"Loaded {len(student_db)} student(s) for matching")

        if not student_db:
            _append_log(session_pk, "ERROR: No students enrolled. Stopping.")
            session.status = 'failed'
            session.save(update_fields=['status'])
            return

        # Open the camera
        cap = _open_camera(session.source_type, session.rtsp_url)
        if cap is None:
            src = session.rtsp_url if session.source_type == 'rtsp' else 'webcam (index 0)'
            _append_log(session_pk, f"ERROR: Could not open camera: {src}")
            session.status = 'failed'
            session.save(update_fields=['status'])
            return

        _append_log(session_pk, "Camera opened. Live processing started.")

        # Hourly accumulator state
        report_number = 1
        hour_start = timezone.now()
        next_report_at = hour_start + timedelta(minutes=report_interval_min)
        hour_counts = defaultdict(int)
        hour_best_confidence = defaultdict(float)
        hour_frames = 0
        hour_detections = 0
        total_frames = 0
        total_dets = 0

        while not stop_event.is_set():
            # 1) Grab a frame
            ret, frame = cap.read()
            if not ret:
                _append_log(session_pk, "Frame read failed — retrying in 2s")
                time.sleep(2)
                # Reconnect for RTSP
                if session.source_type == 'rtsp':
                    cap.release()
                    cap = _open_camera('rtsp', session.rtsp_url)
                    if cap is None:
                        _append_log(session_pk, "Reconnect failed. Stopping.")
                        break
                continue

            hour_frames += 1
            total_frames += 1

            # 2) Detect + identify
            faces, processed, scale = detect_faces(frame)
            n_this_frame = 0
            matches_this_frame = []

            for face in faces:
                if face.det_score < det_conf:
                    continue
                if face.embedding is None:
                    continue
                hour_detections += 1
                total_dets += 1
                n_this_frame += 1

                pk, name, roll, conf = identify(face.embedding, student_db)
                if pk is not None:
                    hour_counts[pk] += 1
                    if conf > hour_best_confidence[pk]:
                        hour_best_confidence[pk] = conf
                    matches_this_frame.append(f"{name}({roll}) {conf}%")

            if n_this_frame > 0:
                matches_str = ", ".join(matches_this_frame) if matches_this_frame else "(no matches)"
                _append_log(session_pk, f"Frame {total_frames}: {n_this_frame} face(s) | {matches_str}")

            # 3) Check if hourly report is due
            now = timezone.now()
            if now >= next_report_at:
                _append_log(session_pk, f"⏰ Hour {report_number} elapsed — generating report …")
                _flush_hour_to_reports(
                    session, report_number, hour_start, now,
                    dict(hour_counts), dict(hour_best_confidence),
                    hour_frames, hour_detections, student_db,
                )
                _append_log(session_pk, f"   Report #{report_number} saved. "
                                       f"{hour_frames} frames, {hour_detections} detections.")
                # Reset for next hour
                report_number += 1
                hour_start = now
                next_report_at = hour_start + timedelta(minutes=report_interval_min)
                hour_counts = defaultdict(int)
                hour_best_confidence = defaultdict(float)
                hour_frames = 0
                hour_detections = 0

            # 4) Sleep before next frame
            time.sleep(interval)

        # Loop exited — clean up
        cap.release()

        # Flush any partial hour as final report
        if hour_frames > 0:
            _append_log(session_pk, f"Flushing final partial report #{report_number}")
            _flush_hour_to_reports(
                session, report_number, hour_start, timezone.now(),
                dict(hour_counts), dict(hour_best_confidence),
                hour_frames, hour_detections, student_db,
            )

        # Compute daily attendance with 75% rule
        n_attendance = _compute_daily_attendance(session)
        _append_log(session_pk, f"✅ Computed daily attendance for {n_attendance} students.")

        session.status = 'completed' if not stop_event.is_set() else 'stopped'
        session.completed_at = timezone.now()
        session.total_frames_processed = total_frames
        session.total_detections = total_dets
        session.save(update_fields=['status', 'completed_at', 'total_frames_processed', 'total_detections'])
        _append_log(session_pk, f"Session ended. Status: {session.status.upper()}")

    except Exception:
        import traceback
        err = traceback.format_exc()
        _append_log(session_pk, f"❌ EXCEPTION:\n{err}")
        try:
            session = LiveSession.objects.get(pk=session_pk)
            session.status = 'failed'
            session.completed_at = timezone.now()
            session.save(update_fields=['status', 'completed_at'])
        except Exception:
            pass

    finally:
        with _active_sessions_lock:
            _active_sessions.pop(session_pk, None)


def start_session_in_thread(session_pk):
    """Start the live session worker in a daemon thread. Returns immediately."""
    t = threading.Thread(target=run_live_session, args=(session_pk,), daemon=True)
    t.start()
    return t
