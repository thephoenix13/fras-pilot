"""
Quick camera connectivity test. Run this first thing on-site to verify
the RTSP stream is reachable and frames are readable before anything else.

Usage:
    python src/test_camera.py
    python src/test_camera.py --url rtsp://192.168.1.50/stream1
"""

import argparse
import sys

import cv2
import yaml


def test_camera(rtsp_url: str) -> None:
    print(f"\n[test] Connecting to: {rtsp_url}")
    cap = cv2.VideoCapture(rtsp_url)

    if not cap.isOpened():
        print(f"[FAIL] Cannot connect to stream.")
        print("       Check: IP address correct? Camera on same network? RTSP enabled on camera?")
        sys.exit(1)

    print("[OK]   Connected to stream.")
    print("[test] Reading frame ...")

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        print("[FAIL] Connected but could not read a frame. Check camera firmware/RTSP settings.")
        sys.exit(1)

    output_path = "data/camera_test.jpg"
    cv2.imwrite(output_path, frame)

    h, w = frame.shape[:2]
    print(f"[OK]   Frame captured — {w}x{h} resolution.")
    print(f"[OK]   Saved to {output_path} — open this file to visually verify the image.")
    print("\n[RESULT] Camera is ready for FRAS.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=None, help="Override RTSP URL (default: from config.yaml)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    if args.url:
        rtsp_url = args.url
    else:
        with open(args.config) as f:
            import yaml
            config = yaml.safe_load(f)
        rtsp_url = config["camera"]["rtsp_url"]

    test_camera(rtsp_url)
