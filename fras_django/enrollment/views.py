import base64
import io
import os
import tempfile
import zipfile

import cv2
import numpy as np
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from PIL import Image

from core.embedding import get_embedding
from core.face_engine import get_face_app
from core.faiss_index import build_and_save, load_index, search
from core.detection import detect_faces

from .forms import BulkEnrollForm, EnrollSingleForm
from .models import Student


# ── Helpers ─────────────────────────────────────────────────────────────────

def _rebuild_faiss_index():
    """
    Rebuild the FAISS index from all active enrolled students.
    Called after any enrollment mutation (add / delete).
    """
    students = Student.objects.filter(is_active=True, face_encoding__isnull=False)
    if not students.exists():
        return

    embeddings = []
    id_map     = {}   # faiss position → student pk
    for pos, s in enumerate(students):
        emb = np.frombuffer(bytes(s.face_encoding), dtype=np.float32)
        if emb.shape[0] == 512:
            embeddings.append(emb)
            id_map[pos] = s.pk

    if not embeddings:
        return

    build_and_save(embeddings, settings.FAISS_INDEX_PATH)

    # Persist id_map so recognition can resolve faiss position → student pk
    import json
    map_path = os.path.join(os.path.dirname(settings.FAISS_INDEX_PATH), 'faiss_map.json')
    with open(map_path, 'w') as f:
        json.dump(id_map, f)


def _load_faiss_map():
    import json
    map_path = os.path.join(os.path.dirname(settings.FAISS_INDEX_PATH), 'faiss_map.json')
    if not os.path.exists(map_path):
        return {}
    with open(map_path) as f:
        return {int(k): v for k, v in json.load(f).items()}


# ── Views ────────────────────────────────────────────────────────────────────

def home(request):
    student_count = Student.objects.filter(is_active=True).count()
    return render(request, 'enrollment/index.html', {'student_count': student_count})


def enroll_single(request):
    if request.method == 'POST':
        form = EnrollSingleForm(request.POST, request.FILES)
        if form.is_valid():
            app = get_face_app()
            d   = form.cleaned_data

            # Save student record (images saved by Django storage)
            student, created = Student.objects.get_or_create(
                student_id=d['student_id'],
                defaults={
                    'name':      d['name'],
                    'classroom': d['classroom'],
                    'roll_no':   d.get('roll_no', ''),
                }
            )
            if not created:
                student.name      = d['name']
                student.classroom = d['classroom']
                student.roll_no   = d.get('roll_no', '')

            for i, key in enumerate(['image1', 'image2', 'image3', 'image4'], 1):
                img_file = d.get(key)
                if img_file:
                    setattr(student, key, img_file)

            student.save()

            # Extract embeddings from uploaded photos
            embeddings = []
            for key in ['image1', 'image2', 'image3', 'image4']:
                img_field = getattr(student, key)
                if img_field:
                    emb = get_embedding(app, img_field.path)
                    if emb is not None:
                        embeddings.append(emb)

            if not embeddings:
                student.delete()
                messages.error(request, 'No faces detected in uploaded photos. Please try clearer photos.')
                return render(request, 'enrollment/enroll_single.html', {'form': form})

            avg = np.mean(embeddings, axis=0)
            avg /= (np.linalg.norm(avg) + 1e-8)
            student.face_encoding = avg.tobytes()
            student.save()

            _rebuild_faiss_index()

            messages.success(request, f"Enrolled {student.name} ({student.student_id}) with {len(embeddings)} photo(s).")
            return redirect('home')
    else:
        form = EnrollSingleForm()

    return render(request, 'enrollment/enroll_single.html', {'form': form})


def enroll_bulk(request):
    if request.method == 'POST':
        form = BulkEnrollForm(request.POST, request.FILES)
        if form.is_valid():
            import csv as csv_mod
            app       = get_face_app()
            classroom = form.cleaned_data['classroom']
            csv_file  = form.cleaned_data['csv_file']
            zip_file  = form.cleaned_data['photos_zip']

            # Parse CSV
            decoded = csv_file.read().decode('utf-8-sig')
            reader  = csv_mod.DictReader(io.StringIO(decoded))
            rows    = list(reader)

            # Extract ZIP to temp dir
            with tempfile.TemporaryDirectory() as tmp:
                with zipfile.ZipFile(zip_file) as zf:
                    zf.extractall(tmp)

                enrolled = 0
                failed   = []

                for row in rows:
                    sid  = str(row.get('student_id', '')).strip()
                    name = str(row.get('name', '')).strip()
                    roll = str(row.get('roll_no', '')).strip()

                    if not sid or not name:
                        continue

                    # Find photos named {sid}_1.jpg, {sid}_2.jpg …
                    photos = sorted([
                        os.path.join(tmp, f)
                        for f in os.listdir(tmp)
                        if f.startswith(sid + '_') and f.lower().endswith(('.jpg', '.jpeg', '.png'))
                    ])

                    # Also search one level deep (zip may have a subfolder)
                    if not photos:
                        for entry in os.scandir(tmp):
                            if entry.is_dir():
                                photos = sorted([
                                    os.path.join(entry.path, f)
                                    for f in os.listdir(entry.path)
                                    if f.startswith(sid + '_') and f.lower().endswith(('.jpg', '.jpeg', '.png'))
                                ])
                                if photos:
                                    break

                    if not photos:
                        failed.append(f"{sid} (no photos)")
                        continue

                    embeddings = []
                    for p in photos:
                        emb = get_embedding(app, p)
                        if emb is not None:
                            embeddings.append(emb)

                    if not embeddings:
                        failed.append(f"{sid} (no face detected)")
                        continue

                    avg = np.mean(embeddings, axis=0)
                    avg /= (np.linalg.norm(avg) + 1e-8)

                    student, _ = Student.objects.update_or_create(
                        student_id=sid,
                        defaults={
                            'name':          name,
                            'classroom':     classroom,
                            'roll_no':       roll,
                            'face_encoding': avg.tobytes(),
                            'is_active':     True,
                        }
                    )
                    enrolled += 1

                _rebuild_faiss_index()

            msg = f"Bulk enroll complete: {enrolled} enrolled."
            if failed:
                msg += f" Skipped {len(failed)}: {', '.join(failed[:5])}"
                if len(failed) > 5:
                    msg += f" … (+{len(failed)-5} more)"
            messages.success(request, msg)
            return redirect('home')
    else:
        form = BulkEnrollForm()

    return render(request, 'enrollment/enroll_bulk.html', {'form': form})


def rebuild_index(request):
    if request.method == 'POST':
        _rebuild_faiss_index()
        messages.success(request, 'FAISS index rebuilt successfully.')
    return redirect('home')


def webcam(request):
    return render(request, 'enrollment/webcam.html')


def recognize_image(request):
    """Ajax endpoint: receives a base64 webcam frame, returns JSON face matches."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    data = request.POST.get('image', '')
    if not data:
        return JsonResponse({'results': []})

    # Decode base64 → OpenCV image
    img_bytes  = base64.b64decode(data.split(',')[1])
    pil_img    = Image.open(io.BytesIO(img_bytes)).convert('RGB')
    frame      = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    app   = get_face_app()
    index = load_index(settings.FAISS_INDEX_PATH)
    id_map = _load_faiss_map()

    if index is None:
        return JsonResponse({'results': [], 'error': 'No enrolled students yet.'})

    match_threshold = settings.FRAS_CONFIG['recognition']['match_threshold']
    det_confidence  = settings.FRAS_CONFIG['recognition']['detection_confidence']

    faces, processed, scale = detect_faces(app, frame)
    results = []

    for face in faces:
        if face.det_score < det_confidence:
            continue
        if face.embedding is None:
            continue

        emb  = face.normed_embedding.astype(np.float32)
        sims, idxs = search(index, emb, k=1)
        sim  = float(sims[0])
        fidx = int(idxs[0])

        x1, y1, x2, y2 = face.bbox.astype(int)
        # Undo scale for original-image coordinates
        loc = [
            int(y1 / scale), int(x2 / scale),
            int(y2 / scale), int(x1 / scale),
        ]

        if (1 - sim) <= match_threshold:
            pk = id_map.get(fidx)
            try:
                student = Student.objects.get(pk=pk)
                name = student.name
                conf = round(sim * 100, 1)
            except Student.DoesNotExist:
                name, conf = 'Unknown', 0.0
        else:
            name, conf = 'Unknown', round(sim * 100, 1)

        results.append({'name': name, 'confidence': conf, 'location': loc})

    return JsonResponse({'results': results})
