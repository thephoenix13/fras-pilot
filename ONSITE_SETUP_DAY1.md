# FRAS Pilot — On-Site Setup Guide (Day 1)
**For:** Resource on-site at client location  
**Support:** Call/WhatsApp Pratik (Pune) for anything you're unsure about  
**Goal:** By end of Day 1, Pratik should have full remote access to the server and the camera RTSP URL should be confirmed working.

---

## PART A — Remote Access Setup
*Do this first. Everything else can be handled by Pratik remotely once this is done.*

### Step 1 — Install TeamViewer on the server
1. Open a browser on the server machine
2. Go to teamviewer.com → Download → TeamViewer Full (free for personal/trial)
3. Install it and open it
4. You will see a **Your ID** (9-digit number) and a **Password**
5. Share both with Pratik over WhatsApp right now
6. Keep TeamViewer open — do not close it

> **If the client's IT policy doesn't allow TeamViewer**, install **AnyDesk** instead (anydesk.com). Same process — share the 9-digit address and password.

---

## PART B — Server Readiness Check
*Walk through this checklist on the server and report results to Pratik.*

### Step 2 — Check the OS
- [ ] Open **System Information** (search in Start menu)
- [ ] Note down: OS Name, OS Version, System Type (should be x64)
- [ ] Confirm it is Windows 10/11 or Ubuntu 22.04 LTS

### Step 3 — Check RAM and Storage
- [ ] Open **Task Manager** → Performance tab → Memory  
      Note: Total installed RAM (need minimum 16 GB)
- [ ] Open **File Explorer** → This PC  
      Note: Free space on C: drive (need minimum 100 GB free)

### Step 4 — Check Internet Access
- [ ] Open a browser and confirm the server can access the internet  
      (needed for downloading Python packages on Day 1 only)

### Step 5 — Check if Python is installed
- [ ] Open **Command Prompt** (search "cmd" in Start menu)
- [ ] Type: `python --version` and press Enter
- [ ] Note down what it shows (or "not found")

---

## PART C — Camera Check
*This is the part only you can do — the camera is on the local network.*

### Step 6 — Find the camera's IP address
Option A — Check the label on the camera itself (IP is sometimes printed on it)  
Option B — Ask the client's IT person for the camera IP  
Option C — Log into the network router admin panel (usually `192.168.1.1`) and look for connected devices

### Step 7 — Access the camera admin panel
1. Open a browser on the server
2. Go to `http://<camera-IP>` (e.g. `http://192.168.1.50`)
3. Log in (default credentials are usually `admin / admin` or `admin / 12345` — ask client IT if unsure)
4. Look for **Video** or **Stream** settings
5. Find and note down the **RTSP URL** — it looks like:  
   `rtsp://192.168.1.50/stream1` or `rtsp://admin:password@192.168.1.50/h264`

### Step 8 — Test the RTSP stream
1. On the server, open **Command Prompt**
2. Type: `ping <camera-IP>` (e.g. `ping 192.168.1.50`)
3. If you get replies — camera is reachable on the network ✓
4. Note down the camera IP and RTSP URL and send to Pratik

### Step 9 — Check camera placement
Walk into the pilot classroom and verify:
- [ ] Camera is mounted **at the front of the room, center above the board** (not corner)
- [ ] Mounting height is approximately **7–8 feet** from the floor
- [ ] Camera is tilted **slightly downward** (15–20°) toward the students
- [ ] Lighting is **even across all student seats** — no strong backlight from windows

> Take a photo of the classroom from the camera's perspective and send to Pratik.

---

## PART D — Student Data Collection
*Start this on Day 1, must be ready before Day 2 morning.*

### Step 10 — Get student photos
Ask the institution's admin/coordinator to provide:
- [ ] **3–4 photos per student** in the pilot class
  - Front-facing photos preferred
  - College ID card photo is acceptable as the main photo
  - No blurry, masked, or heavily filtered images
- [ ] Photos named as: `STU001_1.jpg`, `STU001_2.jpg`, `STU001_3.jpg` etc.
- [ ] A **CSV or Excel file** with columns: `student_id, name, class, roll_no`

> If photos are on a pen drive or shared folder, copy them to the server under:  
> `C:\fras-pilot\data\photos\`

---

## End of Day 1 — What to Report to Pratik

Send Pratik the following over WhatsApp before you wrap up:

```
1. TeamViewer ID and Password (so he can connect)
2. Server OS and RAM details
3. Python version (or "not installed")
4. Camera IP address
5. RTSP URL (if found)
6. Photo of classroom showing camera position
7. Status of student photos — collected / in progress / not started
```

---

## Common Issues & What To Do

| Problem | What to do |
|---|---|
| TeamViewer blocked by IT | Try AnyDesk instead. If both blocked, set up SSH and share IP + credentials with Pratik |
| Can't find camera IP | Ask client's IT person — they must know their own network |
| Camera login credentials unknown | Try `admin/admin`, `admin/12345`, `admin/password`. If none work, ask client IT |
| Python not installed | Tell Pratik — he will guide you through installing it remotely once TeamViewer is set up |
| Less than 100 GB free disk space | Report to Pratik — may need to clear space before proceeding |

---

*This document is part of the FRAS Pilot deployment by Perfect Skills. Confidential.*
