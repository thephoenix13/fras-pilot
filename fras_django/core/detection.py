"""
Face detection with automatic upscaling for small/CCTV images.
Ported from old FRAS Django code (views.py detect_faces_insightface).
"""

import time

import cv2
import numpy as np

MIN_FACE_SIZE  = 20
MIN_DET_SCORE  = 0.75
FACE_OUTPUT_SIZE = (200, 200)


def detect_faces(app, image):
    """
    Detect faces using InsightFace. Upscales images smaller than 800x600 up to 3x
    before detection so tiny CCTV faces get found.

    Returns: (faces, processed_image, scale_factor)
    """
    h, w = image.shape[:2]

    scale = 1.0
    if w < 800 or h < 600:
        scale = max(1280 / w, 960 / h)
        scale = min(scale, 3.0)
        new_w, new_h = int(w * scale), int(h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    faces = app.get(image)
    faces = sorted(faces, key=lambda f: f.bbox[0])  # left-to-right order
    return faces, image, scale


def crop_face(image, bbox, padding=0.3):
    """Crop a face from bbox with proportional padding, resized to FACE_OUTPUT_SIZE."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox.astype(int)
    pad = int((y2 - y1) * padding)

    top    = max(0, y1 - pad)
    bottom = min(h, y2 + pad)
    left   = max(0, x1 - pad)
    right  = min(w, x2 + pad)

    crop = image[top:bottom, left:right]
    return cv2.resize(crop, FACE_OUTPUT_SIZE, interpolation=cv2.INTER_CUBIC)
