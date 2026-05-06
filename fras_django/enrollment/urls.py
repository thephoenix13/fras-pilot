from django.urls import path
from . import views

urlpatterns = [
    path('',                     views.home,            name='home'),
    path('enroll/single/',       views.enroll_single,   name='enroll_single'),
    path('enroll/bulk/',         views.enroll_bulk,     name='enroll_bulk'),
    path('enroll/rebuild-index/',views.rebuild_index,   name='rebuild_index'),
    path('webcam/',              views.webcam,           name='webcam'),
    path('api/recognize/',       views.recognize_image,  name='recognize_image'),
]
