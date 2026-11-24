"""
match_students.py — Match clustered face identities against Class III BCOMP-I enrollment photos.

Instead of matching raw crops one-by-one, this script:
  1. Builds a student embedding DB from enrollment photos (up to N photos each).
  2. For each person_XXX cluster in faces_clustered/, averages all crop embeddings
     into one robust "person embedding".
  3. Matches each person embedding against the student DB.
  4. Reports which student each cluster matched (or UNKNOWN).

Usage (from D:\Projects\fras-pilot\fras_v2\):
    python match_students.py
    python match_students.py --threshold 0.50
    python match_students.py --sessions 20260706_105203          # single session
    python match_students.py --out results.csv

Threshold guide (cosine distance — lower = stricter):
    0.40  strict — clean enrollment photos, good camera angle
    0.50  default — CCTV crops, some angle/lighting variation
    0.60  loose — low-res or heavy occlusion
"""

import os
import sys
import csv
import argparse

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

STUDENTS_DIR   = r"D:\Projects\fras-pilot\fras_v2\data\class_III_BCOMP_I\Class section III BCOMP-I"
CAPTURES_ROOT  = r"D:\Projects\fras-pilot\fras_v2\captured_frames"
DEFAULT_THRESHOLD = 0.50
DEFAULT_OUT    = "match_results.csv"
DET_SIZE       = (640, 640)
MIN_DET_SCORE  = 0.45   # lower threshold for CCTV crops which are already cropped faces

# ---------------------------------------------------------------------------
# InsightFace
# ---------------------------------------------------------------------------

_face_app = None

def get_face_app():
    global _face_app
    if _face_app is None:
        try:
            from insightface.app import FaceAnalysis
        except ImportError:
            print("[FAIL] insightface not installed.  pip install insightface onnxruntime")
            sys.exit(1)
        print("[model] Loading InsightFace buffalo_l ...")
        _face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _face_app.prepare(ctx_id=0, det_size=DET_SIZE)
        print("[model] Ready.\n")
    return _face_app


def embed(image_path, upscale=True):
    """Return normalised 512-d embedding or None."""
    img = cv2.imread(image_path)
    if img is None:
        return None
    h, w = img.shape[:2]
    if upscale and (w < 400 or h < 400):
        scale = min(640 / max(w, h), 3.0)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    faces = get_face_app().get(img)
    if not faces:
        return None
    best = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
    if best.det_score < MIN_DET_SCORE or best.embedding is None:
        return None
    e = best.embedding.astype(np.float32)
    e /= np.linalg.norm(e) + 1e-9
    return e


def mean_embedding(paths):
    """Average all valid embeddings from a list of image paths."""
    embs = [embed(p) for p in paths]
    embs = [e for e in embs if e is not None]
    if not embs:
        return None
    mean = np.mean(embs, axis=0).astype(np.float32)
    mean /= np.linalg.norm(mean) + 1e-9
    return mean

# ---------------------------------------------------------------------------
# Student DB
# ---------------------------------------------------------------------------

def build_student_db(students_dir):
    if not os.path.isdir(students_dir):
        print(f"[FAIL] Students dir not found:\n  {students_dir}")
        sys.exit(1)

    get_face_app()
    folders = sorted(d for d in os.listdir(students_dir)
                     if os.path.isdir(os.path.join(students_dir, d)))

    print(f"[enroll] {len(folders)} student folders found.\n")
    db = []
    for folder in folders:
        parts = folder.split("-", 1)
        roll = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else folder
        fpath = os.path.join(students_dir, folder)
        photos = [os.path.join(fpath, f) for f in os.listdir(fpath)
                  if f.lower().endswith((".jpg", ".jpeg", ".png"))]

        emb = mean_embedding(photos) if photos else None
        status = f"{len(photos)} photo(s)" if photos else "NO PHOTOS"
        if photos and emb is None:
            status = f"{len(photos)} photo(s) — embed failed"
        print(f"  {roll}  {name:<40}  {status}")
        db.append({"roll": roll, "name": name, "embedding": emb, "photo_count": len(photos)})

    enrolled = sum(1 for s in db if s["embedding"] is not None)
    print(f"\n[enroll] {enrolled}/{len(db)} students embedded.\n")
    return db

# ---------------------------------------------------------------------------
# Cluster matching
# ---------------------------------------------------------------------------

def cosine_dist(a, b):
    return 1.0 - float(np.dot(a, b))


def identify(query_emb, student_db, threshold):
    """Return (roll, name, confidence_pct) or (None, 'UNKNOWN', 0.0)."""
    best_dist, best = float("inf"), None
    for s in student_db:
        if s["embedding"] is None:
            continue
        d = cosine_dist(query_emb, s["embedding"])
        if d < best_dist:
            best_dist, best = d, s
    if best and best_dist < threshold:
        return best["roll"], best["name"], round((1 - best_dist) * 100, 1)
    return None, "UNKNOWN", 0.0


def get_cluster_dirs(session_dir):
    clustered = os.path.join(session_dir, "faces_clustered")
    if not os.path.isdir(clustered):
        return []
    return sorted(
        os.path.join(clustered, d) for d in os.listdir(clustered)
        if os.path.isdir(os.path.join(clustered, d)) and d.startswith("person_")
    )


def match_sessions(captures_root, student_db, threshold, sessions_filter=None):
    sessions = sorted(d for d in os.listdir(captures_root)
                      if os.path.isdir(os.path.join(captures_root, d)))
    if sessions_filter:
        sessions = [s for s in sessions if s in sessions_filter]

    print(f"[match] Sessions: {', '.join(sessions)}")
    print(f"[match] Threshold: {threshold}\n")

    rows = []
    matched_students = {}   # roll -> best result across all clusters

    for session in sessions:
        session_dir = os.path.join(captures_root, session)
        clusters = get_cluster_dirs(session_dir)
        if not clusters:
            print(f"  [{session}] No faces_clustered/ found — skipping.")
            continue

        print(f"  [{session}] {len(clusters)} clusters")

        for cluster_path in clusters:
            cluster_name = os.path.basename(cluster_path)
            n_crops = int(cluster_name.split("_n")[-1]) if "_n" in cluster_name else 0

            crops = [os.path.join(cluster_path, f) for f in os.listdir(cluster_path)
                     if f.lower().endswith((".jpg", ".jpeg", ".png"))]

            avg_emb = mean_embedding(crops)
            if avg_emb is None:
                rows.append({"session": session, "cluster": cluster_name,
                             "crops": n_crops, "roll": "", "name": "EMBED_FAILED", "confidence": 0.0})
                print(f"    {cluster_name}: embed failed")
                continue

            roll, name, conf = identify(avg_emb, student_db, threshold)
            rows.append({"session": session, "cluster": cluster_name,
                         "crops": n_crops, "roll": roll or "", "name": name, "confidence": conf})

            if roll:
                # Keep the highest-confidence match per student
                if roll not in matched_students or conf > matched_students[roll]["confidence"]:
                    matched_students[roll] = {"roll": roll, "name": name,
                                              "confidence": conf, "cluster": cluster_name,
                                              "session": session, "crops": n_crops}
                print(f"    {cluster_name} ({n_crops} crops)  →  {name} [{roll}]  {conf}%")
            else:
                print(f"    {cluster_name} ({n_crops} crops)  →  UNKNOWN")

        print()

    return rows, matched_students

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_summary(matched_students, student_db):
    all_rolls = {s["roll"] for s in student_db if s["embedding"] is not None}
    seen = set(matched_students.keys())
    not_seen = all_rolls - seen
    no_photo = [s for s in student_db if s["embedding"] is None]

    print("=" * 70)
    print("ATTENDANCE SUMMARY")
    print("=" * 70)

    print(f"\nPRESENT — matched to a student ({len(seen)}):")
    print(f"  {'Roll':<10} {'Name':<42} {'Conf':>6}  Cluster")
    print(f"  {'-'*10} {'-'*42} {'-'*6}  {'-'*20}")
    for r in sorted(matched_students.values(), key=lambda x: -x["confidence"]):
        print(f"  {r['roll']:<10} {r['name']:<42} {r['confidence']:>5.1f}%  {r['cluster']} ({r['crops']} crops) [{r['session']}]")

    print(f"\nNOT SEEN — enrolled but unmatched ({len(not_seen)}):")
    for s in sorted(student_db, key=lambda x: x["roll"]):
        if s["roll"] in not_seen:
            print(f"  {s['roll']:<10} {s['name']}")

    if no_photo:
        print(f"\nNO PHOTOS — could not check ({len(no_photo)}):")
        for s in no_photo:
            print(f"  {s['roll']:<10} {s['name']}")

    print("=" * 70)
    print(f"  Present: {len(seen)}  |  Absent: {len(not_seen)}  |  No photo: {len(no_photo)}")
    print("=" * 70)


def write_csv(rows, out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["session","cluster","crops","roll","name","confidence"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n[done] Cluster-level report saved to: {out_path}")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--students", default=STUDENTS_DIR)
    ap.add_argument("--captures", default=CAPTURES_ROOT)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--sessions", nargs="+", default=None,
                    help="Limit to specific session folder(s)")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    student_db = build_student_db(args.students)
    rows, matched = match_sessions(args.captures, student_db, args.threshold, args.sessions)
    print_summary(matched, student_db)
    write_csv(rows, args.out)

if __name__ == "__main__":
    main()
