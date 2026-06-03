"""
capture_frames.py - Grab still frames from an RTSP stream at a fixed interval.

Saves 1 frame every N seconds into a dated output folder. Useful for sampling
the classroom camera: collecting test images, checking framing/lighting, or
building an enrollment image set.

Usage (inside the fras_v2 venv):
    python capture_frames.py
    python capture_frames.py --interval 5
    python capture_frames.py --url "rtsp://user:pass@ip:554/stream1" --out frames_room122
    python capture_frames.py --interval 4 --max-frames 50      # stop after 50 frames
    python capture_frames.py --interval 4 --duration 600       # stop after 10 minutes

Stop anytime with Ctrl+C.
"""

import os
import sys
import time
import argparse
from datetime import datetime

# Force RTSP over TCP - far fewer corrupt/torn frames than the UDP default.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2

# Default classroom camera (already stored in the repo's config). Override with --url.
DEFAULT_URL = "rtsp://admin:admin%40123@172.22.1.241:554/stream1"


def open_stream(url):
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    # Keep the internal buffer tiny so retrieved frames are recent, not stale.
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return cap


def main():
    ap = argparse.ArgumentParser(
        description="Capture frames from an RTSP stream at a fixed interval."
    )
    ap.add_argument("--url", default=DEFAULT_URL, help="RTSP URL (default: classroom camera)")
    ap.add_argument("--out", default="captured_frames", help="Output folder (default: captured_frames)")
    ap.add_argument("--interval", type=float, default=4.0, help="Seconds between saved frames (default: 4)")
    ap.add_argument("--max-frames", type=int, default=0, help="Stop after this many frames (0 = unlimited)")
    ap.add_argument("--duration", type=float, default=0, help="Stop after this many seconds (0 = unlimited)")
    args = ap.parse_args()

    # Put everything under a timestamped subfolder so runs don't overwrite each other.
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out, run_stamp)
    os.makedirs(out_dir, exist_ok=True)

    print(f"[capture] Stream : {args.url}")
    print(f"[capture] Folder : {os.path.abspath(out_dir)}")
    print(f"[capture] Every  : {args.interval}s   (Ctrl+C to stop)")

    cap = open_stream(args.url)
    if not cap.isOpened():
        print("[FAIL] Could not open the stream. Check the URL / network / camera is reachable.")
        sys.exit(1)
    print("[OK] Stream opened. Capturing...")

    saved = 0
    last_save = 0.0           # force an immediate first capture
    start = time.time()
    fails = 0

    try:
        while True:
            # grab() advances the decoder cheaply; keeps us near live, draining the buffer.
            if not cap.grab():
                fails += 1
                print(f"[warn] Frame grab failed ({fails}). Reconnecting in 2s...")
                cap.release()
                time.sleep(2)
                cap = open_stream(args.url)
                if not cap.isOpened() and fails >= 5:
                    print("[FAIL] Stream stayed down after several retries. Stopping.")
                    break
                continue
            fails = 0

            now = time.time()
            if now - last_save >= args.interval:
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    ts = datetime.now().strftime("%H%M%S")
                    fname = f"frame_{saved + 1:04d}_{ts}.jpg"
                    path = os.path.join(out_dir, fname)
                    cv2.imwrite(path, frame)
                    saved += 1
                    h, w = frame.shape[:2]
                    print(f"[{saved:04d}] saved {fname}  ({w}x{h})")
                    last_save = now

                    if args.max_frames and saved >= args.max_frames:
                        print(f"[done] Reached --max-frames {args.max_frames}.")
                        break

            if args.duration and (now - start) >= args.duration:
                print(f"[done] Reached --duration {args.duration}s.")
                break

            time.sleep(0.05)   # don't peg the CPU while grabbing

    except KeyboardInterrupt:
        print("\n[stop] Ctrl+C - stopping.")
    finally:
        cap.release()
        print(f"[capture] Done. {saved} frame(s) saved to {os.path.abspath(out_dir)}")


if __name__ == "__main__":
    main()
