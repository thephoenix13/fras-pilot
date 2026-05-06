"""
Converts folder-based photo structure into FRAS enrollment format.

Expected input:
    - Excel file with columns: RollNo, StudentName (plus any other columns — ignored)
    - Photos folder with one subfolder per student named as: "{RollNo}-{name}"
      e.g. "254601-Dasari hari geetha lakshmi"
      Each subfolder contains 3 photos (any filename).

Output:
    data/enrollment/
        254601_1.jpg
        254601_2.jpg
        254601_3.jpg
        254602_1.jpg
        ...
    data/students.csv  (auto-generated with student_id, name, class, roll_no)

Usage:
    python src/prepare_photos.py --excel data/students.xlsx --photos data/photos
"""

import argparse
import os
import shutil

import pandas as pd


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def prepare(excel_path: str, photos_dir: str, output_dir: str, csv_path: str) -> None:
    # Load Excel
    df = pd.read_excel(excel_path)
    df.columns = [c.strip() for c in df.columns]

    if "RollNo" not in df.columns or "StudentName" not in df.columns:
        print(f"[error] Excel must have 'RollNo' and 'StudentName' columns.")
        print(f"        Found columns: {list(df.columns)}")
        return

    df["RollNo"] = df["RollNo"].astype(str).str.strip()
    df["StudentName"] = df["StudentName"].astype(str).str.strip()

    # Build a map: roll_no → student name from Excel
    student_map = {row["RollNo"]: row["StudentName"] for _, row in df.iterrows()}

    os.makedirs(output_dir, exist_ok=True)

    # Get all student folders — named as "{RollNo}-{name}"
    folders = [
        f for f in os.listdir(photos_dir)
        if os.path.isdir(os.path.join(photos_dir, f))
    ]

    records = []
    total_photos = 0
    skipped = []

    for folder in sorted(folders):
        # Extract roll number from folder name prefix (before first "-")
        parts = folder.split("-", 1)
        roll_no = parts[0].strip()

        if roll_no not in student_map:
            print(f"  [warn] Roll No {roll_no} not found in Excel — skipping folder '{folder}'")
            skipped.append(folder)
            continue

        student_name = student_map[roll_no]
        folder_path = os.path.join(photos_dir, folder)

        photos = sorted([
            f for f in os.listdir(folder_path)
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
        ])

        if not photos:
            print(f"  [warn] No photos in folder '{folder}' — skipping")
            skipped.append(folder)
            continue

        for photo_idx, photo_file in enumerate(photos, start=1):
            src = os.path.join(folder_path, photo_file)
            ext = os.path.splitext(photo_file)[1].lower()
            dst = os.path.join(output_dir, f"{roll_no}_{photo_idx}{ext}")
            shutil.copy2(src, dst)
            total_photos += 1

        records.append({
            "student_id": roll_no,
            "name": student_name,
            "class": "",
            "roll_no": roll_no,
        })

        print(f"  {roll_no} — {student_name} ({len(photos)} photos)")

    # Save CSV
    out_df = pd.DataFrame(records)
    out_df.to_csv(csv_path, index=False)

    print(f"\n[done] {len(records)} students prepared, {total_photos} photos copied.")
    print(f"       Photos → {output_dir}")
    print(f"       CSV    → {csv_path}")
    if skipped:
        print(f"[warn] Skipped {len(skipped)} folders: {skipped}")
    print(f"\nNext step — run enrollment:")
    print(f"  python src/enroll.py --csv {csv_path} --photos {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", default="data/students.xlsx", help="Excel file with RollNo and StudentName columns")
    parser.add_argument("--photos", default="data/photos", help="Folder containing one subfolder per student")
    parser.add_argument("--output", default="data/enrollment", help="Output folder for renamed photos")
    parser.add_argument("--csv", default="data/students.csv", help="Output CSV path")
    args = parser.parse_args()

    prepare(args.excel, args.photos, args.output, args.csv)
