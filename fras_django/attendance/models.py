from django.db import models


class AttendanceSession(models.Model):
    STATUS_CHOICES = [
        ('pending',   'Pending'),
        ('running',   'Running'),
        ('completed', 'Completed'),
        ('failed',    'Failed'),
    ]
    SOURCE_CHOICES = [
        ('rtsp',  'RTSP Camera'),
        ('video', 'Video Upload'),
    ]

    session_label = models.CharField(max_length=100, unique=True)
    classroom     = models.CharField(max_length=50)
    subject       = models.CharField(max_length=100)
    date          = models.DateField(auto_now_add=True)
    started_at    = models.DateTimeField(auto_now_add=True)
    completed_at  = models.DateTimeField(null=True, blank=True)
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    source        = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='rtsp')
    frames_dir    = models.CharField(max_length=500, blank=True)
    log_output    = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.session_label} — {self.subject} ({self.status})"


class AttendanceRecord(models.Model):
    STATUS_CHOICES = [('Present', 'Present'), ('Absent', 'Absent')]

    session    = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE,
                                   related_name='records')
    student    = models.ForeignKey('enrollment.Student', on_delete=models.CASCADE,
                                   related_name='attendance_records')
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES)
    detections = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('session', 'student')
        ordering        = ['student__roll_no', 'student__name']

    def __str__(self):
        return f"{self.session.session_label} | {self.student.name} — {self.status}"
