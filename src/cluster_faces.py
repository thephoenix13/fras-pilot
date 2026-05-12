"""
Cluster face crops by identity so each unique person ends up in their own folder.
Useful for counting how many distinct people appeared in a session.

Greedy clustering: each face is assigned to the nearest existing cluster if the
cosine similarity exceeds the threshold; otherwise a new cluster is created.

Usage:
    python src/cluster_faces.py --faces-dir data/faces/CLASSROOM-122/live_01
    python src/cluster_faces.py --faces-dir data/faces/CLASSROOM-122/live_01 --threshold 0.55
    python src/cluster_faces.py --faces-dir data/faces/CLASSROOM-122/live_01 --move
"""

import argparse
import os
import shutil

import cv2
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


def embed(app: FaceAnalysis, image_path: str):
    img = cv2.imread(image_path)
    if img is None:
        return None
    faces = app.get(img)
    if not faces:
        return None
    face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return face.normed_embedding.astype(np.float32)


def cluster(faces_dir: str, out_dir: str, threshold: float, move: bool) -> None:
    app = init_face_model()

    files = sorted([
        os.path.join(faces_dir, f)
        for f in os.listdir(faces_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ])
    if not files:
        print(f"[error] No face crops in {faces_dir}")
        return

    centroids: list[np.ndarray] = []
    cluster_sizes: list[int] = []
    cluster_members: list[list[str]] = []
    skipped: list[str] = []

    for path in tqdm(files, desc="Clustering"):
        emb = embed(app, path)
        if emb is None:
            skipped.append(path)
            continue

        if centroids:
            sims = np.array([float(np.dot(emb, c)) for c in centroids])
            best = int(np.argmax(sims))
            if sims[best] >= threshold:
                n = cluster_sizes[best]
                centroids[best] = (centroids[best] * n + emb) / (n + 1)
                centroids[best] /= np.linalg.norm(centroids[best])
                cluster_sizes[best] = n + 1
                cluster_members[best].append(path)
                continue

        centroids.append(emb)
        cluster_sizes.append(1)
        cluster_members.append([path])

    os.makedirs(out_dir, exist_ok=True)

    order = sorted(range(len(cluster_sizes)), key=lambda i: cluster_sizes[i], reverse=True)

    for rank, i in enumerate(order, start=1):
        person_dir = os.path.join(out_dir, f"person_{rank:03d}_n{cluster_sizes[i]}")
        os.makedirs(person_dir, exist_ok=True)
        for src in cluster_members[i]:
            dst = os.path.join(person_dir, os.path.basename(src))
            if move:
                shutil.move(src, dst)
            else:
                shutil.copy2(src, dst)

    print(f"\n[done] {len(files)} crops → {len(centroids)} unique candidate(s)")
    print(f"       Threshold: {threshold} (cosine similarity)")
    print(f"       Output:    {out_dir}")
    if skipped:
        print(f"[warn] Skipped {len(skipped)} crops (no embedding extractable)")

    print("\nTop clusters (size = crops per person):")
    for rank, i in enumerate(order[:15], start=1):
        print(f"  person_{rank:03d}: {cluster_sizes[i]} crops")
    if len(order) > 15:
        print(f"  ... and {len(order) - 15} more")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--faces-dir", required=True, help="Directory of face crops (output of extract_faces.py)")
    parser.add_argument("--out", default=None, help="Output directory (default: <faces-dir>_clustered)")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Cosine similarity threshold to merge clusters (default: 1 - config match_threshold)")
    parser.add_argument("--move", action="store_true", help="Move crops instead of copying")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.threshold is None:
        args.threshold = 1.0 - config["recognition"]["match_threshold"]
    if args.out is None:
        args.out = args.faces_dir.rstrip("/\\") + "_clustered"

    cluster(args.faces_dir, args.out, args.threshold, args.move)
