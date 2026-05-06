from django.urls import path
from . import views

urlpatterns = [
    path('',                         views.dashboard,          name='dashboard'),
    path('summary/',                 views.summary,            name='summary'),
    path('export/csv/',              views.export_csv,         name='export_csv'),
    path('start/',                   views.start_session,      name='start_session'),
    path('session/<int:pk>/',        views.session_status,     name='session_status'),
    path('session/<int:pk>/status/', views.session_status_api, name='session_status_api'),
]
