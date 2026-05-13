# FRAS — Old Code Setup (Windows)

This is the revived/extended `old/FRAS WORK/FRAS/` Django project. It now includes
RTSP-based attendance with Present/Absent recording.

## What's new (vs. the original old code)

- **Bug fix**: face encodings are now read as `float32` (was `float64`, which
  silently broke recognition for every enrolled student).
- **Student fields**: `student_id`, `classroom`, `roll_no`, `is_active`.
- **Attendance flow**: Start a session → connects to RTSP → samples frames →
  recognises students → applies 3-frame rule → writes Present/Absent records.
- **Live status page** with polling log; **dashboard** with filters; **CSV export**.

## First-time setup

1. **Create a venv** (use Python 3.12 if 3.14 has wheel issues):
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. **Install dependencies**:
   ```powershell
   pip install --upgrade pip
   pip install -r requirements_windows.txt
   ```

3. **Apply migrations** (creates the new attendance tables):
   ```powershell
   python manage.py migrate
   ```

4. **(Optional) Create an admin user** so you can browse data via `/admin/`:
   ```powershell
   python manage.py createsuperuser
   ```

5. **Run the dev server**:
   ```powershell
   python manage.py runserver
   ```

   First request triggers InsightFace model download (~280 MB to
   `~/.insightface/models/buffalo_l/`). Subsequent runs use the cache.

## Workflow

1. **Enroll students** — visit `/upload_images/`. Provide name, classroom,
   roll number, and 4 photos (front, left, right, plus one extra). The system
   averages the 4 face embeddings into one stored vector.

2. **Start an attendance session** — visit `/attendance/start/`:
   - **RTSP URL**: e.g. `rtsp://user:pass@192.168.1.50:554/stream1`
   - **Classroom**: must match the classroom used when enrolling students
   - **Subject** (optional)
   - Capture defaults: 120 s duration, sample every 2 s, 3 sightings = Present,
     match threshold = 0.75 (cosine distance — lower is stricter).

3. **Watch live progress** — automatic redirect to `/attendance/session/<id>/`
   shows the rolling log and Present count. The page polls every 2 s.

4. **View records** — `/attendance/` lists all sessions; click "View" for a
   per-student Present/Absent table; click "CSV" to download.

## Tuning notes

- **`match_thresh`** is cosine distance against the stored 512-d ArcFace
  embedding. Smaller = stricter. Range typically 0.5–0.9.
  - Old default: **0.75** (this code's default)
  - Aggressive (more matches, more false positives): 0.85
  - Conservative (fewer matches, fewer false positives): 0.6

- **`min_frames`** is how many sightings within the session count as Present.
  Increase to suppress flicker; decrease if students briefly enter/leave the frame.

- **`interval_sec`** of 2 s gives ~60 samples in 120 s. Reduce only if your CPU
  can keep up with detection on every sampled frame.

## Troubleshooting

**"No active students with valid 512-d embeddings to match against"**
You haven't enrolled anyone yet, or every enrolled student is `is_active=False`,
or every encoding came out malformed. Enroll at least one student via
`/upload_images/` and re-try.

**"Cannot open RTSP stream"**
- Test the URL with VLC first: Media → Open Network Stream
- Some cameras need credentials in the URL: `rtsp://user:pass@ip:554/path`
- TCP transport sometimes works when UDP fails — try the camera vendor's
  recommended path, e.g. `/h264Preview_01_main` for Reolink, `/Streaming/Channels/101`
  for Hikvision.

**"old 128-d embedding" warning**
Means a stored encoding isn't 512-d; that student needs re-enrollment.
Old data stored with the float64-read bug should now read correctly as float32
since the fix landed; if a specific student still warns, their encoding is
genuinely malformed.

**Webcam recognition matched no one before**
Confirmed bug: `np.frombuffer(... dtype=np.float64)` was reading 2048 bytes
of float32 as 256 float64 values, failing the `len == 512` check. Fixed in
`views.py`. Existing enrolled students should now match without re-enrollment.
