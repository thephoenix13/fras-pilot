import base64
import os
import time
from io import BytesIO
import cv2
import numpy as np
from PIL import Image
from insightface.app import FaceAnalysis
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from .models import Student


uploads_dir = 'uploads'

# ============================================================
#  CONFIG — TUNED FOR CLASSROOM CCTV
# ============================================================
MIN_FACE_SIZE = 20             # Skip tiny artifacts
DUPLICATE_TOLERANCE = 0.75     # Cosine distance threshold (higher = more dedup)
FACE_OUTPUT_SIZE = (200, 200)  # Cropped face output size
MIN_DET_SCORE = 0.75           # Skip low confidence (tops of heads, blur)
EMBEDDING_UPDATE_WEIGHT = 0.3  # How much new embedding updates running average

# ============================================================
#  INSIGHTFACE INITIALIZATION
# ============================================================
log_init_time = time.strftime("%H:%M:%S")
print(f"[FRAS {log_init_time}] Loading InsightFace model (RetinaFace + ArcFace)...")
_start = time.time()

face_app = FaceAnalysis(
    name='buffalo_l',
    providers=['CPUExecutionProvider']
)
face_app.prepare(ctx_id=0, det_size=(640, 640))

print(f"[FRAS {time.strftime('%H:%M:%S')}] InsightFace loaded in {time.time()-_start:.2f}s")
print(f"[FRAS {time.strftime('%H:%M:%S')}] Detection: RetinaFace | Recognition: ArcFace (512-d)")
print(f"[FRAS {time.strftime('%H:%M:%S')}] Config: min_score={MIN_DET_SCORE}, dup_tolerance={DUPLICATE_TOLERANCE}, emb_weight={EMBEDDING_UPDATE_WEIGHT}")


def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[FRAS {timestamp}] {msg}")


def index(request):
    log("Homepage loaded")
    return render(request, 'index.html')


def ensure_dir(file_path):
    if not os.path.exists(file_path):
        os.makedirs(file_path)
        log(f"Created directory: {file_path}")


# ============================================================
#  CORE: INSIGHTFACE DETECTION
# ============================================================

def detect_faces_insightface(image, det_size=None):
    """
    Detect faces using InsightFace (RetinaFace + ArcFace).
    Returns list of face objects with bbox, embedding, det_score, landmark.
    """
    h, w = image.shape[:2]
    log(f"  InsightFace detecting in {w}x{h} image...")

    # For small CCTV images, upscale for better detection
    scale = 1.0
    if w < 800 or h < 600:
        scale = max(1280 / w, 960 / h)
        scale = min(scale, 3.0)
        new_w, new_h = int(w * scale), int(h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        log(f"  Upscaled: {w}x{h} -> {new_w}x{new_h} ({scale:.1f}x)")

    start = time.time()
    faces = face_app.get(image)
    detect_time = time.time() - start

    log(f"  Found {len(faces)} face(s) in {detect_time:.2f}s")

    # Sort by x position (left to right)
    faces = sorted(faces, key=lambda f: f.bbox[0])

    for i, face in enumerate(faces):
        x1, y1, x2, y2 = face.bbox.astype(int)
        fw, fh = x2 - x1, y2 - y1
        score = face.det_score
        has_emb = face.embedding is not None
        log(f"    Face #{i+1}: pos=({x1},{y1})-({x2},{y2}) size={fw}x{fh}px score={score:.3f} emb={'Yes' if has_emb else 'No'}")

    return faces, image, scale


def crop_face_from_bbox(image, bbox, padding=0.3):
    """Crop face using InsightFace bbox with padding."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox.astype(int)
    face_h = y2 - y1
    pad = int(face_h * padding)

    top = max(0, y1 - pad)
    bottom = min(h, y2 + pad)
    left = max(0, x1 - pad)
    right = min(w, x2 + pad)

    face_image = image[top:bottom, left:right]
    crop_h, crop_w = face_image.shape[:2]
    log(f"    Cropped: ({left},{top})-({right},{bottom}) = {crop_w}x{crop_h}px + {pad}px pad")
    face_image = cv2.resize(face_image, FACE_OUTPUT_SIZE, interpolation=cv2.INTER_CUBIC)
    return face_image


def cosine_distance(emb1, emb2):
    """Calculate cosine distance between two embeddings."""
    sim = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
    return 1.0 - sim


def update_embedding(old_emb, new_emb, weight=EMBEDDING_UPDATE_WEIGHT):
    """
    Running average: blend new embedding into existing one.
    This makes the stored embedding more robust over time as we see
    the same face from different angles across frames.
    """
    updated = (1 - weight) * old_emb + weight * new_emb
    # Normalize to unit vector
    updated = updated / np.linalg.norm(updated)
    return updated


# ============================================================
#  VIDEO / IMAGE FACE RECOGNITION
# ============================================================

def videofacerecog(request):
    if request.method == 'POST':
        file = request.FILES['media']
        file_size_mb = file.size / (1024 * 1024)

        log("=" * 50)
        log("FILE UPLOAD RECEIVED")
        log(f"  Name: {file.name}")
        log(f"  Type: {file.content_type}")
        log(f"  Size: {file_size_mb:.2f} MB")
        log("=" * 50)

        fs = FileSystemStorage()
        filename = fs.save(file.name, file)
        uploaded_file_url = fs.url(filename)
        media_path = fs.path(filename)
        log(f"  Saved to: {media_path}")

        ensure_dir(os.path.join(settings.MEDIA_ROOT, uploads_dir))

        # ---- IMAGE ----
        if 'image' in file.content_type:
            log("-" * 40)
            log("IMAGE PROCESSING START")
            log("-" * 40)
            total_start = time.time()

            image = cv2.imread(media_path)
            if image is None:
                log("ERROR: Could not read image!")
                return render(request, 'videofacerecog.html', {'error': 'Could not read image'})

            orig_h, orig_w = image.shape[:2]
            log(f"  Original size: {orig_w}x{orig_h}")

            faces, processed_img, scale = detect_faces_insightface(image)

            face_files = []
            skipped = 0
            skipped_score = 0
            for i, face in enumerate(faces):
                x1, y1, x2, y2 = face.bbox.astype(int)
                fw, fh = x2 - x1, y2 - y1

                if face.det_score < MIN_DET_SCORE:
                    log(f"    Face #{i+1}: SKIPPED (low score {face.det_score:.3f} < {MIN_DET_SCORE})")
                    skipped_score += 1
                    continue

                if fw < MIN_FACE_SIZE or fh < MIN_FACE_SIZE:
                    log(f"    Face #{i+1}: SKIPPED (too small {fw}x{fh}px)")
                    skipped += 1
                    continue

                face_crop = crop_face_from_bbox(processed_img, face.bbox)

                face_save_name = f"{filename}-face{i+1}.jpg"
                face_file_path = os.path.join(settings.MEDIA_ROOT, uploads_dir, face_save_name)
                cv2.imwrite(face_file_path, face_crop)
                face_files.append(fs.url(os.path.join(uploads_dir, face_save_name)))
                log(f"    Face #{i+1}: SAVED -> {face_save_name} (score={face.det_score:.3f})")

            total_time = time.time() - total_start
            log("-" * 40)
            log("IMAGE PROCESSING COMPLETE")
            log(f"  Total detected: {len(faces)}")
            log(f"  Saved: {len(face_files)}")
            log(f"  Skipped (too small): {skipped}")
            log(f"  Skipped (low score): {skipped_score}")
            log(f"  Time: {total_time:.2f}s")
            log("=" * 50)

            return render(request, 'show_faces.html', {
                'original_image': uploaded_file_url,
                'faces': face_files,
                'face_count': len(face_files),
            })

        # ---- VIDEO ----
        elif 'video' in file.content_type:
            log("-" * 40)
            log("VIDEO PROCESSING START")
            log("-" * 40)
            total_start = time.time()

            face_files = extract_and_save_unique_faces(media_path)
            face_files_urls = [
                fs.url(os.path.join(uploads_dir, face_file))
                for face_file in face_files
            ]

            total_time = time.time() - total_start
            log("-" * 40)
            log("VIDEO PROCESSING COMPLETE")
            log(f"  Total unique faces: {len(face_files)}")
            log(f"  Total time: {total_time:.2f}s")
            log("=" * 50)

            return render(request, 'show_faces.html', {
                'original_video': uploaded_file_url,
                'faces': face_files_urls,
                'face_count': len(face_files_urls),
            })

    return render(request, 'videofacerecog.html')


def extract_and_save_unique_faces(video_path):
    """Extract unique faces from video using InsightFace with smart deduplication."""
    overall_start = time.time()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log("ERROR: Could not open video file!")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames_per_two_seconds = int(fps * 2)
    total_samples = max(1, int(total_frames / frames_per_two_seconds) + 1)

    log(f"  Video info:")
    log(f"    Resolution: {width}x{height}")
    log(f"    FPS: {fps:.1f}")
    log(f"    Total frames: {total_frames}")
    log(f"    Duration: {duration:.1f}s ({duration/60:.1f} min)")
    log(f"    Sampling every 2s -> {total_samples} frames to process")
    log(f"    Min det score: {MIN_DET_SCORE}")
    log(f"    Dup tolerance: {DUPLICATE_TOLERANCE}")
    log(f"    Embedding update weight: {EMBEDDING_UPDATE_WEIGHT}")
    log("")

    saved_faces = []
    saved_face_files = []
    face_embeddings_list = []
    face_best_scores = []
    face_seen_count = []        # How many times each face was seen across frames
    two_second_count = 0
    total_faces_seen = 0
    total_skipped_small = 0
    total_skipped_duplicate = 0
    total_skipped_no_emb = 0
    total_skipped_low_score = 0

    # Timing breakdown
    time_reading = 0.0
    time_detection = 0.0
    time_matching = 0.0
    time_cropping = 0.0

    while True:
        frame_index = two_second_count * frames_per_two_seconds
        if frame_index >= total_frames:
            break

        t_read_start = time.time()
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = cap.read()
        time_reading += time.time() - t_read_start

        if not ret:
            log(f"  Frame #{two_second_count+1}: READ FAILED, stopping")
            break

        current_time = frame_index / fps
        progress = ((two_second_count + 1) / total_samples) * 100
        log(f"  --- Frame #{two_second_count+1}/{total_samples} | time={current_time:.1f}s | progress={progress:.0f}% ---")

        t_det_start = time.time()
        faces, processed_frame, scale = detect_faces_insightface(frame)
        time_detection += time.time() - t_det_start

        frame_new = 0
        frame_dup = 0
        frame_small = 0

        for face in faces:
            total_faces_seen += 1
            x1, y1, x2, y2 = face.bbox.astype(int)
            fw, fh = x2 - x1, y2 - y1

            # Skip low confidence detections
            if face.det_score < MIN_DET_SCORE:
                log(f"    -> SKIP: low score ({face.det_score:.3f} < {MIN_DET_SCORE})")
                total_skipped_low_score += 1
                continue

            # Skip small faces
            if fw < MIN_FACE_SIZE or fh < MIN_FACE_SIZE:
                log(f"    -> SKIP: too small ({fw}x{fh}px)")
                frame_small += 1
                total_skipped_small += 1
                continue

            # Check embedding exists
            if face.embedding is None:
                log(f"    -> SKIP: no embedding generated")
                total_skipped_no_emb += 1
                continue

            # Check for duplicates using cosine distance
            t_match_start = time.time()
            is_duplicate = False
            if face_embeddings_list:
                distances = [cosine_distance(face.embedding, emb) for emb in face_embeddings_list]
                best_distance = min(distances)
                best_match_idx = distances.index(best_distance)

                if best_distance < DUPLICATE_TOLERANCE:
                    is_duplicate = True
                    face_seen_count[best_match_idx] += 1

                    # Update embedding with running average (makes matching better over time)
                    face_embeddings_list[best_match_idx] = update_embedding(
                        face_embeddings_list[best_match_idx],
                        face.embedding
                    )

                    # If better score, update the saved crop
                    if face.det_score > face_best_scores[best_match_idx]:
                        old_score = face_best_scores[best_match_idx]
                        face_best_scores[best_match_idx] = face.det_score

                        t_crop_start = time.time()
                        face_crop = crop_face_from_bbox(processed_frame, face.bbox)
                        face_filename = saved_face_files[best_match_idx]
                        face_path = os.path.join(settings.MEDIA_ROOT, uploads_dir, face_filename)
                        cv2.imwrite(face_path, face_crop)
                        time_cropping += time.time() - t_crop_start
                        log(f"    -> DUPLICATE of face #{best_match_idx+1} (dist={best_distance:.3f}) — UPGRADED score {old_score:.3f} -> {face.det_score:.3f} [seen {face_seen_count[best_match_idx]}x]")
                    else:
                        log(f"    -> DUPLICATE: matches face #{best_match_idx+1} (dist={best_distance:.3f}) [seen {face_seen_count[best_match_idx]}x]")

                    frame_dup += 1
                    total_skipped_duplicate += 1

            time_matching += time.time() - t_match_start

            if is_duplicate:
                continue

            # New unique face
            t_crop_start = time.time()
            face_embeddings_list.append(face.embedding.copy())
            face_best_scores.append(face.det_score)
            face_seen_count.append(1)
            face_crop = crop_face_from_bbox(processed_frame, face.bbox)

            face_filename = f"unique_face_{len(face_embeddings_list)}.jpg"
            face_path = os.path.join(settings.MEDIA_ROOT, uploads_dir, face_filename)
            cv2.imwrite(face_path, face_crop)
            saved_faces.append(face_filename)
            saved_face_files.append(face_filename)
            time_cropping += time.time() - t_crop_start
            frame_new += 1
            log(f"    -> NEW FACE #{len(face_embeddings_list)}: {face_filename} ({fw}x{fh}px, score={face.det_score:.3f})")

        log(f"  Frame result: {len(faces)} detected | {frame_new} new | {frame_dup} dup | {frame_small} small")
        log(f"  Running total: {len(saved_faces)} unique faces")
        log("")

        two_second_count += 1

    cap.release()
    overall_time = time.time() - overall_start

    # ============================================================
    #  DETAILED SUMMARY WITH ACCURACY & TIMING
    # ============================================================
    log("")
    log("=" * 60)
    log("  FRAS VIDEO EXTRACTION — FULL REPORT")
    log("=" * 60)

    # Video info
    log(f"  VIDEO:")
    log(f"    Resolution:          {width}x{height}")
    log(f"    Duration:            {duration:.1f}s ({duration/60:.1f} min)")
    log(f"    FPS:                 {fps:.1f}")
    log(f"    Frames sampled:      {two_second_count} (every 2s)")
    log("")

    # Detection stats
    log(f"  DETECTION:")
    log(f"    Total detections:    {total_faces_seen}")
    log(f"    Avg per frame:       {total_faces_seen/max(two_second_count,1):.1f}")
    log(f"    Passed score filter: {total_faces_seen - total_skipped_low_score} ({((total_faces_seen - total_skipped_low_score)/max(total_faces_seen,1)*100):.0f}%)")
    log(f"    Skipped low score:   {total_skipped_low_score} ({(total_skipped_low_score/max(total_faces_seen,1)*100):.0f}%)")
    log(f"    Skipped too small:   {total_skipped_small}")
    log(f"    Skipped no embed:    {total_skipped_no_emb}")
    log("")

    # Deduplication stats
    valid_detections = total_faces_seen - total_skipped_low_score - total_skipped_small - total_skipped_no_emb
    log(f"  DEDUPLICATION:")
    log(f"    Valid detections:    {valid_detections}")
    log(f"    Duplicates caught:   {total_skipped_duplicate} ({(total_skipped_duplicate/max(valid_detections,1)*100):.0f}%)")
    log(f"    Unique faces saved:  {len(saved_faces)}")
    log(f"    Dedup efficiency:    {(total_skipped_duplicate/max(valid_detections,1)*100):.1f}%")
    log("")

    # Face quality breakdown
    if face_best_scores:
        high_conf = sum(1 for s in face_best_scores if s >= 0.85)
        med_conf = sum(1 for s in face_best_scores if 0.75 <= s < 0.85)
        low_conf = sum(1 for s in face_best_scores if s < 0.75)
        log(f"  FACE QUALITY:")
        log(f"    High confidence (>0.85): {high_conf} faces")
        log(f"    Med confidence (0.75-0.85): {med_conf} faces")
        log(f"    Low confidence (<0.75):  {low_conf} faces")
        log(f"    Avg best score:          {np.mean(face_best_scores):.3f}")
        log(f"    Max score:               {max(face_best_scores):.3f}")
        log(f"    Min score:               {min(face_best_scores):.3f}")
        log("")

    # Face sighting frequency
    if face_seen_count:
        log(f"  FACE SIGHTING FREQUENCY:")
        for i, count in enumerate(face_seen_count):
            stability = "STABLE" if count >= 5 else "MODERATE" if count >= 3 else "RARE"
            log(f"    Face #{i+1}: seen {count}x across frames — {stability} (score={face_best_scores[i]:.3f})")
        log("")
        seen_5plus = sum(1 for c in face_seen_count if c >= 5)
        seen_3plus = sum(1 for c in face_seen_count if c >= 3)
        seen_once = sum(1 for c in face_seen_count if c == 1)
        log(f"    Seen 5+ frames (STABLE):   {seen_5plus}")
        log(f"    Seen 3+ frames (MODERATE+): {seen_3plus}")
        log(f"    Seen only 1 frame (RARE):   {seen_once}")
        log(f"    -> Likely real students:     ~{seen_3plus} (seen 3+ times)")
        log(f"    -> Likely duplicates/noise:  ~{seen_once} (seen only once)")
        log("")

    # Timing breakdown
    time_other = overall_time - time_reading - time_detection - time_matching - time_cropping
    log(f"  TIMING:")
    log(f"    Total time:          {overall_time:.2f}s")
    log(f"    Frame reading:       {time_reading:.2f}s ({time_reading/overall_time*100:.0f}%)")
    log(f"    Face detection:      {time_detection:.2f}s ({time_detection/overall_time*100:.0f}%)")
    log(f"    Embedding matching:  {time_matching:.2f}s ({time_matching/overall_time*100:.0f}%)")
    log(f"    Face cropping/save:  {time_cropping:.2f}s ({time_cropping/overall_time*100:.0f}%)")
    log(f"    Other overhead:      {time_other:.2f}s ({time_other/overall_time*100:.0f}%)")
    log(f"    Avg per frame:       {overall_time/max(two_second_count,1):.2f}s")
    log(f"    Processing speed:    {duration/overall_time:.1f}x realtime")
    log("")

    # Final accuracy estimate
    log(f"  ACCURACY ESTIMATE:")
    log(f"    Unique faces output: {len(saved_faces)}")
    log(f"    Reliable faces (3+ sightings): {seen_3plus if face_seen_count else 0}")
    log(f"    System dedup rate:   {(total_skipped_duplicate/max(valid_detections,1)*100):.1f}%")
    if face_seen_count:
        log(f"    Suggested real count: ~{seen_3plus} students")
        log(f"    Noise/edge faces:     ~{len(saved_faces) - seen_3plus}")
    log("=" * 60)

    return saved_faces


# ============================================================
#  STUDENT UPLOAD
# ============================================================

def upload_images(request):
    if request.method == 'POST':
        name       = request.POST['name']
        student_id = request.POST.get('student_id', '').strip()
        classroom  = request.POST.get('classroom', '').strip()
        roll_no    = request.POST.get('roll_no', '').strip()

        log("=" * 50)
        log(f"STUDENT UPLOAD: '{name}' (id={student_id or '-'}, "
            f"class={classroom or '-'}, roll={roll_no or '-'})")
        log("=" * 50)

        image1 = request.FILES['image1']
        image2 = request.FILES['image2']
        image3 = request.FILES['image3']
        image4 = request.FILES['image4']

        log("Photos received:")
        for i, img in enumerate([image1, image2, image3, image4], 1):
            log(f"  {i}. {img.name} ({img.size/1024:.1f} KB)")

        student = Student(
            name=name, image1=image1, image2=image2,
            image3=image3, image4=image4,
            student_id=student_id, classroom=classroom,
            roll_no=roll_no, is_active=True,
        )
        student.save()
        log(f"Student record created (ID: {student.id})")

        image_paths = [
            student.image1.path, student.image2.path,
            student.image3.path, student.image4.path
        ]
        embeddings = []

        for i, path in enumerate(image_paths, 1):
            log(f"Processing photo {i}/4: {os.path.basename(path)}")
            image = cv2.imread(path)
            if image is None:
                log(f"  -> ERROR: Could not read image!")
                continue

            h, w = image.shape[:2]
            log(f"  Size: {w}x{h}")

            if w < 400 or h < 400:
                sc = min(640 / max(w, h), 3.0)
                new_w, new_h = int(w * sc), int(h * sc)
                image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
                log(f"  Upscaled to: {new_w}x{new_h}")

            faces = face_app.get(image)
            if faces:
                best_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                if best_face.embedding is not None:
                    embeddings.append(best_face.embedding)
                    log(f"  -> Face found! Embedding (512-d, score={best_face.det_score:.3f})")
                else:
                    log(f"  -> WARNING: Face detected but no embedding!")
            else:
                log(f"  -> WARNING: No face detected!")

        log(f"Embeddings: {len(embeddings)}/4 successful")

        if embeddings:
            combined_embedding = np.mean(embeddings, axis=0)
            combined_embedding = combined_embedding / np.linalg.norm(combined_embedding)
            # Always store as float32 — recognize_image reads as float32, must match.
            student.face_encoding = combined_embedding.astype(np.float32).tobytes()
            student.save()
            log(f"Combined 512-d embedding saved for '{name}'")
            log(f"STUDENT UPLOAD COMPLETE")
            log("=" * 50)
            return render(request, 'upload.html', {'success': True})
        else:
            student.delete()
            log(f"STUDENT UPLOAD FAILED: No faces in any photo, record deleted")
            log("=" * 50)
            return render(request, 'upload.html', {
                'error': 'No faces detected in uploaded images. Please try clearer photos.'
            })

    return render(request, 'upload.html')


# ============================================================
#  WEBCAM RECOGNITION
# ============================================================

def webcam_template(request):
    log("Webcam page loaded")
    return render(request, 'webcam.html')


def recognize_image(request):
    if request.method == 'POST':
        log("=" * 50)
        log("WEBCAM RECOGNITION")
        log("=" * 50)
        start = time.time()

        data = request.POST.get('image')
        image_data = base64.b64decode(data.split(',')[1])
        pil_image = Image.open(BytesIO(image_data)).convert('RGB')
        image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        h, w = image.shape[:2]
        log(f"  Image received: {w}x{h}")

        students = Student.objects.all()
        student_count = students.count()
        log(f"  Students in DB: {student_count}")

        if not students.exists():
            log("  WARNING: No students registered!")
            return JsonResponse({"results": [], "error": "No students registered yet."})

        known_embeddings = []
        known_names = []
        for student in students:
            if student.face_encoding:
                emb = np.frombuffer(student.face_encoding, dtype=np.float32)
                if len(emb) == 512:
                    known_embeddings.append(emb)
                    known_names.append(student.name)
                else:
                    log(f"  Skipping '{student.name}': unexpected embedding length {len(emb)}, needs re-registration")

        log(f"  Loaded {len(known_embeddings)} embeddings for matching")

        faces, processed_img, scale = detect_faces_insightface(image)

        results = []
        for i, face in enumerate(faces):
            name = "Unknown"
            confidence = 0.0
            x1, y1, x2, y2 = face.bbox.astype(int)

            if face.det_score < MIN_DET_SCORE:
                continue

            if face.embedding is not None and known_embeddings:
                distances = [cosine_distance(face.embedding, emb) for emb in known_embeddings]
                best_distance = min(distances)
                best_match_idx = distances.index(best_distance)

                if best_distance < DUPLICATE_TOLERANCE:
                    name = known_names[best_match_idx]
                    confidence = round((1 - best_distance) * 100, 1)
                    log(f"  Face #{i+1}: MATCH '{name}' ({confidence}%, dist={best_distance:.3f})")
                else:
                    log(f"  Face #{i+1}: UNKNOWN (closest='{known_names[best_match_idx]}', dist={best_distance:.3f})")
            elif not known_embeddings:
                log(f"  Face #{i+1}: UNKNOWN (no embeddings to match)")
            else:
                log(f"  Face #{i+1}: UNKNOWN (no embedding generated)")

            loc_top = int(y1 / scale) if scale > 1 else y1
            loc_right = int(x2 / scale) if scale > 1 else x2
            loc_bottom = int(y2 / scale) if scale > 1 else y2
            loc_left = int(x1 / scale) if scale > 1 else x1

            results.append({
                "name": name,
                "confidence": confidence,
                "location": [loc_top, loc_right, loc_bottom, loc_left]
            })

        total_time = time.time() - start
        log(f"  Done: {len(results)} face(s) in {total_time:.2f}s")
        log("=" * 50)

        return JsonResponse({"results": results})

    return HttpResponse("Only POST method is allowed")


def get_encodings(request):
    students = Student.objects.all()
    count = students.count()
    log(f"Encodings API called. Students: {count}")
    encodings = {}
    for student in students:
        if student.face_encoding:
            emb = np.frombuffer(student.face_encoding, dtype=np.float32)
            encodings[student.name] = emb.tolist()
    return JsonResponse(encodings)