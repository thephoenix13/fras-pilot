"""
Debug script: runs recognition on a sample frame and prints the raw
cosine similarity scores for every detected face — regardless of threshold.
Use this to find the right match_threshold value.

Usage:
    python src/debug_scores.py --frames data/frames/CLASSROOM-122/live_01
"""

import argparse
import json
import os

import cv2
import faiss
import numpy as np
import yaml
from insightface.app import FaceAnalysis


def load_config(config_path="config.yaml"):
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_index(config):
    index = faiss.read_index(config["paths"]["faiss_index"])
    with open(config["paths"]["student_db"]) as f:
        student_db = {int(k): v for k, v in json.load(f).items()}
    return index, student_db


def debug(frames_dir, config, sample=5):
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(1280, 1280))
    index, student_db = load_index(config)

    frames = sorted([
        os.path.join(frames_dir, f)
        for f in os.listdir(frames_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ])[:sample]

    print(f"\nShowing raw similarity scores for first {len(frames)} frames")
    print(f"(threshold in config = {config['recognition']['match_threshold']} → accepts similarity > {1 - config['recognition']['match_threshold']:.2f})\n")

    all_scores = []

    for frame_path in frames:
        img = cv2.imread(frame_path)
        faces = app.get(img)
        print(f"--- {os.path.basename(frame_path)} ({len(faces)} faces) ---")

        for face in faces:
            if face.det_score < 0.5:
                continue
            emb = face.normed_embedding.astype(np.float32).reshape(1, -1)
            distances, indices = index.search(emb, k=3)

            print(f"  Face (det_score={face.det_score:.2f}):")
            for rank, (score, idx) in enumerate(zip(distances[0], indices[0])):
                student = student_db.get(int(idx), {})
                name = student.get("name", "?")
                match = "MATCH" if (1 - score) <= config["recognition"]["match_threshold"] else "below threshold"
                print(f"    #{rank+1}  {name:<35} similarity={score:.4f}  [{match}]")
                all_scores.append(score)

    if all_scores:
        print(f"\n--- Score distribution across all faces ---")
        print(f"  Max similarity : {max(all_scores):.4f}")
        print(f"  Avg similarity : {sum(all_scores)/len(all_scores):.4f}")
        print(f"  Min similarity : {min(all_scores):.4f}")
        print(f"\n  Suggested threshold: set match_threshold to {round(1 - max(all_scores) + 0.05, 2)} or lower in fix_config.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", required=True)
    parser.add_argument("--sample", type=int, default=5, help="Number of frames to sample")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    debug(args.frames, config, args.sample)
