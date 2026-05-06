import io
import os
import threading

import pandas as pd
from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Sum, Case, When, IntegerField
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import StartSessionForm
from .models import AttendanceRecord, AttendanceSession
from .tasks import run_rtsp_session, run_video_session


# ── Dashboard ────────────────────────────────────────────────────────────────

def dashboard(request):
    qs = AttendanceRecord.objects.select_related('session', 'student')

    date      = request.GET.get('date')
    classroom = request.GET.get('classroom')
    subject   = request.GET.get('subject')
    session   = request.GET.get('session')

    if date:
        qs = qs.filter(session__date=date)
    if classroom:
        qs = qs.filter(session__classroom=classroom)
    if subject:
        qs = qs.filter(session__subject=subject)
    if session:
        qs = qs.filter(session__session_label=session)

    # Filter options
    dates      = AttendanceSession.objects.values_list('date', flat=True).distinct().order_by('-date')
    classrooms = AttendanceSession.objects.values_list('classroom', flat=True).distinct()
    subjects   = AttendanceSession.objects.values_list('subject', flat=True).distinct()
    sessions   = AttendanceSession.objects.values_list('session_label', flat=True).distinct().order_by('-started_at')

    return render(request, 'attendance/dashboard.html', {
        'records':    qs.order_by('-session__date', '-session__started_at'),
        'dates':      dates,
        'classrooms': classrooms,
        'subjects':   subjects,
        'sessions':   sessions,
        'filters':    {'date': date, 'classroom': classroom, 'subject': subject, 'session': session},
    })


def summary(request):
    rows = (
        AttendanceSession.objects
        .filter(status='completed')
        .annotate(
            total   = Count('records'),
            present = Sum(Case(When(records__status='Present', then=1),
                               default=0, output_field=IntegerField())),
        )
        .order_by('-date')
        .values('date', 'subject', 'classroom', 'session_label', 'total', 'present')
    )
    for r in rows:
        r['pct'] = round(r['present'] / r['total'] * 100, 1) if r['total'] else 0

    return render(request, 'attendance/summary.html', {'rows': rows})


# ── Export ───────────────────────────────────────────────────────────────────

def export_csv(request):
    qs = AttendanceRecord.objects.select_related('session', 'student')

    date    = request.GET.get('date')
    subject = request.GET.get('subject')
    session = request.GET.get('session')

    if date:
        qs = qs.filter(session__date=date)
    if subject:
        qs = qs.filter(session__subject=subject)
    if session:
        qs = qs.filter(session__session_label=session)

    data = list(qs.values(
        'student__student_id', 'student__name', 'student__classroom',
        'session__subject', 'session__session_label', 'session__date',
        'status', 'detections',
    ))

    df = pd.DataFrame(data)
    if not df.empty:
        df.columns = ['student_id', 'name', 'classroom', 'subject', 'session', 'date', 'status', 'detections']

    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    fname = f"attendance_{date or 'all'}_{subject or 'all'}.csv"
    return HttpResponse(
        buf.getvalue(),
        content_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'},
    )


# ── Session management ───────────────────────────────────────────────────────

def start_session(request):
    if request.method == 'POST':
        form = StartSessionForm(request.POST, request.FILES)
        if form.is_valid():
            d = form.cleaned_data

            if AttendanceSession.objects.filter(session_label=d['session_label']).exists():
                messages.error(request, f"Session '{d['session_label']}' already exists.")
                return render(request, 'attendance/start_session.html', {'form': form})

            session = AttendanceSession.objects.create(
                session_label = d['session_label'],
                classroom     = d['classroom'],
                subject       = d['subject'],
                source        = d['source'],
                status        = 'pending',
            )

            if d['source'] == 'rtsp':
                t = threading.Thread(target=run_rtsp_session, args=(session.pk,), daemon=True)
                t.start()
            else:
                # Save uploaded video to media/uploads/
                video_file = d['video_file']
                upload_path = os.path.join(settings.MEDIA_ROOT, 'uploads', video_file.name)
                os.makedirs(os.path.dirname(upload_path), exist_ok=True)
                with open(upload_path, 'wb') as fh:
                    for chunk in video_file.chunks():
                        fh.write(chunk)
                t = threading.Thread(
                    target=run_video_session,
                    args=(session.pk, upload_path),
                    daemon=True,
                )
                t.start()

            return redirect('session_status', pk=session.pk)
    else:
        form = StartSessionForm()

    return render(request, 'attendance/start_session.html', {'form': form})


def session_status(request, pk):
    session = get_object_or_404(AttendanceSession, pk=pk)
    return render(request, 'attendance/session_running.html', {'session': session})


def session_status_api(request, pk):
    """JSON polling endpoint for the session status page."""
    session = get_object_or_404(AttendanceSession, pk=pk)
    log     = session.log_output or ''
    # Return last 50 lines to keep response small
    log_tail = '\n'.join(log.splitlines()[-50:])

    present = AttendanceRecord.objects.filter(session=session, status='Present').count()
    total   = AttendanceRecord.objects.filter(session=session).count()

    return JsonResponse({
        'status':        session.status,
        'log_tail':      log_tail,
        'present_count': present,
        'total_count':   total,
    })
