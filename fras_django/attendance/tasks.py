"""
Background task: runs the full RTSP capture → recognize → attendance log pipeline.
Executed in a Python thread so the web request returns immediately.

The AttendanceSession.log_output field is appended as progress messages arrive,
and the status page polls /attendance/session/<id>/status/ (JSON) every 3s.
"""

import os
import time
import threading
from datetime import datetime

import cv2
import numpy as np
from django.conf import settings
from django.utils import timezone

from core.embedding import get_embedding
from core.face_engine import get_face_app
from core.faiss_index import load_index, search
from core.detection import detect_faces, MIN_DET_SCORE
from core.deduplication import extract_unique_faces

_lock = threading.Lock()


def _log(session_id: int, msg: str):
    """Append a timestamped line to AttendanceSession.log_output."""
    from attendance.models import AttendanceSession
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {msg}\n"
    with _lock:
        AttendanceSession.objects.filter(pk=session_id).update(
            log_output=models_concat(session_id, line)
        )
    print(line, end='')


def models_concat(session_id: int, line: str) -> str:
    from attendance.models import AttendanceSession
    try:
        s = AttendanceSession.objects.get(pk=session_id)
        return (s.log_output or '') + line
    except AttendanceSession.DoesNotExist:
        return line


def _match_frame(app, index, id_map, frame_path: str, det_confidence: float, match_threshold: float) -> list[dict]:
    """Run recognition on one saved frame. Returns list of {student_pk, sim}."""
    img = cv2.imread(frame_path)
    if img is None:
        return []

    faces, processed, _ = detect_faces(app, img)
    results = []

    for face in faces:
        if face.det_score < det_confidence:
            continue
        if face.embedding is None:
            continue

        emb  = face.normed_embedding.astype(np.float32)
        sims, idxs = search(index, emb, k=1)
        sim  = float(sims[0])
        fidx = int(idxs[0])

        if (1 - sim) <= match_threshold:
            pk = id_map.get(fidx)
            if pk:
                results.append({'student_pk': pk, 'sim': sim})

    return results


def run_rtsp_session(session_id: int):
    """
    Main background thread function for RTSP-based attendance.
    """
    from attendance.models import AttendanceSession, AttendanceRecord
    from enrollment.models import Student

    try:
        session = AttendanceSession.objects.get(pk=session_id)
        session.status = 'running'
        session.save(update_fields=['status'])

        cfg            = settings.FRAS_CONFIG
        rtsp_url       = cfg['camera']['rtsp_url']
        interval       = cfg['camera']['frame_interval_seconds']
        duration       = cfg['camera']['capture_duration_seconds']
        det_confidence = cfg['recognition']['detection_confidence']
        match_threshold= cfg['recognition']['match_threshold']
        min_frames     = cfg['recognition']['min_frames_for_present']

        frames_dir = os.path.join(
            settings.FRAMES_DIR,
            session.classroom,
            session.session_label,
        )
        os.makedirs(frames_dir, exist_ok=True)
        session.frames_dir = frames_dir
        session.save(update_fields=['frames_dir'])

        # ── Step 1: Capture ───────────────────────────────────────────────
        _log(session_id, f"Connecting to RTSP stream …")
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot connect to: {rtsp_url}")

        _log(session_id, f"Connected. Capturing for {duration}s every {interval}s …")
        saved_paths = []
        start_time  = time.time()
        frame_count = 0

        while (time.time() - start_time) < duration:
            ret, frame = cap.read()
            if not ret:
                _log(session_id, "Frame read failed — retrying …")
                time.sleep(1)
                cap.release()
                cap = cv2.VideoCapture(rtsp_url)
                continue

            ts       = datetime.now().strftime('%H%M%S_%f')
            filename = f"frame_{frame_count:04d}_{ts}.jpg"
            path     = os.path.join(frames_dir, filename)
            cv2.imwrite(path, frame)
            saved_paths.append(path)
            frame_count += 1
            _log(session_id, f"Captured frame {frame_count}: {filename}")
            time.sleep(interval)

        cap.release()
        _log(session_id, f"Capture complete — {frame_count} frames saved.")

        # ── Step 2: Recognition ───────────────────────────────────────────
        _log(session_id, "Loading FAISS index …")
        index  = load_index(settings.FAISS_INDEX_PATH)
        if index is None:
            raise RuntimeError("No FAISS index found. Enroll students first.")

        import json
        map_path = os.path.join(os.path.dirname(settings.FAISS_INDEX_PATH), 'faiss_map.json')
        with open(map_path) as f:
            id_map = {int(k): int(v) for k, v in json.load(f).items()}

        app = get_face_app()
        detection_counts = {}  # student_pk → count

        _log(session_id, f"Running recognition on {len(saved_paths)} frames …")
        for fp in saved_paths:
            matches = _match_frame(app, index, id_map, fp, det_confidence, match_threshold)
            names   = []
            for m in matches:
                pk = m['student_pk']
                detection_counts[pk] = detection_counts.get(pk, 0) + 1
                names.append(str(pk))
            _log(session_id, f"  {os.path.basename(fp)}: {len(matches)} match(es) → {names}")

        # ── Step 3: Write attendance records ─────────────────────────────
        students = Student.objects.filter(classroom=session.classroom, is_active=True)
        records  = []
        for student in students:
            count  = detection_counts.get(student.pk, 0)
            status = 'Present' if count >= min_frames else 'Absent'
            records.append(AttendanceRecord(
                session    = session,
                student    = student,
                status     = status,
                detections = count,
            ))

        AttendanceRecord.objects.bulk_create(records, ignore_conflicts=True)

        present = sum(1 for r in records if r.status == 'Present')
        _log(session_id, f"Done. Present: {present}/{len(records)}")

        session.status       = 'completed'
        session.completed_at = timezone.now()
        session.save(update_fields=['status', 'completed_at'])

    except Exception as exc:
        import traceback
        from attendance.models import AttendanceSession
        err = traceback.format_exc()
        AttendanceSession.objects.filter(pk=session_id).update(
            status     = 'failed',
            log_output = models_concat(session_id, f"[ERROR] {err}\n"),
        )


def run_video_session(session_id: int, video_path: str):
    """
    Background thread for video-upload-based attendance.
    Uses deduplication logic from core/deduplication.py to extract unique faces,
    then matches each against the FAISS index.
    """
    from attendance.models import AttendanceSession, AttendanceRecord
    from enrollment.models import Student

    try:
        session = AttendanceSession.objects.get(pk=session_id)
        session.status = 'running'
        session.save(update_fields=['status'])

        cfg             = settings.FRAS_CONFIG
        det_confidence  = cfg['recognition']['detection_confidence']
        match_threshold = cfg['recognition']['match_threshold']
        min_frames      = cfg['recognition']['min_frames_for_present']

        output_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', f"session_{session_id}")

        _log(session_id, f"Extracting unique faces from video …")
        face_files = extract_unique_faces(video_path, output_dir)
        _log(session_id, f"Extracted {len(face_files)} unique face(s).")

        index = load_index(settings.FAISS_INDEX_PATH)
        if index is None:
            raise RuntimeError("No FAISS index found. Enroll students first.")

        import json
        map_path = os.path.join(os.path.dirname(settings.FAISS_INDEX_PATH), 'faiss_map.json')
        with open(map_path) as f:
            id_map = {int(k): int(v) for k, v in json.load(f).items()}

        app = get_face_app()
        detection_counts = {}

        for fname in face_files:
            fp  = os.path.join(output_dir, fname)
            img = cv2.imread(fp)
            if img is None:
                continue
            faces, _, _ = detect_faces(app, img)
            for face in faces:
                if face.det_score < det_confidence or face.embedding is None:
                    continue
                emb  = face.normed_embedding.astype(np.float32)
                sims, idxs = search(index, emb, k=1)
                sim  = float(sims[0])
                fidx = int(idxs[0])
                if (1 - sim) <= match_threshold:
                    pk = id_map.get(fidx)
                    if pk:
                        detection_counts[pk] = detection_counts.get(pk, 0) + 1

        students = Student.objects.filter(classroom=session.classroom, is_active=True)
        records  = []
        for student in students:
            count  = detection_counts.get(student.pk, 0)
            status = 'Present' if count >= min_frames else 'Absent'
            records.append(AttendanceRecord(
                session=session, student=student,
                status=status, detections=count,
            ))

        AttendanceRecord.objects.bulk_create(records, ignore_conflicts=True)
        present = sum(1 for r in records if r.status == 'Present')
        _log(session_id, f"Done. Present: {present}/{len(records)}")

        session.status       = 'completed'
        session.completed_at = timezone.now()
        session.save(update_fields=['status', 'completed_at'])

    except Exception as exc:
        import traceback
        from attendance.models import AttendanceSession
        err = traceback.format_exc()
        AttendanceSession.objects.filter(pk=session_id).update(
            status     = 'failed',
            log_output = models_concat(session_id, f"[ERROR] {err}\n"),
        )
