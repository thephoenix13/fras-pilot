import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('facerecognition', '0001_initial'),
    ]

    operations = [
        # ── Extend Student ──────────────────────────────────────────────────
        migrations.AddField(
            model_name='student',
            name='student_id',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='student',
            name='classroom',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
        migrations.AddField(
            model_name='student',
            name='roll_no',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='student',
            name='is_active',
            field=models.BooleanField(default=True),
        ),

        # ── AttendanceSession ───────────────────────────────────────────────
        migrations.CreateModel(
            name='AttendanceSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('session_label', models.CharField(max_length=100)),
                ('classroom', models.CharField(blank=True, default='', max_length=50)),
                ('subject', models.CharField(blank=True, default='', max_length=100)),
                ('rtsp_url', models.CharField(max_length=500)),
                ('duration_sec', models.IntegerField(default=120)),
                ('interval_sec', models.IntegerField(default=2)),
                ('min_frames', models.IntegerField(default=3)),
                ('match_thresh', models.FloatField(default=0.75)),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('running', 'Running'),
                             ('completed', 'Completed'), ('failed', 'Failed')],
                    default='pending', max_length=20,
                )),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('log_output', models.TextField(blank=True, default='')),
            ],
            options={
                'ordering': ['-started_at'],
            },
        ),

        # ── AttendanceRecord ────────────────────────────────────────────────
        migrations.CreateModel(
            name='AttendanceRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[('Present', 'Present'), ('Absent', 'Absent')],
                    max_length=10,
                )),
                ('detections', models.IntegerField(default=0)),
                ('best_score', models.FloatField(default=0.0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('session', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='records',
                    to='facerecognition.attendancesession',
                )),
                ('student', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='attendance_records',
                    to='facerecognition.student',
                )),
            ],
            options={
                'ordering': ['student__classroom', 'student__roll_no', 'student__name'],
                'unique_together': {('session', 'student')},
            },
        ),
    ]
