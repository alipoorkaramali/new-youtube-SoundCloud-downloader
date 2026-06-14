#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
اسکریپت حذف فایل‌های صوتی قدیمی (بیش از ۱۲ ساعت) و حذف رکوردهای مربوطه
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ========== تنظیمات ==========
TIMES_FILE = Path("State/upload_times_Download_audio_downloads.txt")
AUDIO_FOLDER = Path("Download/audio_download")
MAX_AGE_HOURS = 12
DRY_RUN = False  # برای اجرای واقعی False بگذارید
# =============================


def cleanup_old_audio(max_age_hours=MAX_AGE_HOURS, dry_run=DRY_RUN):
    print("=" * 60)
    print("پاکسازی فایل‌های صوتی قدیمی و حذف رکوردها")
    print(f"زمان اجرا: {datetime.now(timezone.utc).isoformat()}")
    print(f"حداکثر سن مجاز: {max_age_hours} ساعت")
    print(f"حالت Dry-run: {dry_run}")
    print("=" * 60)

    if not TIMES_FILE.exists():
        print(f"⚠️ فایل زمان‌بندی یافت نشد: {TIMES_FILE}")
        return

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)

    # خواندن همه خطوط
    with open(TIMES_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []          # خطوطی که باید نگهداری شوند (فایل‌های جوان)
    deleted_count = 0
    removed_records_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if " | " not in line:
            print(f"⚠️ فرمت نامعتبر (رد شد): {line[:50]}")
            removed_records_count += 1
            continue

        filename, time_str = line.split(" | ", 1)
        try:
            file_time = datetime.fromisoformat(time_str)
        except Exception as e:
            print(f"⚠️ زمان نامعتبر (رد شد): {line[:50]} - {e}")
            removed_records_count += 1
            continue

        age = now - file_time
        age_hours = age.total_seconds() / 3600
        file_path = AUDIO_FOLDER / filename

        # تصمیم‌گیری
        if file_time < cutoff:
            # فایل قدیمی است → باید حذف شود (هم فایل صوتی، هم رکورد)
            if not dry_run:
                # حذف فایل صوتی اگر وجود داشته باشد
                if file_path.exists():
                    try:
                        os.remove(file_path)
                        print(f"🗑️ حذف فایل: {file_path} (سن: {age_hours:.1f} ساعت)")
                        deleted_count += 1
                    except Exception as e:
                        print(f"❌ خطا در حذف فایل {file_path}: {e}")
                        # حتی اگر حذف فایل خطا داد، باز هم رکورد را حذف می‌کنیم تا دوباره تلاش نکند
                else:
                    print(f"⚠️ فایل از قبل وجود ندارد (حذف رکورد): {file_path}")
                # رکورد را به new_lines اضافه نمی‌کنیم → حذف می‌شود
                removed_records_count += 1
            else:
                # حالت dry-run: فقط نمایش
                print(f"🔍 [DRY-RUN] حذف خواهد شد: فایل {file_path} و رکورد آن (سن: {age_hours:.1f} ساعت)")
                removed_records_count += 1
                if file_path.exists():
                    deleted_count += 1  # فقط برای آمار در dry-run
        else:
            # فایل جوان است → نگهداری فایل و رکورد
            new_lines.append(line)
            print(f"⏳ نگهداری: {file_path} (سن: {age_hours:.1f} ساعت)")

    # بازنویسی فایل زمان‌بندی با خطوط نگهداری شده (در صورت عدم dry-run)
    if not dry_run:
        # ابتدا یک بکاپ (اختیاری) - می‌توانید حذف کنید
        backup_file = TIMES_FILE.with_suffix(".txt.bak")
        TIMES_FILE.rename(backup_file)
        with open(TIMES_FILE, "w", encoding="utf-8") as f:
            f.writelines(line + "\n" for line in new_lines if line)
        print(f"📝 فایل زمان‌بندی به‌روزرسانی شد. {len(new_lines)} رکورد باقی ماند.")
        # حذف بکاپ (یا می‌توانید نگه دارید)
        if backup_file.exists():
            os.remove(backup_file)

    # گزارش نهایی
    print("-" * 60)
    print("گزارش نهایی:")
    print(f"  - فایل‌های صوتی حذف شده: {deleted_count}")
    print(f"  - رکوردهای حذف شده از فایل زمان‌بندی: {removed_records_count}")
    print(f"  - رکوردهای باقی‌مانده (فایل‌های جوان): {len(new_lines)}")
    if dry_run:
        print("⚠️ حالت DRY_RUN فعال بود – هیچ تغییری واقعاً اعمال نشد.")
    else:
        print("✅ پاکسازی و به‌روزرسانی فایل زمان‌بندی با موفقیت انجام شد.")
    print("=" * 60)


def main():
    global DRY_RUN
    if len(sys.argv) > 1 and sys.argv[1].lower() in ["--dry-run", "-n"]:
        DRY_RUN = True
        print("🔧 حالت Dry-run فعال شد.")
    cleanup_old_audio(max_age_hours=MAX_AGE_HOURS, dry_run=DRY_RUN)


if __name__ == "__main__":
    main()
