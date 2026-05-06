from django.contrib import admin
from .models import AttendanceSession, AttendanceRecord


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display  = ('session_label', 'subject', 'classroom', 'date', 'status', 'source')
    list_filter   = ('status', 'classroom', 'subject')
    search_fields = ('session_label', 'subject')
    readonly_fields = ('log_output',)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display  = ('session', 'student', 'status', 'detections', 'created_at')
    list_filter   = ('status', 'session__classroom', 'session__subject')
    search_fields = ('student__name', 'student__student_id')
