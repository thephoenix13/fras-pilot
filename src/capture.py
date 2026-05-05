"""
RTSP frame capture: connects to the camera, samples frames over a session window,
saves them to disk for the recognition pipeline.

Usage:
    python src/capture.py                          # uses config.yaml defaults
    python src/capture.py --session morning_01     # named session label
"""

import argparse
import os
import time
from datetime import datetime

import cv2
import yaml


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def capture_session(config: dict, session_label: str | None = None) -> list[str]:
    rtsp_url = config["camera"]["rtsp_url"]
    classroom_id = config["camera"]["classroom_id"]
    interval = config["camera"]["frame_interval_seconds"]
    duration = config["camera"]["capture_duration_seconds"]
    frames_dir = config["paths"]["frames_dir"]

    session_label = session_label or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(frames_dir, classroom_id, session_label)
    os.makedirs(output_dir, exist_ok=True)

    print(f"[capture] Connecting to {rtsp_url} ...")
    cap = cv2.VideoCapture(rtsp_url)

    if not cap.isOpened():
        raise RuntimeError(f"Cannot connect to RTSP stream: {rtsp_url}")

    print(f"[capture] Connected. Sampling for {duration}s every {interval}s → {output_dir}")

    saved_paths = []
    start_time = time.time()
    frame_count = 0

    while (time.time() - start_time) < duration:
        ret, frame = cap.read()
        if not ret:
            print("[warn] Failed to read frame — retrying ...")
            time.sleep(1)
            # Attempt reconnect
            cap.release()
            cap = cv2.VideoCapture(rtsp_url)
            continue

        timestamp = datetime.now().strftime("%H%M%S_%f")
        filename = f"frame_{frame_count:04d}_{timestamp}.jpg"
        path = os.path.join(output_dir, filename)
        cv2.imwrite(path, frame)
        saved_paths.append(path)
        frame_count += 1

        print(f"  [frame {frame_count}] saved → {filename}")
        time.sleep(interval)

    cap.release()
    print(f"\n[capture] Done. {frame_count} frames saved to {output_dir}")
    return saved_paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default=None, help="Session label (default: timestamp)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    capture_session(config, args.session)
