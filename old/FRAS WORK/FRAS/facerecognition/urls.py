from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from . import views
from . import attendance_views as av

urlpatterns = [
    # Existing endpoints — unchanged
    path('',                   views.index,             name='index'),
    path('videofacerecog/',    views.videofacerecog,    name='videofacerecog'),
    path('upload_images/',     views.upload_images,     name='upload_images'),
    path('webcam_template/',   views.webcam_template,   name='webcam_template'),
    path('recognize_image/',   views.recognize_image,   name='recognize_image'),
    path('get_encodings/',     views.get_encodings,     name='get_encodings'),

    # New attendance endpoints
    path('attendance/start/',                  av.start_attendance,      name='start_attendance'),
    path('attendance/session/<int:pk>/',       av.session_status,        name='session_status'),
    path('attendance/session/<int:pk>/api/',   av.session_status_api,    name='session_status_api'),
    path('attendance/session/<int:pk>/detail/',av.session_detail,        name='session_detail'),
    path('attendance/session/<int:pk>/csv/',   av.export_attendance_csv, name='export_attendance_csv'),
    path('attendance/',                        av.attendance_dashboard,  name='attendance_dashboard'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
