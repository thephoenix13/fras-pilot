from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),

    # Students
    path('upload-students/', views.upload_students, name='upload_students'),
    path('students/', views.students_list, name='students_list'),

    # Sessions
    path('start-session/', views.start_session, name='start_session'),
    path('sessions/', views.all_sessions, name='all_sessions'),
    path('session/<int:pk>/', views.session_status, name='session_status'),
    path('session/<int:pk>/status/', views.session_status_api, name='session_status_api'),
    path('session/<int:pk>/stop/', views.session_stop, name='session_stop'),
    path('session/<int:pk>/reports/', views.session_reports, name='session_reports'),
    path('session/<int:pk>/download/<int:report_number>/',
         views.download_hourly_report, name='download_hourly_report'),
    path('session/<int:pk>/download-daily/',
         views.download_daily_report, name='download_daily_report'),
    path('session/<int:pk>/download-all/',
         views.download_all_reports_zip, name='download_all_reports_zip'),
]
