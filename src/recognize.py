"""
Recognition engine: given a frame path, detects all faces and matches each
against the enrolled FAISS index.

Returns a list of detections: [{student_id, name, confidence, bbox}]
Can also be run standalone on a directory of frames.

Usage:
    python src/recognize.py --frames data/frames/PILOT_ROOM_01/morning_01
"""

import argparse
import json
import os

import cv2
import faiss
import numpy as np
import yaml
from insightface.app import FaceAnalysis


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_index(config: dict) -> tuple[faiss.Index, dict]:
    faiss_path = config["paths"]["faiss_index"]
    db_path = config["paths"]["student_db"]

    if not os.path.exists(faiss_path):
        raise FileNotFoundError(f"FAISS index not found: {faiss_path}. Run enroll.py first.")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Student DB not found: {db_path}. Run enroll.py first.")

    index = faiss.read_index(faiss_path)
    with open(db_path) as f:
        # Keys are int positions in the FAISS index
        student_db = {int(k): v for k, v in json.load(f).items()}

    return index, student_db


def init_face_model() -> FaceAnalysis:
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    return app


def recognize_frame(
    app: FaceAnalysis,
    index: faiss.Index,
    student_db: dict,
    frame_path: str,
    det_confidence: float,
    match_threshold: float,
) -> list[dict]:
    img = cv2.imread(frame_path)
    if img is None:
        return []

    faces = app.get(img)
    results = []

    for face in faces:
        if face.det_score < det_confidence:
            continue

        embedding = face.normed_embedding.astype(np.float32).reshape(1, -1)
        distances, indices = index.search(embedding, k=1)

        score = float(distances[0][0])   # cosine similarity (higher = better)
        idx = int(indices[0][0])

        # Convert cosine similarity to distance: distance = 1 - similarity
        # Reject if similarity is too low (i.e. distance > threshold)
        if (1 - score) > match_threshold:
            results.append({
                "student_id": "UNKNOWN",
                "name": "Unknown",
                "confidence": round(score, 4),
                "bbox": face.bbox.tolist(),
            })
            continue

        student = student_db.get(idx, {})
        results.append({
            "student_id": student.get("student_id", "UNKNOWN"),
            "name": student.get("name", "Unknown"),
            "confidence": round(score, 4),
            "bbox": face.bbox.tolist(),
        })

    return results


def recognize_session(frames_dir: str, config: dict) -> dict[str, list[dict]]:
    index, student_db = load_index(config)
    app = init_face_model()

    det_confidence = config["recognition"]["detection_confidence"]
    match_threshold = config["recognition"]["match_threshold"]

    frame_files = sorted([
        os.path.join(frames_dir, f)
        for f in os.listdir(frames_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ])

    if not frame_files:
        print(f"[warn] No frames found in {frames_dir}")
        return {}

    session_results = {}
    for frame_path in frame_files:
        detections = recognize_frame(app, index, student_db, frame_path, det_confidence, match_threshold)
        session_results[frame_path] = detections
        detected_names = [d["name"] for d in detections if d["student_id"] != "UNKNOWN"]
        print(f"  {os.path.basename(frame_path)}: {len(detections)} face(s) → {detected_names}")

    return session_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", required=True, help="Directory of frames from one session")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    results = recognize_session(args.frames, config)
    print(f"\n[done] Processed {len(results)} frames.")
