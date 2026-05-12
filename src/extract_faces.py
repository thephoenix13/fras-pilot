"""
Crop every detected face from a session's frames and save them as individual JPGs.
If the FAISS index exists, crops are tagged with the matched student_id.

Usage:
    python src/extract_faces.py --frames data/frames/PILOT_ROOM_01/morning_01
    python src/extract_faces.py --frames data/frames/PILOT_ROOM_01/morning_01 --out data/faces
    python src/extract_faces.py --frames data/frames/PILOT_ROOM_01/morning_01 --no-recognize
"""

import argparse
import json
import os

import cv2
import faiss
import numpy as np
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


def load_index(config: dict):
    faiss_path = config["paths"]["faiss_index"]
    db_path = config["paths"]["student_db"]
    if not (os.path.exists(faiss_path) and os.path.exists(db_path)):
        return None, None
    index = faiss.read_index(faiss_path)
    with open(db_path) as f:
        student_db = {int(k): v for k, v in json.load(f).items()}
    return index, student_db


def crop_face(img: np.ndarray, bbox, padding: float = 0.2) -> np.ndarray:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    px, py = bw * padding, bh * padding
    x1 = max(0, int(x1 - px))
    y1 = max(0, int(y1 - py))
    x2 = min(w, int(x2 + px))
    y2 = min(h, int(y2 + py))
    return img[y1:y2, x1:x2]


def extract(frames_dir: str, out_dir: str, config: dict, recognize: bool) -> None:
    app = init_face_model()
    det_confidence = config["recognition"]["detection_confidence"]
    match_threshold = config["recognition"]["match_threshold"]

    index, student_db = (None, None)
    if recognize:
        index, student_db = load_index(config)
        if index is None:
            print("[warn] FAISS index not found — saving crops without student tags.")

    os.makedirs(out_dir, exist_ok=True)

    frame_files = sorted([
        os.path.join(frames_dir, f)
        for f in os.listdir(frames_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ])

    if not frame_files:
        print(f"[error] No frames found in {frames_dir}")
        return

    total_faces = 0
    for frame_path in tqdm(frame_files, desc="Extracting faces"):
        img = cv2.imread(frame_path)
        if img is None:
            continue

        faces = app.get(img)
        frame_stem = os.path.splitext(os.path.basename(frame_path))[0]

        for i, face in enumerate(faces):
            if face.det_score < det_confidence:
                continue

            tag = "face"
            if index is not None:
                emb = face.normed_embedding.astype(np.float32).reshape(1, -1)
                distances, indices = index.search(emb, k=1)
                score = float(distances[0][0])
                idx = int(indices[0][0])
                if (1 - score) <= match_threshold:
                    student = student_db.get(idx, {})
                    tag = student.get("student_id", "UNKNOWN")
                else:
                    tag = "UNKNOWN"

            crop = crop_face(img, face.bbox)
            if crop.size == 0:
                continue

            out_name = f"{frame_stem}_face{i:02d}_{tag}.jpg"
            cv2.imwrite(os.path.join(out_dir, out_name), crop)
            total_faces += 1

    print(f"\n[done] {total_faces} face(s) saved to {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", required=True, help="Directory of frames from one session")
    parser.add_argument("--out", default=None, help="Output directory (default: data/faces/<classroom>/<session>)")
    parser.add_argument("--no-recognize", action="store_true", help="Skip student ID tagging")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.out is None:
        rel = os.path.relpath(args.frames, config["paths"]["frames_dir"])
        args.out = os.path.join("data", "faces", rel)

    extract(args.frames, args.out, config, recognize=not args.no_recognize)
