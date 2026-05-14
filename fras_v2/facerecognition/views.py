"""
FRAS v2 Views

Routes:
  /                          → home menu
  /upload-students/          → CSV + photos upload
  /students/                 → list registered students
  /start-session/            → start a live attendance session
  /session/<pk>/             → live status page (auto-refreshing)
  /session/<pk>/status/      → JSON poll endpoint
  /session/<pk>/stop/        → stop a running session
  /session/<pk>/reports/     → see all hourly reports + daily attendance
  /session/<pk>/download/<n>/ → download Nth hourly report CSV
  /session/<pk>/download-daily/ → download daily attendance CSV
"""

import csv
import io
import os
import zipfile

import cv2
import numpy as np
from django.conf import settings
from django.contrib import messages
from django.core.files.storage import FileSystemStorage
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import (
    Student, StudentPhoto, LiveSession,
    HourlyReport, StudentDetection, DailyAttendance,
)
from .face_engine import extract_embedding_from_image_path, pack_embeddings
from .tasks import start_session_in_thread, stop_session, is_session_active


# ── Home ───────────────────────────────────────────────────────────────────

def home(request):
    return render(request, 'home.html', {
        'n_students': Student.objects.filter(is_active=True).count(),
        'n_sessions': LiveSession.objects.count(),
        'recent_sessions': LiveSession.objects.all()[:5],
    })


# ── Student upload (CSV + photos in zip) ──────────────────────────────────

def upload_students(request):
    """
    Two upload modes:
    1. CSV with one photo column (flexible: 1 or 4 photos)
    2. Individual student registration form
    """
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        photos_zip = request.FILES.get('photos_zip')

        if not csv_file:
            messages.error(request, "Please upload a CSV file.")
            return render(request, 'upload_students.html')

        # Save photos zip first (if provided) and extract to media/student_photos/
        photo_dir = os.path.join(settings.MEDIA_ROOT, 'student_photos')
        os.makedirs(photo_dir, exist_ok=True)

        if photos_zip:
            try:
                z = zipfile.ZipFile(photos_zip)
                for name in z.namelist():
                    # Skip dirs and hidden files
                    if name.endswith('/') or name.startswith('__MACOSX') or '/.DS_Store' in name:
                        continue
                    # Flatten — strip directories, keep just the filename
                    fname = os.path.basename(name)
                    if not fname:
                        continue
                    out_path = os.path.join(photo_dir, fname)
                    with z.open(name) as src, open(out_path, 'wb') as dst:
                        dst.write(src.read())
            except zipfile.BadZipFile:
                messages.error(request, "Photos zip file is invalid.")
                return render(request, 'upload_students.html')

        # Now parse the CSV
        try:
            csv_text = csv_file.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            csv_text = csv_file.read().decode('latin-1')

        reader = csv.DictReader(io.StringIO(csv_text))

        created = 0
        updated = 0
        failed = 0
        errors = []

        for row_idx, row in enumerate(reader, start=2):
            # Required: name, roll_number, at least 1 photo
            name = (row.get('name') or '').strip()
            roll = (row.get('roll_number') or '').strip()

            if not name or not roll:
                errors.append(f"Row {row_idx}: missing name or roll_number")
                failed += 1
                continue

            # Collect photo filenames (photo, photo1, photo2, photo3, photo4)
            photo_names = []
            for col in ['photo', 'photo1', 'photo2', 'photo3', 'photo4',
                        'image', 'image1', 'image2', 'image3', 'image4']:
                val = (row.get(col) or '').strip()
                if val and val not in photo_names:
                    photo_names.append(val)

            if not photo_names:
                errors.append(f"Row {row_idx} ({roll}): no photo filename(s)")
                failed += 1
                continue

            # Extract embeddings
            embeddings = []
            for pname in photo_names:
                ppath = os.path.join(photo_dir, pname)
                if not os.path.exists(ppath):
                    errors.append(f"Row {row_idx} ({roll}): photo not found → {pname}")
                    continue
                emb, score = extract_embedding_from_image_path(ppath)
                if emb is not None:
                    embeddings.append(emb)
                else:
                    errors.append(f"Row {row_idx} ({roll}): no face in {pname}")

            if not embeddings:
                failed += 1
                continue

            packed, n_emb = pack_embeddings(embeddings)

            # Create or update student
            student, was_created = Student.objects.update_or_create(
                roll_number=roll,
                defaults={
                    'name': name,
                    'student_id': (row.get('student_id') or '').strip(),
                    'classroom': (row.get('classroom') or 'default').strip(),
                    'section': (row.get('section') or '').strip(),
                    'parent_contact': (row.get('parent_contact') or '').strip(),
                    'face_encoding': packed,
                    'n_embeddings': n_emb,
                    'is_active': True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

            # Save photo records
            student.photos.all().delete()
            for pname in photo_names:
                ppath = os.path.join('student_photos', pname)
                if os.path.exists(os.path.join(settings.MEDIA_ROOT, ppath)):
                    StudentPhoto.objects.create(
                        student=student,
                        image=ppath,
                        embedding_extracted=True,
                    )

        if errors:
            messages.warning(request, f"Some rows had issues: {len(errors)} (see below).")
        messages.success(request, f"Enrolled: {created} new, {updated} updated, {failed} failed.")

        return render(request, 'upload_students.html', {
            'created': created, 'updated': updated, 'failed': failed,
            'errors': errors[:30],
        })

    return render(request, 'upload_students.html')


def students_list(request):
    students = Student.objects.filter(is_active=True).prefetch_related('photos')
    return render(request, 'students_list.html', {'students': students})


# ── Sessions ───────────────────────────────────────────────────────────────

def start_session(request):
    if request.method == 'POST':
        classroom = (request.POST.get('classroom') or 'default').strip()
        subject = (request.POST.get('subject') or '').strip()
        source_type = request.POST.get('source_type', 'webcam')
        rtsp_url = (request.POST.get('rtsp_url') or '').strip()

        if source_type == 'rtsp' and not rtsp_url:
            messages.error(request, "RTSP URL is required for CCTV source.")
            return render(request, 'start_session.html')

        if Student.objects.filter(is_active=True).count() == 0:
            messages.error(request, "No students enrolled yet. Upload student CSV first.")
            return redirect('upload_students')

        session = LiveSession.objects.create(
            classroom=classroom,
            subject=subject,
            source_type=source_type,
            rtsp_url=rtsp_url,
            status='pending',
        )

        start_session_in_thread(session.pk)
        return redirect('session_status', pk=session.pk)

    return render(request, 'start_session.html')


def session_status(request, pk):
    session = get_object_or_404(LiveSession, pk=pk)
    return render(request, 'session_status.html', {
        'session': session,
        'is_active': is_session_active(pk),
    })


def session_status_api(request, pk):
    """JSON poll endpoint used by the live page."""
    session = get_object_or_404(LiveSession, pk=pk)

    log_tail = '\n'.join((session.log_output or '').splitlines()[-30:])

    reports_data = []
    for r in session.reports.all().order_by('report_number'):
        present_count = StudentDetection.objects.filter(report=r, was_present=True).count()
        reports_data.append({
            'number': r.report_number,
            'period': f"{timezone.localtime(r.period_start).strftime('%H:%M')} - {timezone.localtime(r.period_end).strftime('%H:%M')}",
            'frames': r.frames_processed,
            'present': present_count,
        })

    return JsonResponse({
        'status': session.status,
        'log_tail': log_tail,
        'is_active': is_session_active(pk),
        'total_frames': session.total_frames_processed,
        'total_detections': session.total_detections,
        'reports': reports_data,
    })


def session_stop(request, pk):
    session = get_object_or_404(LiveSession, pk=pk)
    if is_session_active(pk):
        stop_session(pk)
        messages.info(request, "Stop signal sent. Finishing current frame …")
    return redirect('session_status', pk=pk)


def session_reports(request, pk):
    session = get_object_or_404(LiveSession, pk=pk)
    reports = session.reports.all().prefetch_related('detections__student')
    daily = session.daily_attendance.all().select_related('student')

    # Build a matrix: student -> [present/absent in each report]
    students = Student.objects.filter(is_active=True)
    matrix = []
    for student in students:
        row = {'student': student, 'cells': [], 'daily': None}
        for r in reports:
            det = StudentDetection.objects.filter(report=r, student=student).first()
            row['cells'].append({
                'present': det.was_present if det else False,
                'count': det.detection_count if det else 0,
                'confidence': det.best_confidence if det else 0,
            })
        row['daily'] = daily.filter(student=student).first()
        matrix.append(row)

    return render(request, 'session_reports.html', {
        'session': session,
        'reports': reports,
        'daily': daily,
        'matrix': matrix,
    })


def download_hourly_report(request, pk, report_number):
    session = get_object_or_404(LiveSession, pk=pk)
    report = get_object_or_404(HourlyReport, session=session, report_number=report_number)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="hourly_{session.classroom}_'
        f'{session.date}_report{report_number}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([
        'Roll Number', 'Name', 'Classroom', 'Status',
        'Detection Count', 'Best Confidence (%)',
        'Report Period Start', 'Report Period End',
    ])

    period_start = timezone.localtime(report.period_start).strftime('%Y-%m-%d %H:%M:%S')
    period_end = timezone.localtime(report.period_end).strftime('%Y-%m-%d %H:%M:%S')

    detections = StudentDetection.objects.filter(report=report).select_related('student').order_by('student__roll_number')
    for d in detections:
        writer.writerow([
            d.student.roll_number, d.student.name, d.student.classroom,
            'Present' if d.was_present else 'Absent',
            d.detection_count, f"{d.best_confidence:.1f}",
            period_start, period_end,
        ])
    return response


def download_daily_report(request, pk):
    session = get_object_or_404(LiveSession, pk=pk)
    daily = session.daily_attendance.all().select_related('student').order_by('student__roll_number')

    if not daily.exists():
        messages.error(request, "Daily attendance not yet computed (session must complete first).")
        return redirect('session_reports', pk=pk)

    threshold = settings.FRAS_CONFIG['attendance']['present_threshold_percent']

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="daily_attendance_{session.classroom}_{session.date}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([
        'Roll Number', 'Name', 'Classroom', 'Section',
        'Reports Present In', 'Total Reports', 'Presence %',
        'Final Status', 'Threshold %', 'Date',
    ])
    for d in daily:
        writer.writerow([
            d.student.roll_number, d.student.name, d.student.classroom, d.student.section,
            d.reports_present_in, d.total_reports,
            f"{d.presence_percentage:.1f}",
            d.final_status, threshold, session.date,
        ])
    return response


def download_all_reports_zip(request, pk):
    """Bundle ALL hourly reports + daily into one zip."""
    session = get_object_or_404(LiveSession, pk=pk)
    threshold = settings.FRAS_CONFIG['attendance']['present_threshold_percent']

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Hourly reports
        for r in session.reports.all().order_by('report_number'):
            csv_buf = io.StringIO()
            w = csv.writer(csv_buf)
            w.writerow(['Roll Number', 'Name', 'Status', 'Detection Count',
                       'Best Confidence (%)', 'Period Start', 'Period End'])
            period_start = timezone.localtime(r.period_start).strftime('%Y-%m-%d %H:%M:%S')
            period_end = timezone.localtime(r.period_end).strftime('%Y-%m-%d %H:%M:%S')
            dets = StudentDetection.objects.filter(report=r).select_related('student').order_by('student__roll_number')
            for d in dets:
                w.writerow([
                    d.student.roll_number, d.student.name,
                    'Present' if d.was_present else 'Absent',
                    d.detection_count, f"{d.best_confidence:.1f}",
                    period_start, period_end,
                ])
            zf.writestr(f"hourly_report_{r.report_number:02d}.csv", csv_buf.getvalue())

        # Daily attendance
        daily = session.daily_attendance.all().select_related('student').order_by('student__roll_number')
        if daily.exists():
            csv_buf = io.StringIO()
            w = csv.writer(csv_buf)
            w.writerow(['Roll Number', 'Name', 'Classroom', 'Reports Present In',
                       'Total Reports', 'Presence %', 'Final Status', 'Threshold %'])
            for d in daily:
                w.writerow([
                    d.student.roll_number, d.student.name, d.student.classroom,
                    d.reports_present_in, d.total_reports,
                    f"{d.presence_percentage:.1f}", d.final_status, threshold,
                ])
            zf.writestr("daily_attendance.csv", csv_buf.getvalue())

    buf.seek(0)
    response = HttpResponse(buf.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = (
        f'attachment; filename="reports_{session.classroom}_{session.date}.zip"'
    )
    return response


def all_sessions(request):
    """List all past sessions."""
    sessions = LiveSession.objects.all().order_by('-started_at')
    return render(request, 'all_sessions.html', {'sessions': sessions})
