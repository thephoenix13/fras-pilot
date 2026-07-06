"""
capture_frames.py - Grab frames from an RTSP stream + extract face crops.

Saves 1 frame every N seconds into a dated output folder.
If --extract-faces is set (default: on), also runs InsightFace RetinaFace on
each saved frame and writes cropped face JPEGs into a faces/ subfolder.

Use this to verify two things at once:
  1. The camera stream is reachable and the frames are usable.
  2. InsightFace can actually detect faces from that camera angle/distance.

Usage:
    python capture_frames.py                              # stream + extract faces
    python capture_frames.py --no-extract-faces           # frames only, no InsightFace
    python capture_frames.py --interval 5                 # 1 frame every 5s
    python capture_frames.py --url "rtsp://user:pass@ip:554/stream1" --out test_run
    python capture_frames.py --interval 4 --max-frames 50
    python capture_frames.py --interval 4 --duration 600  # stop after 10 min

Stop anytime with Ctrl+C.

Output layout
-------------
captured_frames/
  20260706_091532/           <- timestamped run folder
    frames/
      frame_0001_091534.jpg
      frame_0002_091538.jpg
      ...
    faces/
      frame_0001_091534_face1_99.jpg   <- face crop, det_score 99%
      frame_0001_091534_face2_87.jpg
      frame_0002_091538_face1_94.jpg
      ...
    summary.txt              <- per-frame detection log written at the end
"""

import os
import sys
import time
import argparse
from datetime import datetime

# Force RTSP over TCP - far fewer corrupt/torn frames than the UDP default.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2

# Default classroom camera. Override with --url.
DEFAULT_URL = "rtsp://admin:admin%40123@172.22.1.241:554/stream1"

# Padding added around each detected face bbox before cropping (pixels, pre-scale).
FACE_PADDING = 20

# InsightFace detection size. 640x640 is the default used by the main app.
# Bump to 1280 if faces are being missed from a distance.
DET_SIZE = (640, 640)

# Minimum detection confidence to save a face crop.
MIN_DET_SCORE = 0.70


# ---------------------------------------------------------------------------
# InsightFace loader (standalone - no Django)
# ---------------------------------------------------------------------------

_face_app = None

def get_face_app():
    global _face_app
    if _face_app is None:
        try:
            from insightface.app import FaceAnalysis
        except ImportError:
            print("[FAIL] insightface is not installed. Run: pip install insightface onnxruntime")
            sys.exit(1)
        print("[face] Loading InsightFace buffalo_l ...  (first run downloads ~300 MB)")
        t = time.time()
        _face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _face_app.prepare(ctx_id=0, det_size=DET_SIZE)
        print(f"[face] Model ready in {time.time() - t:.1f}s")
    return _face_app


# ---------------------------------------------------------------------------
# Face extraction
# ---------------------------------------------------------------------------

def extract_faces(frame, frame_name, faces_dir):
    """
    Run detection on frame, save each face crop to faces_dir.
    Returns a list of dicts with keys: index, score, bbox, path.
    """
    app = get_face_app()

    h, w = frame.shape[:2]
    scale = 1.0

    # Upscale small frames (same logic as face_engine.py in the main app).
    if w < 800 or h < 600:
        scale = min(max(1280 / w, 960 / h), 3.0)
        resized = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    else:
        resized = frame

    faces = app.get(resized)

    results = []
    for i, face in enumerate(faces, start=1):
        score = float(face.det_score)
        if score < MIN_DET_SCORE:
            continue

        # bbox is in resized-frame coordinates - map back to original.
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        x1 = max(0, int(x1 / scale) - FACE_PADDING)
        y1 = max(0, int(y1 / scale) - FACE_PADDING)
        x2 = min(w,  int(x2 / scale) + FACE_PADDING)
        y2 = min(h,  int(y2 / scale) + FACE_PADDING)

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        score_pct = int(score * 100)
        fname = f"{os.path.splitext(frame_name)[0]}_face{i}_{score_pct}.jpg"
        path  = os.path.join(faces_dir, fname)
        cv2.imwrite(path, crop)

        results.append({
            "index": i,
            "score": score_pct,
            "bbox":  (x1, y1, x2, y2),
            "path":  fname,
        })

    return results


# ---------------------------------------------------------------------------
# Stream helpers
# ---------------------------------------------------------------------------

def open_stream(url):
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return cap


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Capture RTSP frames and optionally extract face crops."
    )
    ap.add_argument("--url",      default=DEFAULT_URL, help="RTSP URL (default: classroom camera)")
    ap.add_argument("--out",      default="captured_frames", help="Output root folder")
    ap.add_argument("--interval", type=float, default=4.0, help="Seconds between saved frames (default: 4)")
    ap.add_argument("--max-frames", type=int, default=0, help="Stop after N frames (0 = unlimited)")
    ap.add_argument("--duration",   type=float, default=0, help="Stop after N seconds (0 = unlimited)")
    ap.add_argument("--extract-faces",    dest="extract", action="store_true",  default=True,
                    help="Run face detection on each frame (default: on)")
    ap.add_argument("--no-extract-faces", dest="extract", action="store_false",
                    help="Skip face detection, save frames only")
    ap.add_argument("--det-size", type=int, default=640,
                    help="InsightFace detection grid size (default: 640; try 1280 for small/distant faces)")
    args = ap.parse_args()

    global DET_SIZE
    DET_SIZE = (args.det_size, args.det_size)

    # Build output dirs
    run_stamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir    = os.path.join(args.out, run_stamp)
    frames_dir = os.path.join(run_dir, "frames")
    faces_dir  = os.path.join(run_dir, "faces")
    os.makedirs(frames_dir, exist_ok=True)
    if args.extract:
        os.makedirs(faces_dir, exist_ok=True)

    print(f"\n[capture] Stream  : {args.url}")
    print(f"[capture] Frames  : {os.path.abspath(frames_dir)}")
    if args.extract:
        print(f"[capture] Faces   : {os.path.abspath(faces_dir)}")
        print(f"[capture] Det size: {DET_SIZE[0]}x{DET_SIZE[1]}  min score: {int(MIN_DET_SCORE*100)}%")
    print(f"[capture] Interval: {args.interval}s   (Ctrl+C to stop)\n")

    if args.extract:
        get_face_app()

    cap = open_stream(args.url)
    if not cap.isOpened():
        print("[FAIL] Could not open the stream. Check URL / network / camera.")
        sys.exit(1)
    print("[OK] Stream opened.\n")

    log_lines   = []
    saved       = 0
    total_faces = 0
    last_save   = 0.0
    start       = time.time()
    fails       = 0

    try:
        while True:
            if not cap.grab():
                fails += 1
                print(f"[warn] Grab failed ({fails}). Reconnecting in 2s ...")
                cap.release()
                time.sleep(2)
                cap = open_stream(args.url)
                if not cap.isOpened() and fails >= 5:
                    print("[FAIL] Stream stayed down. Stopping.")
                    break
                continue
            fails = 0

            now = time.time()
            if now - last_save >= args.interval:
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    ts    = datetime.now().strftime("%H%M%S")
                    fname = f"frame_{saved + 1:04d}_{ts}.jpg"
                    cv2.imwrite(os.path.join(frames_dir, fname), frame)
                    saved    += 1
                    h, w      = frame.shape[:2]
                    last_save = now

                    if args.extract:
                        face_results = extract_faces(frame, fname, faces_dir)
                        n = len(face_results)
                        total_faces += n

                        scores_str = ", ".join(f"face{r['index']}={r['score']}%" for r in face_results)
                        status = (
                            f"{n} face(s) detected  [{scores_str}]"
                            if face_results else
                            f"0 faces detected (below {int(MIN_DET_SCORE*100)}% threshold)"
                        )
                        print(f"[{saved:04d}] {fname}  ({w}x{h})  ->  {status}")
                        log_lines.append(f"{fname}\t{w}x{h}\t{n} faces\t{scores_str}")
                    else:
                        print(f"[{saved:04d}] {fname}  ({w}x{h})")
                        log_lines.append(f"{fname}\t{w}x{h}")

                    if args.max_frames and saved >= args.max_frames:
                        print(f"\n[done] Reached --max-frames {args.max_frames}.")
                        break

            if args.duration and (time.time() - start) >= args.duration:
                print(f"\n[done] Reached --duration {args.duration}s.")
                break

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n[stop] Ctrl+C - stopping.")
    finally:
        cap.release()

        summary_path = os.path.join(run_dir, "summary.txt")
        elapsed = time.time() - start
        with open(summary_path, "w") as f:
            f.write(f"FRAS capture run -- {run_stamp}\n")
            f.write(f"Stream:    {args.url}\n")
            f.write(f"Duration:  {elapsed:.1f}s\n")
            f.write(f"Frames:    {saved}\n")
            if args.extract:
                f.write(f"Faces:     {total_faces} crops saved\n")
                f.write(f"Det size:  {DET_SIZE[0]}x{DET_SIZE[1]}\n")
            f.write(f"\n{'frame':<40} {'resolution':<12} {'faces':<10} scores\n")
            f.write("-" * 80 + "\n")
            for line in log_lines:
                f.write(line + "\n")

        print(f"\n[capture] {saved} frame(s) saved.")
        if args.extract:
            print(f"[capture] {total_faces} face crop(s) saved.")
        print(f"[capture] Summary -> {os.path.abspath(summary_path)}")


if __name__ == "__main__":
    main()
