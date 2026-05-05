"""
Enrollment pipeline: student photos + CSV → ArcFace embeddings → FAISS index on disk.

Usage:
    python src/enroll.py --csv data/students_sample.csv --photos data/photos

Photo naming convention: {student_id}_1.jpg, {student_id}_2.jpg, ...
"""

import argparse
import json
import os
import sys

import cv2
import faiss
import numpy as np
import pandas as pd
import yaml
from insightface.app import FaceAnalysis
from tqdm import tqdm


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def init_face_model() -> FaceAnalysis:
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    return app


def get_embedding(app: FaceAnalysis, image_path: str) -> np.ndarray | None:
    img = cv2.imread(image_path)
    if img is None:
        print(f"  [warn] Cannot read image: {image_path}")
        return None

    faces = app.get(img)
    if not faces:
        print(f"  [warn] No face detected: {image_path}")
        return None

    # Use the largest detected face (most prominent in frame)
    face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return face.normed_embedding.astype(np.float32)


def enroll(csv_path: str, photos_dir: str, config: dict) -> None:
    df = pd.read_csv(csv_path)
    required_cols = {"student_id", "name", "class", "roll_no"}
    if not required_cols.issubset(df.columns):
        print(f"[error] CSV must contain columns: {required_cols}")
        sys.exit(1)

    app = init_face_model()

    embeddings = []
    student_records = {}
    failed = []

    for _, row in tqdm(df.iterrows(), total=len(df), desc="Enrolling students"):
        sid = str(row["student_id"])
        photos = sorted([
            os.path.join(photos_dir, f)
            for f in os.listdir(photos_dir)
            if f.startswith(sid + "_") and f.lower().endswith((".jpg", ".jpeg", ".png"))
        ])

        if not photos:
            print(f"  [warn] No photos found for {sid} — skipping")
            failed.append(sid)
            continue

        student_embeddings = []
        for photo_path in photos:
            emb = get_embedding(app, photo_path)
            if emb is not None:
                student_embeddings.append(emb)

        if not student_embeddings:
            print(f"  [warn] No valid embeddings for {sid} — skipping")
            failed.append(sid)
            continue

        # Average embeddings across all photos for robustness
        avg_embedding = np.mean(student_embeddings, axis=0)
        avg_embedding /= np.linalg.norm(avg_embedding)  # re-normalise after averaging

        embeddings.append(avg_embedding)
        student_records[len(embeddings) - 1] = {
            "student_id": sid,
            "name": row["name"],
            "class": row["class"],
            "roll_no": str(row["roll_no"]),
        }

    if not embeddings:
        print("[error] No students enrolled. Check photos directory and CSV.")
        sys.exit(1)

    # Build FAISS index (inner product on normalised vectors = cosine similarity)
    dim = 512
    index = faiss.IndexFlatIP(dim)
    matrix = np.stack(embeddings)
    index.add(matrix)

    faiss_path = config["paths"]["faiss_index"]
    db_path = config["paths"]["student_db"]

    os.makedirs(os.path.dirname(faiss_path), exist_ok=True)
    faiss.write_index(index, faiss_path)

    with open(db_path, "w") as f:
        json.dump(student_records, f, indent=2)

    print(f"\n[done] Enrolled {len(embeddings)} students.")
    print(f"       FAISS index → {faiss_path}")
    print(f"       Student DB  → {db_path}")
    if failed:
        print(f"[warn] Skipped {len(failed)} students (no photos/detections): {failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="data/students_sample.csv")
    parser.add_argument("--photos", default="data/photos")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    enroll(args.csv, args.photos, config)
