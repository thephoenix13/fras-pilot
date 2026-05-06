"""
Converts folder-based photo structure into FRAS enrollment format.

Input structure (what you have):
    data/photos/
        Rahul Sharma/
            photo1.jpg
            photo2.jpg
            photo3.jpg
        Priya Patel/
            photo1.jpg
            ...

Output:
    data/enrollment/
        STU001_1.jpg
        STU001_2.jpg
        STU001_3.jpg
        STU002_1.jpg
        ...
    data/students.csv  (auto-generated)

Usage:
    python src/prepare_photos.py
    python src/prepare_photos.py --photos data/photos --output data/enrollment --csv data/students.csv
"""

import argparse
import os
import shutil

import pandas as pd


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def prepare(photos_dir: str, output_dir: str, csv_path: str) -> None:
    os.makedirs(output_dir, exist_ok=True)

    student_folders = sorted([
        f for f in os.listdir(photos_dir)
        if os.path.isdir(os.path.join(photos_dir, f))
    ])

    if not student_folders:
        print(f"[error] No subfolders found in {photos_dir}")
        print("        Expected one folder per student named after the student.")
        return

    records = []
    total_photos = 0

    for idx, student_name in enumerate(student_folders, start=1):
        student_id = f"STU{idx:03d}"
        folder_path = os.path.join(photos_dir, student_name)

        photos = sorted([
            f for f in os.listdir(folder_path)
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
        ])

        if not photos:
            print(f"  [warn] No photos found for {student_name} — skipping")
            continue

        for photo_idx, photo_file in enumerate(photos, start=1):
            src = os.path.join(folder_path, photo_file)
            ext = os.path.splitext(photo_file)[1].lower()
            dst = os.path.join(output_dir, f"{student_id}_{photo_idx}{ext}")
            shutil.copy2(src, dst)
            total_photos += 1

        records.append({
            "student_id": student_id,
            "name": student_name,
            "class": "",
            "roll_no": idx,
        })

        print(f"  {student_id} — {student_name} ({len(photos)} photos)")

    df = pd.DataFrame(records)
    df.to_csv(csv_path, index=False)

    print(f"\n[done] {len(records)} students prepared, {total_photos} photos copied.")
    print(f"       Photos  → {output_dir}")
    print(f"       CSV     → {csv_path}")
    print(f"\nNext step — run enrollment:")
    print(f"  python src/enroll.py --csv {csv_path} --photos {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--photos", default="data/photos", help="Folder containing one subfolder per student")
    parser.add_argument("--output", default="data/enrollment", help="Output folder for renamed photos")
    parser.add_argument("--csv", default="data/students.csv", help="Output CSV path")
    args = parser.parse_args()

    prepare(args.photos, args.output, args.csv)
