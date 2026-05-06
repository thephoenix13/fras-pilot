from django.contrib import admin
from .models import Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display  = ('student_id', 'name', 'classroom', 'roll_no', 'is_active', 'enrolled_at')
    list_filter   = ('classroom', 'is_active')
    search_fields = ('student_id', 'name', 'roll_no')
    ordering      = ('classroom', 'roll_no')
