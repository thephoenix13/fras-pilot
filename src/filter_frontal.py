"""
Automatically filters out side profile photos from the enrollment folder.
Keeps only frontal-facing photos using InsightFace pose estimation (yaw angle).

Photos removed are moved to data/removed_profiles/ (not deleted) so you can
review them if needed.

Usage:
    python src/filter_frontal.py
    python src/filter_frontal.py --photos data/enrollment --yaw-limit 35
"""

import argparse
import os
import shutil

import cv2
import numpy as np
import yaml
from insightface.app import FaceAnalysis
from tqdm import tqdm


def load_config(config_path="config.yaml"):
    with open(config_path) as f:
        return yaml.safe_load(f)


def filter_frontal(photos_dir: str, removed_dir: str, yaw_limit: float) -> None:
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))

    os.makedirs(removed_dir, exist_ok=True)

    photos = sorted([
        f for f in os.listdir(photos_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ])

    if not photos:
        print(f"[error] No photos found in {photos_dir}")
        return

    kept = []
    removed = []
    no_face = []

    print(f"\nScanning {len(photos)} photos (yaw limit = ±{yaw_limit}°) ...\n")

    for filename in tqdm(photos, desc="Filtering"):
        path = os.path.join(photos_dir, filename)
        img = cv2.imread(path)

        if img is None:
            no_face.append(filename)
            continue

        faces = app.get(img)

        if not faces:
            print(f"  [no face] {filename} — moving to removed")
            shutil.move(path, os.path.join(removed_dir, filename))
            no_face.append(filename)
            continue

        # Use the largest detected face
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))

        # pose gives [yaw, pitch, roll] in degrees
        yaw = float(face.pose[0]) if face.pose is not None else 0.0

        if abs(yaw) > yaw_limit:
            shutil.move(path, os.path.join(removed_dir, filename))
            removed.append((filename, round(yaw, 1)))
        else:
            kept.append((filename, round(yaw, 1)))

    print(f"\n{'='*50}")
    print(f"  Kept    : {len(kept)} frontal photos")
    print(f"  Removed : {len(removed)} side profiles → {removed_dir}")
    if no_face:
        print(f"  No face : {len(no_face)} photos (also moved to removed)")
    print(f"{'='*50}")

    if removed:
        print(f"\nRemoved photos (yaw angle > ±{yaw_limit}°):")
        for fname, yaw in removed:
            print(f"  {fname}  (yaw={yaw}°)")

    print(f"\nNext step — re-run enrollment with frontal photos only:")
    print(f"  python src/enroll.py --csv data/students.csv --photos {photos_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--photos", default="data/enrollment", help="Enrollment photos folder")
    parser.add_argument("--removed-dir", default="data/removed_profiles", help="Folder to move side profiles into")
    parser.add_argument("--yaw-limit", type=float, default=35, help="Max yaw angle in degrees to keep (default: 35)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    filter_frontal(args.photos, args.removed_dir, args.yaw_limit)
