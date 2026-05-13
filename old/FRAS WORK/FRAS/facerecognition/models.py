from django.db import models


class Student(models.Model):
    name          = models.CharField(max_length=100)
    image1        = models.ImageField(upload_to='students/')
    image2        = models.ImageField(upload_to='students/')
    image3        = models.ImageField(upload_to='students/')
    image4        = models.ImageField(upload_to='students/')
    face_encoding = models.BinaryField()

    # New fields for attendance reporting. Blank-allowed so existing rows survive.
    student_id    = models.CharField(max_length=20, blank=True, default='')
    classroom     = models.CharField(max_length=50, blank=True, default='')
    roll_no       = models.CharField(max_length=20, blank=True, default='')
    is_active     = models.BooleanField(default=True)

    def __str__(self):
        if self.classroom and self.roll_no:
            return f"{self.name} ({self.classroom} #{self.roll_no})"
        return self.name


class AttendanceSession(models.Model):
    STATUS_CHOICES = [
        ('pending',   'Pending'),
        ('running',   'Running'),
        ('completed', 'Completed'),
        ('failed',    'Failed'),
    ]

    session_label = models.CharField(max_length=100)
    classroom     = models.CharField(max_length=50, blank=True, default='')
    subject       = models.CharField(max_length=100, blank=True, default='')
    rtsp_url      = models.CharField(max_length=500)
    duration_sec  = models.IntegerField(default=120)
    interval_sec  = models.IntegerField(default=2)
    min_frames    = models.IntegerField(default=3)
    match_thresh  = models.FloatField(default=0.75)
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    started_at    = models.DateTimeField(auto_now_add=True)
    completed_at  = models.DateTimeField(null=True, blank=True)
    log_output    = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.session_label} — {self.subject or 'no subject'} ({self.status})"


class AttendanceRecord(models.Model):
    STATUS_CHOICES = [('Present', 'Present'), ('Absent', 'Absent')]

    session    = models.ForeignKey(
        AttendanceSession, on_delete=models.CASCADE, related_name='records',
    )
    student    = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='attendance_records',
    )
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES)
    detections = models.IntegerField(default=0)
    best_score = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('session', 'student')
        ordering = ['student__classroom', 'student__roll_no', 'student__name']

    def __str__(self):
        return f"{self.session.session_label} | {self.student.name} — {self.status}"
