# FRAS v2 — Face Recognition Attendance System

Automated classroom attendance using face recognition. Captures live video from CCTV/webcam, identifies enrolled students, generates hourly reports, and computes daily attendance using a 75% presence rule.

## Features

- 📥 **Bulk student upload** via CSV + photos zip (supports 1 to 4 photos per student)
- 📹 **Live attendance** from CCTV (RTSP) or webcam
- ⏰ **Auto hourly reports** generated every 60 minutes during a session
- ✅ **Smart daily verdict** — student must appear in ≥75% of reports to be marked Present
- 💾 **Download** individual hourly reports + final daily attendance as CSV, or everything as a zip
- 🧠 **Multi-embedding recognition** — stores multiple face fingerprints per student for better accuracy
- 🎯 **InsightFace** (RetinaFace + ArcFace 512-d) for industry-grade face recognition
- 🧵 **Background threading** — UI stays responsive while live processing runs

## Quick Start

### 1. Setup

```bash
# Create and activate a virtual environment
python3 -m venv env
source env/bin/activate           # Mac/Linux
# OR
env\Scripts\activate              # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Initialize the database

```bash
python manage.py migrate
python manage.py createsuperuser   # optional, for admin access at /admin/
```

### 3. Run the server

```bash
python manage.py runserver
```

Open http://127.0.0.1:8000/ in your browser.

> **First run:** InsightFace will download ~300MB of model files. This happens once.

## Usage

### Step 1 — Enroll Students

1. Prepare a CSV file (see `sample_data/students_sample.csv` for format)
2. Required columns: `name`, `roll_number`, at least one of `photo`/`photo1`/`photo2`/`photo3`/`photo4`
3. Optional columns: `classroom`, `section`, `student_id`, `parent_contact`
4. Zip all referenced photo files into a single ZIP
5. Go to **Students → Upload Students**, upload both files

**For best recognition accuracy**, provide 2–4 photos per student covering different angles and conditions. If you'll be using CCTV later, include at least one photo at similar resolution/angle.

### Step 2 — Start a Session

1. Go to **New Session**
2. Enter classroom, subject
3. Choose source:
   - **Local Webcam** — for testing (uses your laptop camera)
   - **RTSP CCTV** — for production (paste your camera's RTSP URL)
4. Click **Start Session**

### Step 3 — Monitor Live

The session page auto-refreshes every 2.5 seconds showing:
- Frames processed
- Total face detections
- Hourly reports as they're generated
- Live log of detections (with student names + confidence)

### Step 4 — Stop & Download

When the school day ends, click **Stop Session**. The system will:
1. Flush the current partial hour as the last report
2. Compute the 75% rule across all hourly reports
3. Mark each student Present or Absent for the day

Then download:
- **Individual hourly reports** (one CSV per hour)
- **Daily attendance** (one CSV with the final verdict)
- **Everything as ZIP** (all reports bundled together)

## How the 75% Rule Works

Suppose you ran a session from 9 AM to 1 PM with 4 hourly reports generated.

| Student | 9-10 | 10-11 | 11-12 | 12-1 | Present in | % | Final |
|---|---|---|---|---|---|---|---|
| Sarvesh | ✅ | ✅ | ❌ | ✅ | 3/4 | 75% | **PRESENT** |
| Rahul | ✅ | ❌ | ❌ | ❌ | 1/4 | 25% | **ABSENT** |
| Priya | ✅ | ✅ | ✅ | ✅ | 4/4 | 100% | **PRESENT** |

To be "present in an hour", a student needs to be detected in at least 1 frame during that hour.

The 75% threshold is configurable in `fras_project/settings.py` under `FRAS_CONFIG['attendance']['present_threshold_percent']`.

## Configuration

Edit `fras_project/settings.py`, look for `FRAS_CONFIG`:

```python
FRAS_CONFIG = {
    'camera': {
        'source': 0,                          # webcam index for testing
        'frame_interval_seconds': 2,          # capture 1 frame every N seconds
    },
    'recognition': {
        'detection_confidence': 0.75,         # min face detection score
        'match_threshold': 0.55,              # cosine distance (lower = stricter)
        'min_face_size': 30,
    },
    'attendance': {
        'report_interval_minutes': 60,        # generate report every 60 min
        'present_threshold_percent': 75,      # ≥75% of reports = Present
        'min_detections_per_hour': 1,         # ≥1 detection in an hour = present that hour
    },
}
```

## Troubleshooting

**"No students enrolled yet"** → Upload your CSV first via **Students → Upload Students**.

**Photos in zip not found** → Photo filenames in CSV must match files in zip exactly (case-sensitive). HEIC files don't work — convert to JPG.

**Webcam doesn't open** → On Mac, grant camera permission to Terminal/your IDE in System Preferences → Security & Privacy → Camera.

**RTSP camera doesn't connect** → Test the URL first with `ffplay rtsp://your-url`. Most cameras need `rtsp://user:pass@ip:port/stream1`.

**Low recognition accuracy** → Re-enroll students with more varied photos. If using CCTV, include at least one CCTV-like photo (lower resolution, distance angle).

**Server eats memory** → Reduce `frame_interval_seconds` from 2 to 5 to process fewer frames.

## Project Structure

```
fras_v2/
├── manage.py
├── requirements.txt
├── README.md
├── fras_project/
│   ├── settings.py         ← Django + FRAS_CONFIG
│   ├── urls.py
│   ├── wsgi.py, asgi.py
├── facerecognition/
│   ├── models.py            ← Student, LiveSession, HourlyReport, etc.
│   ├── views.py             ← HTTP endpoints
│   ├── urls.py
│   ├── admin.py
│   ├── face_engine.py       ← InsightFace + matching logic
│   ├── tasks.py             ← background live-session worker
│   └── migrations/
├── templates/
│   ├── base.html
│   ├── home.html
│   ├── upload_students.html
│   ├── students_list.html
│   ├── start_session.html
│   ├── session_status.html
│   ├── session_reports.html
│   └── all_sessions.html
├── sample_data/
│   └── students_sample.csv
└── media/                   ← created at runtime (photos, frames)
```

## Tech Stack

- **Backend**: Django 5+, SQLite (default), Python 3.10+
- **Face engine**: InsightFace (buffalo_l) — RetinaFace detector + ArcFace 512-d embeddings
- **Compute**: ONNX Runtime CPU
- **Frontend**: Vanilla HTML/CSS/JS (no build step)

## License

Internal pilot — not for redistribution.
