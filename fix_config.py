config = """camera:
  rtsp_url: "rtsp://admin:admin%40123@172.22.1.241:554/stream1"
  classroom_id: "CLASSROOM-122"
  frame_interval_seconds: 5
  capture_duration_seconds: 60

recognition:
  detection_confidence: 0.75
  match_threshold: 0.6
  min_frames_for_present: 2

paths:
  photos_dir: "data/photos"
  frames_dir: "data/frames"
  faiss_index: "db/faiss.index"
  student_db: "db/students.json"
  attendance_db: "db/fras.db"

dashboard:
  host: "0.0.0.0"
  port: 8000
"""

with open("config.yaml", "w", encoding="utf-8") as f:
    f.write(config)

print("config.yaml written successfully.")
