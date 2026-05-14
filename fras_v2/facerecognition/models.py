"""
FRAS v2 Data Models
- Student: registered students with face embeddings
- LiveSession: a single classroom streaming session (e.g. 9 AM - 1 PM)
- HourlyReport: one report per hour during the session
- StudentDetection: which students were detected in which report
- DailyAttendance: final present/absent verdict per student per day
"""

from django.db import models


class Student(models.Model):
    """Registered student. May have multiple face embeddings."""
    name = models.CharField(max_length=100)
    roll_number = models.CharField(max_length=50, unique=True)
    student_id = models.CharField(max_length=50, blank=True)
    classroom = models.CharField(max_length=50, blank=True, default='default')
    section = models.CharField(max_length=10, blank=True)
    parent_contact = models.CharField(max_length=20, blank=True)

    # Stored face embedding(s) — packed: N x 512 float32 bytes (so N embeddings)
    face_encoding = models.BinaryField(null=True, blank=True)
    n_embeddings = models.IntegerField(default=0)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['roll_number']

    def __str__(self):
        return f"{self.roll_number} - {self.name}"


class StudentPhoto(models.Model):
    """Each photo uploaded for a student (could be 1 or many)."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='student_photos/')
    embedding_extracted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class LiveSession(models.Model):
    """A single live attendance session — typically 1 day per classroom."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('stopped', 'Stopped'),
    ]

    SOURCE_CHOICES = [
        ('webcam', 'Local Webcam'),
        ('rtsp', 'RTSP CCTV Camera'),
    ]

    classroom = models.CharField(max_length=50, default='default')
    subject = models.CharField(max_length=100, blank=True)
    date = models.DateField(auto_now_add=True)

    source_type = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='webcam')
    rtsp_url = models.CharField(max_length=500, blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    log_output = models.TextField(blank=True)
    total_frames_processed = models.IntegerField(default=0)
    total_detections = models.IntegerField(default=0)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.classroom} - {self.date} ({self.status})"


class HourlyReport(models.Model):
    """A report for one hour of a live session."""
    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name='reports')
    report_number = models.IntegerField()  # 1, 2, 3, ...
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    frames_processed = models.IntegerField(default=0)
    total_face_detections = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['session', 'report_number']
        unique_together = [('session', 'report_number')]

    def __str__(self):
        return f"{self.session} - Report #{self.report_number}"


class StudentDetection(models.Model):
    """Per-report record: was student X present in this hour's report?"""
    report = models.ForeignKey(HourlyReport, on_delete=models.CASCADE, related_name='detections')
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    detection_count = models.IntegerField(default=0)  # how many frames they appeared in
    best_confidence = models.FloatField(default=0.0)
    was_present = models.BooleanField(default=False)

    class Meta:
        unique_together = [('report', 'student')]


class DailyAttendance(models.Model):
    """Final daily verdict per student. Computed at end of session."""
    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name='daily_attendance')
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    reports_present_in = models.IntegerField(default=0)
    total_reports = models.IntegerField(default=0)
    presence_percentage = models.FloatField(default=0.0)
    final_status = models.CharField(max_length=10, default='Absent')  # Present / Absent
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('session', 'student')]
        ordering = ['student__roll_number']

    def __str__(self):
        return f"{self.student} - {self.final_status} ({self.presence_percentage:.0f}%)"
