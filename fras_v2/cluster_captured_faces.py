"""
cluster_captured_faces.py - Group captured face crops by identity.

Scans the faces/ folder from a capture_frames.py run, extracts an embedding
for each crop using InsightFace, then clusters them so every crop of the same
person ends up in one folder.

Output folders are named:
  person_001_n12/   <- person 1, appeared in 12 crops (most frequent first)
  person_002_n8/
  person_003_n3/
  ...
  unmatched/        <- crops where no face could be detected (rare)

Usage:
    # Cluster a specific run's faces folder
    python cluster_captured_faces.py --faces-dir captured_frames/20260706_091532/faces

    # Cluster all runs at once
    python cluster_captured_faces.py --all

    # Stricter matching (fewer, cleaner clusters)
    python cluster_captured_faces.py --all --threshold 0.72

    # Move instead of copy (saves disk space)
    python cluster_captured_faces.py --all --move

Threshold guide:
    0.55 - very loose, may merge different people (good for low-res CCTV)
    0.65 - default, works well for most classroom cameras
    0.72 - strict, may split one person into 2 clusters if angle varies a lot
"""

import os
import sys
import shutil
import argparse
from datetime import datetime

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLD = 0.65   # cosine similarity to consider two faces the same person
DET_SIZE          = (640, 640)
MIN_DET_SCORE     = 0.60   # lower than capture_frames.py since these are already cropped

CAPTURED_ROOT = "captured_frames"


# ---------------------------------------------------------------------------
# InsightFace (standalone, no Django)
# ---------------------------------------------------------------------------

_face_app = None

def get_face_app():
    global _face_app
    if _face_app is None:
        try:
            from insightface.app import FaceAnalysis
        except ImportError:
            print("[FAIL] insightface not installed. Run: pip install insightface onnxruntime")
            sys.exit(1)
        print("[face] Loading InsightFace buffalo_l ...")
        _face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _face_app.prepare(ctx_id=0, det_size=DET_SIZE)
        print("[face] Model ready.\n")
    return _face_app


# ---------------------------------------------------------------------------
# Embedding extraction
# ---------------------------------------------------------------------------

def get_embedding(image_path):
    """
    Extract a normalised 512-d embedding from a face crop.
    Returns np.ndarray or None if no face detected.
    """
    img = cv2.imread(image_path)
    if img is None:
        return None

    h, w = img.shape[:2]
    # Crops can be small — upscale so the model can work with them
    if w < 112 or h < 112:
        scale = max(112 / w, 112 / h)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

    faces = get_face_app().get(img)
    if not faces:
        return None

    # Pick the largest detected face (the crop should only have one)
    best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    if best.det_score < MIN_DET_SCORE or best.embedding is None:
        return None

    emb = best.embedding.astype(np.float32)
    emb /= (np.linalg.norm(emb) + 1e-9)
    return emb


# ---------------------------------------------------------------------------
# Greedy clustering
# ---------------------------------------------------------------------------

def cluster_embeddings(file_emb_pairs, threshold):
    """
    Greedy nearest-centroid clustering.
    file_emb_pairs: list of (filepath, embedding)
    Returns: list of clusters, each cluster is a list of filepaths.
             Sorted largest-first.
    """
    centroids = []       # running mean embedding per cluster
    sizes     = []       # crop count per cluster
    members   = []       # list of file paths per cluster

    for path, emb in file_emb_pairs:
        if centroids:
            sims = np.array([float(np.dot(emb, c)) for c in centroids])
            best_idx = int(np.argmax(sims))
            if sims[best_idx] >= threshold:
                # Update centroid as running mean
                n = sizes[best_idx]
                centroids[best_idx] = (centroids[best_idx] * n + emb) / (n + 1)
                centroids[best_idx] /= (np.linalg.norm(centroids[best_idx]) + 1e-9)
                sizes[best_idx] += 1
                members[best_idx].append(path)
                continue

        # New cluster
        centroids.append(emb.copy())
        sizes.append(1)
        members.append([path])

    # Sort largest cluster first
    order = sorted(range(len(sizes)), key=lambda i: sizes[i], reverse=True)
    return [members[i] for i in order]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def process_faces_dir(faces_dir, threshold, move):
    """
    Cluster all face crops in faces_dir and write output to faces_dir_clustered/.
    """
    if not os.path.isdir(faces_dir):
        print(f"[skip] Not found: {faces_dir}")
        return

    crops = sorted([
        os.path.join(faces_dir, f)
        for f in os.listdir(faces_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ])

    if not crops:
        print(f"[skip] No crops in {faces_dir}")
        return

    print(f"[cluster] {faces_dir}")
    print(f"          {len(crops)} crops  |  threshold: {threshold}")

    # Extract embeddings
    file_emb_pairs = []
    unmatched = []

    get_face_app()   # ensure loaded before progress loop

    for i, path in enumerate(crops, 1):
        emb = get_embedding(path)
        if emb is not None:
            file_emb_pairs.append((path, emb))
        else:
            unmatched.append(path)
        if i % 10 == 0 or i == len(crops):
            print(f"  Embedding {i}/{len(crops)} ...", end="\r")

    print()

    if not file_emb_pairs:
        print("  [warn] Could not extract embeddings from any crop. "
              "Crops may be too blurry or too small.")
        return

    clusters = cluster_embeddings(file_emb_pairs, threshold)

    # Write output
    out_dir = faces_dir.rstrip("/\\").rstrip("\\") + "_clustered"
    os.makedirs(out_dir, exist_ok=True)

    for rank, members in enumerate(clusters, start=1):
        person_dir = os.path.join(out_dir, f"person_{rank:03d}_n{len(members)}")
        os.makedirs(person_dir, exist_ok=True)
        for src in members:
            dst = os.path.join(person_dir, os.path.basename(src))
            if move:
                shutil.move(src, dst)
            else:
                shutil.copy2(src, dst)

    if unmatched:
        unmatched_dir = os.path.join(out_dir, "unmatched")
        os.makedirs(unmatched_dir, exist_ok=True)
        for src in unmatched:
            dst = os.path.join(unmatched_dir, os.path.basename(src))
            shutil.copy2(src, dst)

    print(f"\n  Done -> {os.path.abspath(out_dir)}")
    print(f"  {len(clusters)} unique person(s) found across {len(file_emb_pairs)} crops")
    if unmatched:
        print(f"  {len(unmatched)} crop(s) moved to unmatched/ (no embedding)")

    print("\n  Breakdown:")
    for rank, members in enumerate(clusters[:20], start=1):
        print(f"    person_{rank:03d}: {len(members)} crop(s)")
    if len(clusters) > 20:
        print(f"    ... and {len(clusters) - 20} more")
    print()


def find_all_faces_dirs(root):
    """Walk captured_frames/ and return every faces/ subfolder found."""
    found = []
    if not os.path.isdir(root):
        print(f"[FAIL] Folder not found: {os.path.abspath(root)}")
        sys.exit(1)
    for run_folder in sorted(os.listdir(root)):
        faces_path = os.path.join(root, run_folder, "faces")
        if os.path.isdir(faces_path):
            found.append(faces_path)
    return found


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Cluster captured face crops by identity."
    )
    ap.add_argument("--faces-dir", default=None,
                    help="Path to a specific faces/ folder from a capture run")
    ap.add_argument("--all", action="store_true",
                    help=f"Process every run under {CAPTURED_ROOT}/")
    ap.add_argument("--root", default=CAPTURED_ROOT,
                    help=f"Root folder to scan when using --all (default: {CAPTURED_ROOT})")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"Cosine similarity threshold (default: {DEFAULT_THRESHOLD}). "
                         "Higher = stricter matching.")
    ap.add_argument("--move", action="store_true",
                    help="Move crops into cluster folders instead of copying")
    args = ap.parse_args()

    if not args.faces_dir and not args.all:
        ap.print_help()
        print("\n[hint] Use --faces-dir <path> for one run, or --all for every run.")
        sys.exit(0)

    if args.all:
        dirs = find_all_faces_dirs(args.root)
        if not dirs:
            print(f"[FAIL] No faces/ folders found under {os.path.abspath(args.root)}")
            sys.exit(1)
        print(f"Found {len(dirs)} capture run(s) to process.\n")
        for d in dirs:
            process_faces_dir(d, args.threshold, args.move)
    else:
        process_faces_dir(args.faces_dir, args.threshold, args.move)


if __name__ == "__main__":
    main()
