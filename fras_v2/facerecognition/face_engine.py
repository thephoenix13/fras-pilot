"""
Face recognition engine.
- Lazy-loads InsightFace buffalo_l (RetinaFace + ArcFace).
- Provides detection, embedding extraction, and multi-embedding identification.
"""

import time
import threading

import cv2
import numpy as np

from django.conf import settings

_face_app = None
_face_app_lock = threading.Lock()


def get_face_app():
    """Lazy-load the InsightFace model (thread-safe)."""
    global _face_app
    with _face_app_lock:
        if _face_app is None:
            from insightface.app import FaceAnalysis
            print("[FRAS] Loading InsightFace buffalo_l model …")
            t = time.time()
            _face_app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
            _face_app.prepare(ctx_id=0, det_size=(640, 640))
            print(f"[FRAS] Model loaded in {time.time() - t:.1f}s")
    return _face_app


# ── Detection ──────────────────────────────────────────────────────────────

def detect_faces(image, upscale_small=True):
    """
    Detect all faces in an image. Returns (faces, processed_image, scale).
    `faces` is a list of InsightFace Face objects (with bbox, det_score, embedding).
    """
    app = get_face_app()
    h, w = image.shape[:2]
    scale = 1.0

    # Upscale small CCTV frames for better detection
    if upscale_small and (w < 800 or h < 600):
        scale = min(max(1280 / w, 960 / h), 3.0)
        new_w, new_h = int(w * scale), int(h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    faces = app.get(image)
    return faces, image, scale


def cosine_distance(a, b):
    """Cosine distance between two normalized embeddings."""
    return 1.0 - float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


# ── Student embedding extraction ───────────────────────────────────────────

def extract_embedding_from_image_path(path):
    """
    Load an image and extract the largest face's embedding.
    Returns (embedding, det_score) or (None, 0.0) if no face found.
    """
    img = cv2.imread(path)
    if img is None:
        return None, 0.0

    h, w = img.shape[:2]
    # Upscale tiny photos
    if w < 400 or h < 400:
        sc = min(640 / max(w, h), 3.0)
        img = cv2.resize(img, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_CUBIC)

    app = get_face_app()
    faces = app.get(img)
    if not faces:
        return None, 0.0

    # Pick the largest face
    best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    if best.embedding is None:
        return None, 0.0

    emb = best.embedding.astype(np.float32)
    emb = emb / (np.linalg.norm(emb) + 1e-9)
    return emb, float(best.det_score)


# ── Student database loading & matching ────────────────────────────────────

def load_all_students():
    """
    Load every active student's embeddings.
    Returns: list of (student_pk, name, roll, [list_of_embeddings])
    """
    from .models import Student
    out = []
    for s in Student.objects.filter(is_active=True):
        if not s.face_encoding or s.n_embeddings == 0:
            continue
        arr = np.frombuffer(s.face_encoding, dtype=np.float32)
        if len(arr) % 512 != 0:
            continue
        n = len(arr) // 512
        embs = [arr[i * 512:(i + 1) * 512] for i in range(n)]
        out.append((s.pk, s.name, s.roll_number, embs))
    return out


def identify(face_embedding, student_db, threshold=None):
    """
    Identify a query face against the student database.
    Returns: (student_pk, name, roll, confidence_pct) or (None, 'Unknown', '', 0.0)
    """
    if threshold is None:
        threshold = settings.FRAS_CONFIG['recognition']['match_threshold']

    if face_embedding is None or not student_db:
        return None, 'Unknown', '', 0.0

    emb = face_embedding.astype(np.float32)
    emb = emb / (np.linalg.norm(emb) + 1e-9)

    best_dist = float('inf')
    best = None

    for pk, name, roll, embs in student_db:
        # Take the minimum distance across all of this student's photos
        student_best = min(cosine_distance(emb, ref) for ref in embs)
        if student_best < best_dist:
            best_dist = student_best
            best = (pk, name, roll)

    if best is not None and best_dist < threshold:
        conf = round((1 - best_dist) * 100, 1)
        return best[0], best[1], best[2], conf
    return None, 'Unknown', '', 0.0


def pack_embeddings(embeddings):
    """Pack a list of 512-d float32 embeddings into bytes for DB storage."""
    if not embeddings:
        return b'', 0
    normalized = []
    for emb in embeddings:
        emb = np.asarray(emb, dtype=np.float32)
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        normalized.append(emb)
    stacked = np.concatenate(normalized).astype(np.float32)
    return stacked.tobytes(), len(normalized)
