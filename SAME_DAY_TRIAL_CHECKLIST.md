# FRAS — Same-Day Trial Checklist
**Perfect Skills | Confidential**  
A compressed end-to-end pilot — setup, enrollment, live session, and dashboard — all in one visit.

---

## PRE-VISIT PREP (2–3 days before)
*Done by Pratik in Pune. The trial only works if this is complete before you travel.*

### From the client — collect in advance
- [ ] **Student photos** for the pilot class (20–40 students minimum)
  - 3–4 photos per student ideally; ID card photo acceptable as the main photo
  - Name files as: `STU001_1.jpg`, `STU001_2.jpg` etc.
- [ ] **Student metadata CSV** — columns: `student_id, name, class, roll_no`
- [ ] **Camera RTSP URL** — have the client IT confirm this before you travel
  - Looks like: `rtsp://192.168.1.50/stream1`
  - Test it from your machine if possible via VLC: Media → Open Network Stream
- [ ] **Server specs confirmed** — OS (Windows 10/11 or Ubuntu), RAM (min 16 GB), GPU if any
- [ ] **Tech setup confirmed** — Python installed, internet available on day of visit (see Tech Setup Document)

### On your machine — do before travelling
- [ ] Run enrollment pipeline on the student photos:
  ```bash
  python src/enroll.py --csv data/students_sample.csv --photos data/photos
  ```
- [ ] Verify FAISS index was built: `db/faiss.index` and `db/students.json` exist
- [ ] Pre-download the InsightFace `buffalo_l` model (it auto-downloads on first run — do this on your machine so you have it):
  ```bash
  python -c "from insightface.app import FaceAnalysis; app = FaceAnalysis(name='buffalo_l'); app.prepare(ctx_id=-1)"
  ```
  Model files land in `~/.insightface/models/buffalo_l/` — copy this folder to your USB drive
- [ ] Copy to USB drive or push to private Git repo:
  - Entire `fras-pilot/` project folder
  - `~/.insightface/models/buffalo_l/` model folder

### What to bring on-site
- [ ] Laptop (with the codebase)
- [ ] USB drive with: project code, pre-built `db/` folder, `buffalo_l` model files
- [ ] Power bank / charger
- [ ] HDMI cable (for dashboard demo on a screen if needed)

---

## ON-SITE TIMELINE (~4–5 hours)

### Hour 1 — Setup (Remote access + environment)
- [ ] Connect to server via TeamViewer (resource should have this ready — see Day 1 checklist)
- [ ] Copy project from USB to server: `C:\fras-pilot\`
- [ ] Copy `buffalo_l` model to: `C:\Users\<username>\.insightface\models\buffalo_l\`
- [ ] Open Command Prompt, navigate to project:
  ```bash
  cd C:\fras-pilot
  pip install -r requirements.txt
  ```
- [ ] Update `config.yaml` with the actual RTSP URL and classroom ID

### Hour 2 — Camera & dry run
- [ ] Test camera connectivity:
  ```bash
  python src/test_camera.py
  ```
- [ ] Open `data/camera_test.jpg` — visually verify faces are clear and the frame covers the full classroom
- [ ] If image is poor: check camera placement (see placement guide in Tech Document)
- [ ] Run a dry-run capture:
  ```bash
  python src/capture.py --session dry_run
  ```
- [ ] Run recognition on dry-run frames:
  ```bash
  python src/recognize.py --frames data/frames/PILOT_ROOM_01/dry_run
  ```
- [ ] Verify student names appear in output with confidence scores

### Hour 3 — Live Session 1
- [ ] Confirm a class is in session (students seated, normal conditions)
- [ ] Start the dashboard:
  ```bash
  uvicorn web.app:app --host 0.0.0.0 --port 8000
  ```
- [ ] Open dashboard in browser: `http://localhost:8000`
- [ ] Run live session:
  ```bash
  python src/attendance.py --session live_01 --subject "Subject Name"
  ```
- [ ] Watch terminal — detections should print in real time
- [ ] After session: check dashboard for attendance records
- [ ] Compare against physical headcount in the room

### Hour 4 — Calibration + Live Session 2
- [ ] Based on Session 1 results, adjust `config.yaml` if needed:

  | Observation | Fix |
  |---|---|
  | Too many "Unknown" faces | Lower `match_threshold`: 0.4 → 0.35 |
  | Wrong students marked Present | Raise `match_threshold`: 0.4 → 0.45 |
  | Students missed despite being present | Lower `detection_confidence`: 0.75 → 0.70 |
  | Too many false positives | Raise `min_frames_for_present`: 3 → 4 |

- [ ] Run Live Session 2:
  ```bash
  python src/attendance.py --session live_02 --subject "Subject Name"
  ```
- [ ] Get manual ground truth from faculty (who was actually present in both sessions)

### Hour 5 — Report + Client Handover
- [ ] Prepare ground truth CSV (`data/ground_truth.csv`) and generate accuracy report:
  ```bash
  python src/report.py --ground-truth data/ground_truth.csv
  ```
- [ ] Open report from `reports/` folder — review accuracy % and false positive rate
- [ ] Walk client admin/principal through the dashboard (filter by date, export CSV)
- [ ] Share next steps for full rollout

---

## SUCCESS CRITERIA (from Scope of Work)
By end of the trial, you should be able to confirm:
- [ ] Identification Accuracy ≥ 85%
- [ ] False Positives < 2%
- [ ] Dashboard showing records within 5 minutes of session
- [ ] 2 successful live sessions completed

---

## IF THINGS GO WRONG

| Problem | Quick fix |
|---|---|
| RTSP won't connect | Run `ping <camera-IP>` — if no reply, camera not on same network as server |
| Low accuracy (<70%) | Check camera placement — must be center-mounted, not corner |
| Model download fails | Copy `buffalo_l` folder from USB to `C:\Users\<user>\.insightface\models\` |
| Dashboard won't open | Check port 8000 is not blocked by firewall: `netsh advfirewall firewall add rule name="FRAS" protocol=TCP dir=in localport=8000 action=allow` |
| pip install fails | See Tech Setup Document — likely missing VS Build Tools or wrong Python version |

---

*Perfect Skills | FRAS Pilot | Confidential*
