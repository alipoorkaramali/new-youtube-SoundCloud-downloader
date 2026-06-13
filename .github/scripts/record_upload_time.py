import sys
import os
from datetime import datetime, timezone

def main():
    if len(sys.argv) < 2:
        print("❌ خطا: پوشه مقصد مشخص نشده است.")
        sys.exit(1)

    folder = sys.argv[1].rstrip('/')  # حذف اسلش اضافی
    # نام فایل رکورد بر اساس نام پوشه (با جایگزینی / با _)
    safe_folder_name = folder.replace('/', '_')
    times_file = f"upload_times_{safe_folder_name}.txt"

    # خواندن رکوردهای موجود برای این پوشه
    existing = {}
    if os.path.exists(times_file):
        with open(times_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if " | " in line:
                    fname, time_str = line.split(" | ", 1)
                    existing[fname] = time_str

    # اضافه کردن فایل‌های جدید در این پوشه
    new_entries = []
    if os.path.isdir(folder):
        for fname in os.listdir(folder):
            if fname in existing:
                continue
            file_path = os.path.join(folder, fname)
            if os.path.isfile(file_path):
                mtime = os.path.getmtime(file_path)
                file_time = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                new_entries.append(f"{fname} | {file_time}")

    # بازنویسی فایل رکورد مخصوص این پوشه: نگهداری همه رکوردهایی که فایلشان هنوز وجود دارد
    with open(times_file, "w", encoding="utf-8") as f:
        for fname, t in existing.items():
            file_path = os.path.join(folder, fname)
            if os.path.isfile(file_path):
                f.write(f"{fname} | {t}\n")
        for entry in new_entries:
            f.write(entry + "\n")

    print(f"✅ رکورد زمان برای پوشه '{folder}' در فایل '{times_file}' به‌روز شد.")

if __name__ == "__main__":
    main()
