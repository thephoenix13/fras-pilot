"""
Video face extraction with smart deduplication.
Ported from old FRAS Django code (views.py extract_and_save_unique_faces).

Samples one frame every 2 seconds, detects faces, deduplicates by cosine
distance, keeps the best crop per unique face with a running embedding average.
"""

import os
import time

import cv2
import numpy as np

from .detection import detect_faces, crop_face, MIN_DET_SCORE, MIN_FACE_SIZE
from .embedding import cosine_distance, update_embedding

DUPLICATE_TOLERANCE = 0.75


def extract_unique_faces(video_path: str, output_dir: str) -> list[str]:
    """
    Extract unique face crops from a video file.

    Returns a list of saved filenames (relative, under output_dir).
    """
    from .face_engine import get_face_app
    app = get_face_app()

    os.makedirs(output_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps         = cap.get(cv2.CAP_PROP_FPS) or 30
    total       = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step        = int(fps * 2)                    # sample every 2 seconds
    total_steps = max(1, total // step + 1)

    saved_files      = []
    embeddings_list  = []
    best_scores      = []
    seen_counts      = []

    step_idx = 0
    while True:
        frame_pos = step_idx * step
        if frame_pos >= total:
            break

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
        ret, frame = cap.read()
        if not ret:
            break

        faces, processed, scale = detect_faces(app, frame)

        for face in faces:
            if face.det_score < MIN_DET_SCORE:
                continue
            x1, y1, x2, y2 = face.bbox.astype(int)
            if (x2 - x1) < MIN_FACE_SIZE or (y2 - y1) < MIN_FACE_SIZE:
                continue
            if face.embedding is None:
                continue

            emb = face.normed_embedding.astype(np.float32)

            # Check against known faces
            is_dup = False
            if embeddings_list:
                dists = [cosine_distance(emb, e) for e in embeddings_list]
                best_dist = min(dists)
                best_idx  = dists.index(best_dist)

                if best_dist < DUPLICATE_TOLERANCE:
                    is_dup = True
                    seen_counts[best_idx] += 1
                    embeddings_list[best_idx] = update_embedding(embeddings_list[best_idx], emb)

                    # Upgrade crop if better detection score
                    if face.det_score > best_scores[best_idx]:
                        best_scores[best_idx] = face.det_score
                        crop = crop_face(processed, face.bbox)
                        path = os.path.join(output_dir, saved_files[best_idx])
                        cv2.imwrite(path, crop)

            if not is_dup:
                embeddings_list.append(emb.copy())
                best_scores.append(face.det_score)
                seen_counts.append(1)

                fname = f"face_{len(embeddings_list):03d}.jpg"
                crop  = crop_face(processed, face.bbox)
                cv2.imwrite(os.path.join(output_dir, fname), crop)
                saved_files.append(fname)

        step_idx += 1

    cap.release()
    return saved_files
