"""
Lazy singleton for the InsightFace model.
Import get_face_app() wherever you need detection/recognition.
The model is loaded on first call so Django can start without GPU/model present.
"""

_face_app = None


def get_face_app():
    global _face_app
    if _face_app is None:
        from insightface.app import FaceAnalysis
        import time
        print(f"[FRAS] Loading InsightFace buffalo_l model ...")
        t = time.time()
        _face_app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
        print(f"[FRAS] Model loaded in {time.time() - t:.1f}s")
    return _face_app
