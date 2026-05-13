"""
RTSP-driven classroom attendance.

Flow:
    1. start_attendance — form to launch a session
    2. background thread captures frames from RTSP for N seconds
    3. each frame is run through InsightFace + matched against active students
    4. detection counts are aggregated; 3+ detections → Present
    5. AttendanceRecord rows are written for every active student in the classroom
    6. session_status / session_status_api drive a live progress page
    7. attendance_dashboard / export_attendance_csv view + export results

Reuses face_app, log(), detect_faces_insightface, cosine_distance from views.py
to avoid loading the InsightFace model twice.
"""

import csv
import threading
import time
from datetime import datetime

import cv2
import numpy as np
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import AttendanceRecord, AttendanceSession, Student
# Reuse the InsightFace model + detection from views.py.
# Importing face_app here ensures the model loads on first import (same as before).
from .views import detect_faces_insightface, face_app  # noqa: F401


# ── Defaults shown in the start-session form ────────────────────────────────
DEFAULT_RTSP_URL  = "rtsp://192.168.1.50/stream1"
DEFAULT_DURATION  = 120
DEFAULT_INTERVAL  = 2
DEFAULT_MIN_FRAME = 3
DEFAULT_THRESHOLD = 0.75


# ============================================================================
#   START SESSION
# ============================================================================

def start_attendance(request):
    """Form view: collect RTSP URL + classroom + subject + timing, then launch."""
    if request.method == 'POST':
        rtsp_url     = request.POST.get('rtsp_url',     DEFAULT_RTSP_URL).strip()
        classroom    = request.POST.get('classroom',    '').strip()
        subject      = request.POST.get('subject',      '').strip()
        session_lbl  = request.POST.get('session_label','').strip()
        duration     = int(request.POST.get('duration_sec', DEFAULT_DURATION))
        interval     = int(request.POST.get('interval_sec', DEFAULT_INTERVAL))
        min_frames   = int(request.POST.get('min_frames',   DEFAULT_MIN_FRAME))
        match_thresh = float(request.POST.get('match_thresh', DEFAULT_THRESHOLD))

        if not session_lbl:
            session_lbl = datetime.now().strftime('%Y%m%d_%H%M%S')

        if not rtsp_url:
            messages.error(request, "RTSP URL is required.")
            return render(request, 'start_attendance.html', _form_defaults())

        # Make sure there's at least one student to match against
        active_count = Student.objects.filter(is_active=True).exclude(face_encoding=b'').count()
        if active_count == 0:
            messages.error(
                request,
                "No enrolled students with face encodings found. "
                "Enroll students first via 'Upload Faces For Recognition'."
            )
            return render(request, 'start_attendance.html', _form_defaults())

        session = AttendanceSession.objects.create(
            session_label = session_lbl,
            classroom     = classroom,
            subject       = subject,
            rtsp_url      = rtsp_url,
            duration_sec  = duration,
            interval_sec  = interval,
            min_frames    = min_frames,
            match_thresh  = match_thresh,
            status        = 'pending',
        )

        t = threading.Thread(
            target=run_rtsp_attendance_session,
            args=(session.pk,),
            daemon=True,
        )
        t.start()

        return redirect('session_status', pk=session.pk)

    return render(request, 'start_attendance.html', _form_defaults())


def _form_defaults():
    return {
        'rtsp_url':     DEFAULT_RTSP_URL,
        'duration_sec': DEFAULT_DURATION,
        'interval_sec': DEFAULT_INTERVAL,
        'min_frames':   DEFAULT_MIN_FRAME,
        'match_thresh': DEFAULT_THRESHOLD,
        'classrooms':   sorted(set(
            Student.objects.filter(is_active=True)
            .exclude(classroom='').values_list('classroom', flat=True)
        )),
    }


# ============================================================================
#   STATUS PAGE + JSON POLLER
# ============================================================================

def session_status(request, pk):
    session = get_object_or_404(AttendanceSession, pk=pk)
    return render(request, 'session_status.html', {'session': session})


def session_status_api(request, pk):
    session = get_object_or_404(AttendanceSession, pk=pk)
    log_lines = (session.log_output or '').splitlines()
    log_tail  = '\n'.join(log_lines[-80:])

    records = AttendanceRecord.objects.filter(session=session)
    present = records.filter(status='Present').count()
    total   = records.count()

    return JsonResponse({
        'status':        session.status,
        'log_tail':      log_tail,
        'present_count': present,
        'total_count':   total,
        'completed':     session.status in ('completed', 'failed'),
    })


# ============================================================================
#   DASHBOARD + EXPORT
# ============================================================================

def attendance_dashboard(request):
    sessions = AttendanceSession.objects.all().order_by('-started_at')

    classroom_filter = request.GET.get('classroom', '').strip()
    subject_filter   = request.GET.get('subject', '').strip()
    date_filter      = request.GET.get('date', '').strip()

    if classroom_filter:
        sessions = sessions.filter(classroom=classroom_filter)
    if subject_filter:
        sessions = sessions.filter(subject=subject_filter)
    if date_filter:
        sessions = sessions.filter(started_at__date=date_filter)

    sessions_with_summary = []
    for s in sessions[:50]:
        records = AttendanceRecord.objects.filter(session=s)
        sessions_with_summary.append({
            'session': s,
            'total':   records.count(),
            'present': records.filter(status='Present').count(),
        })

    classrooms = sorted(set(
        AttendanceSession.objects.exclude(classroom='').values_list('classroom', flat=True)
    ))
    subjects = sorted(set(
        AttendanceSession.objects.exclude(subject='').values_list('subject', flat=True)
    ))

    return render(request, 'attendance_dashboard.html', {
        'sessions':   sessions_with_summary,
        'classrooms': classrooms,
        'subjects':   subjects,
        'filters':    {
            'classroom': classroom_filter,
            'subject':   subject_filter,
            'date':      date_filter,
        },
    })


def session_detail(request, pk):
    session = get_object_or_404(AttendanceSession, pk=pk)
    records = (
        AttendanceRecord.objects
        .filter(session=session)
        .select_related('student')
        .order_by('-status', 'student__classroom', 'student__roll_no', 'student__name')
    )
    return render(request, 'session_detail.html', {
        'session': session,
        'records': records,
    })


def export_attendance_csv(request, pk):
    session = get_object_or_404(AttendanceSession, pk=pk)
    records = (
        AttendanceRecord.objects
        .filter(session=session)
        .select_related('student')
        .order_by('student__classroom', 'student__roll_no', 'student__name')
    )

    fname = f"attendance_{session.session_label}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{fname}"'

    w = csv.writer(response)
    w.writerow([
        'session', 'date', 'classroom', 'subject',
        'student_id', 'name', 'roll_no',
        'status', 'detections', 'best_score',
    ])
    for r in records:
        w.writerow([
            session.session_label,
            session.started_at.strftime('%Y-%m-%d %H:%M:%S'),
            session.classroom,
            session.subject,
            r.student.student_id,
            r.student.name,
            r.student.roll_no,
            r.status,
            r.detections,
            f"{r.best_score:.4f}",
        ])
    return response


# ============================================================================
#   BACKGROUND THREAD: RTSP → DETECT → MATCH → ATTENDANCE
# ============================================================================

_log_lock = threading.Lock()


def _append_log(session_id: int, line: str) -> None:
    """Append a timestamped line to the session's log_output (and stdout)."""
    ts = datetime.now().strftime('%H:%M:%S')
    full = f"[{ts}] {line}\n"
    with _log_lock:
        try:
            s = AttendanceSession.objects.get(pk=session_id)
            s.log_output = (s.log_output or '') + full
            s.save(update_fields=['log_output'])
        except AttendanceSession.DoesNotExist:
            pass
    print(full, end='')


def _load_known_embeddings(classroom: str | None):
    """
    Return (embeddings_matrix, student_pks) for matching.
    If classroom is non-empty, only enrol students of that classroom; else all active.
    """
    qs = Student.objects.filter(is_active=True).exclude(face_encoding=b'')
    if classroom:
        qs = qs.filter(classroom=classroom)

    embeddings, pks = [], []
    for s in qs:
        emb = np.frombuffer(bytes(s.face_encoding), dtype=np.float32)
        if emb.shape[0] != 512:
            continue
        embeddings.append(emb)
        pks.append(s.pk)

    if not embeddings:
        return None, []
    return np.stack(embeddings), pks


def _match_face_against_known(face_embedding, known_matrix, threshold):
    """
    Return (best_idx, distance) if a match is found, else (None, best_distance).
    Uses cosine distance against the pre-stacked known_matrix.
    """
    fe = face_embedding / (np.linalg.norm(face_embedding) + 1e-8)
    # known_matrix rows are already L2-normalised (we stored them that way)
    sims = known_matrix @ fe
    distances = 1.0 - sims
    best_idx = int(np.argmin(distances))
    best_dist = float(distances[best_idx])
    if best_dist <= threshold:
        return best_idx, best_dist
    return None, best_dist


def run_rtsp_attendance_session(session_id: int) -> None:
    """
    Long-running thread that drives one attendance session end-to-end.
    All progress is written into AttendanceSession.log_output for the UI to poll.
    """
    try:
        session = AttendanceSession.objects.get(pk=session_id)
        session.status = 'running'
        session.save(update_fields=['status'])

        _append_log(session_id, "=" * 50)
        _append_log(session_id, f"ATTENDANCE SESSION: {session.session_label}")
        _append_log(session_id, f"  classroom = {session.classroom or '(any active)'}")
        _append_log(session_id, f"  subject   = {session.subject or '(none)'}")
        _append_log(session_id, f"  duration  = {session.duration_sec}s, every {session.interval_sec}s")
        _append_log(session_id, f"  min_frames_for_present = {session.min_frames}")
        _append_log(session_id, f"  match_thresh           = {session.match_thresh}")
        _append_log(session_id, "=" * 50)

        # ── Load known students ─────────────────────────────────────────────
        known_matrix, known_pks = _load_known_embeddings(session.classroom or None)
        if known_matrix is None:
            raise RuntimeError(
                "No active students with valid 512-d embeddings to match against."
            )
        _append_log(session_id, f"Loaded {len(known_pks)} student embedding(s) for matching")

        # ── Connect to RTSP ─────────────────────────────────────────────────
        _append_log(session_id, f"Connecting to RTSP: {session.rtsp_url}")
        cap = cv2.VideoCapture(session.rtsp_url)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open RTSP stream: {session.rtsp_url}")
        _append_log(session_id, "Connected. Beginning capture …")

        # ── Capture + recognise loop ────────────────────────────────────────
        deadline      = time.time() + session.duration_sec
        frame_count   = 0
        det_counts    = {}        # student_pk → count
        best_scores   = {}        # student_pk → best similarity (1 - distance)
        last_capture  = 0.0

        while time.time() < deadline:
            now = time.time()
            if (now - last_capture) < session.interval_sec:
                # Drain the RTSP buffer between samples so we get a fresh frame next time
                cap.grab()
                time.sleep(0.05)
                continue

            ret, frame = cap.read()
            if not ret or frame is None:
                _append_log(session_id, "Frame read failed — reconnecting in 1s …")
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(session.rtsp_url)
                continue

            frame_count += 1
            last_capture = now
            elapsed = int(now - (deadline - session.duration_sec))
            _append_log(session_id,
                f"--- frame {frame_count} @ t={elapsed}s "
                f"({frame.shape[1]}x{frame.shape[0]}) ---")

            try:
                faces, processed, _scale = detect_faces_insightface(frame)
            except Exception as e:
                _append_log(session_id, f"  detection error: {e}")
                continue

            if not faces:
                _append_log(session_id, "  no faces detected")
                continue

            for i, face in enumerate(faces, 1):
                if face.det_score < 0.5:
                    continue
                if face.embedding is None:
                    continue

                idx, dist = _match_face_against_known(
                    face.embedding.astype(np.float32),
                    known_matrix,
                    session.match_thresh,
                )
                if idx is None:
                    _append_log(session_id, f"  face #{i}: UNKNOWN (dist={dist:.3f})")
                    continue

                pk = known_pks[idx]
                det_counts[pk] = det_counts.get(pk, 0) + 1
                sim = 1.0 - dist
                if sim > best_scores.get(pk, 0.0):
                    best_scores[pk] = sim

                # Look up name only for log line — small cost
                try:
                    name = Student.objects.values_list('name', flat=True).get(pk=pk)
                except Student.DoesNotExist:
                    name = f"pk={pk}"
                _append_log(session_id,
                    f"  face #{i}: MATCH '{name}' (dist={dist:.3f}, "
                    f"sim={sim:.3f}, count={det_counts[pk]})")

        cap.release()
        _append_log(session_id, f"Capture finished — {frame_count} frame(s) processed")

        # ── Apply 3-frame rule and write records ────────────────────────────
        # Roster: every active student in the same classroom (or all if classroom blank)
        roster_qs = Student.objects.filter(is_active=True)
        if session.classroom:
            roster_qs = roster_qs.filter(classroom=session.classroom)

        records_to_create = []
        for student in roster_qs:
            count = det_counts.get(student.pk, 0)
            status = 'Present' if count >= session.min_frames else 'Absent'
            records_to_create.append(AttendanceRecord(
                session    = session,
                student    = student,
                status     = status,
                detections = count,
                best_score = best_scores.get(student.pk, 0.0),
            ))

        AttendanceRecord.objects.bulk_create(records_to_create, ignore_conflicts=True)

        present = sum(1 for r in records_to_create if r.status == 'Present')
        total   = len(records_to_create)
        _append_log(session_id, f"Done — Present: {present}/{total}")

        session.status       = 'completed'
        session.completed_at = timezone.now()
        session.save(update_fields=['status', 'completed_at'])

    except Exception as exc:
        import traceback
        err = traceback.format_exc()
        _append_log(session_id, f"[ERROR] {err}")
        AttendanceSession.objects.filter(pk=session_id).update(status='failed')
