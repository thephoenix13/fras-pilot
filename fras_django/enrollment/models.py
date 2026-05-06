from django.db import models


class Student(models.Model):
    student_id    = models.CharField(max_length=20, unique=True)
    name          = models.CharField(max_length=100)
    classroom     = models.CharField(max_length=50)
    roll_no       = models.CharField(max_length=20, blank=True)
    image1        = models.ImageField(upload_to='students/', null=True, blank=True)
    image2        = models.ImageField(upload_to='students/', null=True, blank=True)
    image3        = models.ImageField(upload_to='students/', null=True, blank=True)
    image4        = models.ImageField(upload_to='students/', null=True, blank=True)
    # 512-d ArcFace embedding stored as raw bytes (float32 → 2048 bytes)
    face_encoding = models.BinaryField(null=True, blank=True)
    enrolled_at   = models.DateTimeField(auto_now_add=True)
    is_active     = models.BooleanField(default=True)

    class Meta:
        ordering = ['classroom', 'roll_no', 'name']

    def __str__(self):
        return f"{self.student_id} — {self.name} ({self.classroom})"
