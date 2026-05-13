import os
import time
from datetime import datetime, timedelta, timezone

def cleanup(folder):
    safe_name = folder.replace('/', '_')
    times_file = f"upload_times_{safe_name}.txt"
    if not os.path.exists(times_file):
        print("هیچ فایل رکوردی یافت نشد.")
        return

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    with open(times_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    to_delete = []
    for line in lines:
        line = line.strip()
        if not line or " | " not in line:
            continue
        fname, time_str = line.split(" | ", 1)
        try:
            file_time = datetime.fromisoformat(time_str)
            if file_time < cutoff:
                file_path = os.path.join(folder, fname)
                if os.path.exists(file_path):
                    to_delete.append(file_path)
        except:
            pass

    for path in to_delete:
        os.remove(path)
        print(f"🗑️ حذف فایل قدیمی: {path}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cleanup(sys.argv[1])
    else:
        print("لطفاً پوشه را وارد کنید.")
