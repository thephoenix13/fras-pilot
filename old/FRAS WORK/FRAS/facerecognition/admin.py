from django.contrib import admin

from .models import AttendanceRecord, AttendanceSession, Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display  = ('name', 'student_id', 'classroom', 'roll_no', 'is_active')
    list_filter   = ('classroom', 'is_active')
    search_fields = ('name', 'student_id', 'roll_no')


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display  = ('session_label', 'classroom', 'subject', 'status', 'started_at')
    list_filter   = ('status', 'classroom', 'subject')
    search_fields = ('session_label',)
    readonly_fields = ('started_at', 'completed_at', 'log_output')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display  = ('session', 'student', 'status', 'detections', 'best_score')
    list_filter   = ('status', 'session__classroom')
    search_fields = ('student__name', 'student__student_id')
