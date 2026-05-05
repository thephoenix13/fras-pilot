# FRAS — Technical Setup Guide for School Device
**Perfect Skills | Confidential**  
This document covers everything that needs to be installed and configured on the school's server or PC before the FRAS pilot can run.

> **Who does this:** Either Pratik remotely (via TeamViewer) or the school's IT person in advance.  
> **When:** Must be completed before the trial day.  
> **Time required:** ~1–2 hours (mostly waiting for downloads).

---

## SECTION 1 — Minimum System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 64-bit | Windows 11 or Ubuntu 22.04 LTS |
| CPU | Intel Core i5 / AMD Ryzen 5 | Intel Core i7 / Xeon |
| RAM | 16 GB | 32 GB |
| Storage | 100 GB free disk space | 500 GB SSD |
| GPU | Not required for pilot | NVIDIA GPU 8GB+ VRAM for full rollout |
| Network | Must be on same LAN as classroom camera | Gigabit LAN preferred |
| Internet | Required during setup only | Not needed after setup |

> **Pilot note:** A laptop meeting these specs works fine for the 1-classroom pilot. A dedicated server is only needed for the full 150-classroom rollout.

---

## SECTION 2 — Step-by-Step Installation (Windows)

### Step 1 — Install Python 3.11

> Python 3.14 (latest) is NOT recommended — some AI packages don't support it yet. Use Python 3.11.

1. Download Python 3.11 from the official site:  
   `https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe`
2. Run the installer
3. **Important:** On the first screen, check **"Add Python to PATH"** before clicking Install
4. Choose "Install Now"
5. After install, open **Command Prompt** and verify:
   ```
   python --version
   ```
   Should show: `Python 3.11.x`

---

### Step 2 — Install Microsoft Visual C++ Build Tools

> Required for compiling the InsightFace face recognition library.

1. Download Build Tools:  
   `https://aka.ms/vs/17/release/vs_BuildTools.exe`
2. Run the installer
3. In the installer screen, check **"Desktop development with C++"**
4. On the right panel, ensure these are selected:
   - MSVC v143 build tools
   - Windows 11 SDK (or Windows 10 SDK)
   - C++ CMake tools
5. Click **Install** — this takes 10–20 minutes and requires ~4 GB
6. Restart the computer after installation

---

### Step 3 — Install Git

> Needed to download the FRAS project code from the repository.

1. Download Git: `https://git-scm.com/download/win`
2. Run the installer with all default settings
3. Verify in Command Prompt:
   ```
   git --version
   ```

---

### Step 4 — Download the FRAS project

Open Command Prompt and run:
```bash
cd C:\
git clone https://github.com/thephoenix13/fras-pilot.git
cd fras-pilot
```

> **Note:** The repository is private. You will be prompted for GitHub credentials.  
> Use the GitHub username and a Personal Access Token (PAT) as the password.  
> To generate a PAT: GitHub → Settings → Developer Settings → Personal Access Tokens → Generate New Token → select `repo` scope.

> **No internet / no GitHub access?** Copy the project folder from a USB drive to `C:\fras-pilot\` instead.

---

### Step 5 — Create a virtual environment

> Keeps FRAS dependencies isolated from other Python software on the machine.

```bash
cd C:\fras-pilot
python -m venv venv
venv\Scripts\activate
```

You should see `(venv)` appear at the start of your command prompt. Run all future commands inside this environment.

---

### Step 6 — Install Python dependencies

```bash
pip install -r requirements.txt
```

This downloads and installs all required libraries. Takes 5–15 minutes depending on internet speed.

Expected output at the end:
```
Successfully installed insightface-0.7.3 faiss-cpu-1.x.x onnxruntime-1.x.x ...
```

---

### Step 7 — Download the Face Recognition Model

The AI model downloads automatically on first run. To pre-download it (recommended — avoids delays on trial day):

```bash
python -c "from insightface.app import FaceAnalysis; app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); app.prepare(ctx_id=-1)"
```

This downloads ~300 MB of model files to `C:\Users\<username>\.insightface\models\buffalo_l\`

---

### Step 8 — Verify the full installation

Run the built-in verification script:

```bash
python src/test_camera.py --url rtsp://<camera-ip>/stream1
```

Replace `<camera-ip>` with the actual camera IP address on the school network.

Expected output:
```
[OK]   Connected to stream.
[OK]   Frame captured — 1920x1080 resolution.
[OK]   Saved to data/camera_test.jpg
[RESULT] Camera is ready for FRAS.
```

Open `data/camera_test.jpg` to visually confirm the classroom frame looks correct.

---

## SECTION 3 — Network Configuration

### Camera must be on the same LAN as the server

```
[Classroom Camera] ──── [Network Switch] ──── [Server/PC running FRAS]
       RTSP stream over local network (no internet needed)
```

- Camera and server must be connected to the **same router or switch**
- Wi-Fi works for testing but is not recommended for live sessions (frame drops)
- **Gigabit LAN is strongly recommended** for the full rollout

### How to find the camera's RTSP URL

1. Log into your camera's admin panel via browser (e.g. `http://192.168.1.50`)
2. Navigate to: **Configuration → Video → Stream**
3. Note the RTSP URL — common formats:

| Camera Brand | Typical RTSP URL |
|---|---|
| Hikvision | `rtsp://admin:password@192.168.1.50:554/Streaming/Channels/101` |
| CP Plus | `rtsp://admin:admin@192.168.1.50:554/stream1` |
| Dahua | `rtsp://admin:password@192.168.1.50:554/cam/realmonitor?channel=1&subtype=0` |
| Generic IP Cam | `rtsp://192.168.1.50/stream1` |

4. Update `config.yaml` with the confirmed URL:
```yaml
camera:
  rtsp_url: "rtsp://admin:password@192.168.1.50:554/stream1"
```

### Open dashboard port on firewall (if needed)

If the dashboard is not accessible from other devices on the network:
```bash
netsh advfirewall firewall add rule name="FRAS Dashboard" protocol=TCP dir=in localport=8000 action=allow
```

---

## SECTION 4 — Camera Placement Requirements

Camera placement is the **single biggest factor in accuracy**. Get this right before running any sessions.

```
         [CAMERA]
            |
          7-8 ft
          height
        15-20° tilt
            |
    =============================  ← Blackboard / front wall
    |                           |
    |    [Student seats]        |
    |                           |
    =============================
```

| Requirement | Detail |
|---|---|
| Position | Center of classroom, above the blackboard. NOT corner-mounted. |
| Height | 7–8 feet from floor |
| Tilt | 15–20° downward toward students |
| Resolution | Minimum 1080p Full HD |
| Lighting | Even light across all seats. Avoid rooms where windows are behind students. |

**Impact of placement on accuracy:**
- Corner-mounted camera: ~79% accuracy (tested)
- Center-mounted camera: ~90–95% accuracy (expected)

---

## SECTION 5 — Folder Structure After Setup

```
C:\fras-pilot\
├── config.yaml              ← Update RTSP URL here before running
├── requirements.txt
├── data\
│   ├── photos\              ← Drop student photos here (STU001_1.jpg etc.)
│   ├── frames\              ← Captured RTSP frames land here automatically
│   └── students_sample.csv  ← Replace with actual student metadata
├── db\                      ← FAISS index and SQLite DB (auto-created)
├── reports\                 ← Accuracy reports (Excel)
├── src\
│   ├── enroll.py
│   ├── capture.py
│   ├── recognize.py
│   ├── attendance.py
│   ├── test_camera.py
│   └── report.py
└── web\
    └── app.py               ← Dashboard server
```

---

## SECTION 6 — Quick Command Reference

```bash
# Activate environment (run this every time you open a new terminal)
venv\Scripts\activate

# Test camera connectivity
python src/test_camera.py

# Enroll students
python src/enroll.py --csv data/students.csv --photos data/photos

# Run a live attendance session
python src/attendance.py --session morning_01 --subject "Mathematics"

# Start dashboard (open http://localhost:8000 in browser)
uvicorn web.app:app --host 0.0.0.0 --port 8000

# Generate accuracy report
python src/report.py --ground-truth data/ground_truth.csv
```

---

## SECTION 7 — Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `python not found` | Python not in PATH | Reinstall Python, check "Add to PATH" box |
| `error: Microsoft Visual C++ 14.0 required` | Build Tools not installed | Complete Step 2 above |
| `No matching distribution found for faiss-cpu` | Wrong Python version | Use Python 3.11 (Step 1) |
| `Cannot connect to RTSP stream` | Camera not reachable | Run `ping <camera-ip>` — check network |
| `No face detected` in enrollment | Bad photo quality | Use clear, well-lit, unmasked photos |
| Dashboard not loading | Port blocked | Run firewall command in Section 3 |
| Low accuracy in live session | Poor camera placement | See Section 4 — center mount required |

---

*Perfect Skills | FRAS Pilot | Confidential*  
*For technical support contact: pratikgade@perfectskills.in*
