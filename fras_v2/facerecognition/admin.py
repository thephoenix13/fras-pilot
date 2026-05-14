from django.contrib import admin
from .models import (
    Student, StudentPhoto, LiveSession,
    HourlyReport, StudentDetection, DailyAttendance,
)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['roll_number', 'name', 'classroom', 'section', 'n_embeddings', 'is_active']
    list_filter = ['classroom', 'section', 'is_active']
    search_fields = ['name', 'roll_number', 'student_id']


@admin.register(LiveSession)
class LiveSessionAdmin(admin.ModelAdmin):
    list_display = ['date', 'classroom', 'subject', 'status', 'source_type', 'started_at']
    list_filter = ['status', 'classroom', 'date']
    readonly_fields = ['log_output']


@admin.register(HourlyReport)
class HourlyReportAdmin(admin.ModelAdmin):
    list_display = ['session', 'report_number', 'period_start', 'period_end', 'frames_processed']


@admin.register(DailyAttendance)
class DailyAttendanceAdmin(admin.ModelAdmin):
    list_display = ['session', 'student', 'final_status', 'presence_percentage']
    list_filter = ['final_status', 'session__date']


admin.site.register(StudentPhoto)
admin.site.register(StudentDetection)
