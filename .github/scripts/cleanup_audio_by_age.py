import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# مسیرهای دقیق بر اساس مخزن شما
TIMES_FILE = Path("State/upload_times_Download_audio_downloads.txt")
AUDIO_FOLDER = Path("Download/audio_download")

def cleanup_old_audio(max_age_hours: int = 12):
    if not TIMES_FILE.exists():
        print(f"⚠️ فایل زمان‌بندی یافت نشد: {TIMES_FILE}")
        return

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)

    with open(TIMES_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    deleted = 0
    for line in lines:
        line = line.strip()
        if not line or " | " not in line:
            continue

        filename, time_str = line.split(" | ", 1)
        try:
            file_time = datetime.fromisoformat(time_str)
            if file_time < cutoff:
                file_path = AUDIO_FOLDER / filename
                if file_path.exists():
                    os.remove(file_path)
                    print(f"🗑️ حذف شد: {file_path} (ثبت: {time_str})")
                    deleted += 1
                else:
                    print(f"⚠️ فایل موجود نیست: {file_path}")
        except Exception as e:
            print(f"❌ خطا در خط: {line[:50]}... - {e}")

    print(f"✅ {deleted} فایل حذف شدند.")

if __name__ == "__main__":
    cleanup_old_audio()
