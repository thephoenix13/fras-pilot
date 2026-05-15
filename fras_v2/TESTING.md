# Testing fras_v2 on the school dev machine

A dry-run guide for evaluating fras_v2 alongside the live root pilot, without touching the production deployment at `C:\Users\lenovo\fras-pilot`.

## Goals

- Verify the install works on the school machine (Windows + CCTV environment)
- Confirm the enroll → live session → hourly report → daily attendance loop runs end-to-end
- Test RTSP capture against CLASSROOM-122 without disrupting the running root pilot

## Setup (one time)

Open PowerShell on the school machine.

```powershell
# New folder — DO NOT touch C:\Users\lenovo\fras-pilot
cd C:\Users\lenovo
git clone https://github.com/thephoenix13/fras-pilot.git fras-v2-test
cd fras-v2-test\fras_v2

# Fresh venv (separate from root's)
python -m venv env
.\env\Scripts\activate

pip install -r requirements.txt

python manage.py migrate
```

> **First run downloads ~300 MB** of InsightFace `buffalo_l` model files. Make sure the school machine has internet access. This happens once.

## Run the server

```powershell
python manage.py runserver 8001
```

Different port from root (which uses 8000). Open `http://127.0.0.1:8001/` in the browser.

## Test plan

### 1. Enroll a small test set first

Don't bulk-import all 65 students on the first run. Start with 3–5:

- Use `sample_data/students_sample.csv` as a template
- Either re-use a few real student photos, or shoot a quick test photo per person with the webcam
- Go to **Students → Upload Students**, upload the CSV + a zip of the photos
- Confirm they appear in `/students/`

### 2. Webcam session (end-to-end smoke test)

- Go to **New Session**
- Source: **Local Webcam**
- Classroom: `TEST-WEBCAM` (so it doesn't collide with CLASSROOM-122 data later)
- Click **Start Session**
- Sit in front of the laptop camera; the log should show `Frame N: 1 face(s) | YourName(roll) 9X%`
- Click **Stop Session** after a minute or two
- Check the reports page — you should see one partial-hour report and a daily attendance row

### 3. Speed up the hourly rollover for testing

Hourly reports take 60 minutes to trigger naturally. To verify the rollover logic without waiting:

1. Edit `fras_project/settings.py` line 88:
   ```python
   'report_interval_minutes': 2,   # was 60
   ```
2. Restart the server
3. Start a new webcam session, wait ~2 minutes
4. Watch the log — you should see `⏰ Hour 1 elapsed — generating report …`
5. **Revert to 60 before any real test**

### 4. RTSP session against CLASSROOM-122

Only after webcam works.

- Source: **RTSP CCTV Camera**
- Paste the CLASSROOM-122 RTSP URL (same one root uses)
- Classroom: `TEST-CCTV-122`
- Run it for 10–15 minutes during a quiet period
- Watch for the `Frame read failed — retrying` log line; the auto-reconnect logic should kick in if it happens

> ⚠️ **Don't run this while root has a live session active on the same stream.** Multiple decoders on one RTSP source usually works, but can occasionally fight for keyframes. Test outside school hours, or pause root's session first.

### 5. Verify the downloads

After stopping the session, on the **Session Reports** page:

- Download a single hourly CSV — confirm it has roll number, name, status, detection count
- Download the daily CSV — confirm presence % and Present/Absent verdict per student
- Download the "all reports" ZIP — confirm it contains both

## What to watch / common gotchas

| Symptom | Cause / fix |
|---|---|
| CPU pegged at 100% | Bump `frame_interval_seconds` from 2 to 5 in `settings.py` |
| "No students enrolled yet" | Upload CSV first; check at least one photo had a detectable face |
| `Photos in zip not found` | Photo filenames in CSV must match files in zip exactly (case-sensitive on extraction) |
| Webcam doesn't open | Webcam already in use by Zoom/Teams/etc; close other apps |
| RTSP doesn't connect | Test the URL with `ffplay rtsp://...` first |
| InsightFace download stalls | Need internet; ~300 MB; will resume on retry |

## Cleanup

When the test is done:

```powershell
# Stop the server (Ctrl+C)
deactivate
cd C:\Users\lenovo
rmdir /s fras-v2-test    # optional — remove the test install
```

Root pilot at `C:\Users\lenovo\fras-pilot` is untouched throughout.

## Decision criteria — promote v2?

Only consider moving v2 to production if all of these hold:

- [ ] Webcam session runs for >10 minutes without errors
- [ ] RTSP session against CLASSROOM-122 runs for >30 minutes without crashes
- [ ] Hourly rollover fires correctly (tested with shortened interval)
- [ ] Daily attendance CSV has the right Present/Absent split given a known test
- [ ] You're willing to re-enroll all 65 students into v2's schema (their embeddings in root's DB are not portable)

If all green, the migration plan would be: enroll all 65 fresh in v2, run v2 on port 8001 alongside root for a few days, then swap.
