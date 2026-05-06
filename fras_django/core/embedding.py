"""
Embedding helpers: extraction, cosine distance, running average update.
Ported from old FRAS Django code (views.py) + current src/enroll.py.
All embeddings are float32, L2-normalised (normed_embedding from InsightFace).
"""

import numpy as np

EMBEDDING_UPDATE_WEIGHT = 0.3


def get_embedding(app, image_or_path):
    """
    Extract a 512-d normalised ArcFace embedding from an image.
    Accepts an OpenCV BGR array or a file path string.
    Returns float32 ndarray or None if no face detected.
    """
    import cv2
    if isinstance(image_or_path, str):
        img = cv2.imread(image_or_path)
        if img is None:
            return None
    else:
        img = image_or_path

    # Upscale small enrollment photos for better detection
    h, w = img.shape[:2]
    if w < 400 or h < 400:
        sc = min(640 / max(w, h), 3.0)
        img = cv2.resize(img, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_CUBIC)

    faces = app.get(img)
    if not faces:
        return None

    # Use the largest face
    face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return face.normed_embedding.astype(np.float32)


def cosine_distance(emb1, emb2):
    """Cosine distance in [0, 2]. Lower = more similar."""
    sim = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2) + 1e-8)
    return 1.0 - float(sim)


def update_embedding(old_emb, new_emb, weight=EMBEDDING_UPDATE_WEIGHT):
    """
    Running average: blend new embedding into the stored one.
    Keeps the representation adaptive as more frames of the same face arrive.
    """
    updated = (1 - weight) * old_emb + weight * new_emb
    updated = updated / (np.linalg.norm(updated) + 1e-8)
    return updated
