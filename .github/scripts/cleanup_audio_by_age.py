#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ========== تنظیمات پیش‌فرض ==========
TIMES_FILE = Path("State/upload_times_Download_YoutubeDownloads.txt")
AUDIO_FOLDER = Path("Download/YoutubeDownloads")
DEFAULT_MAX_AGE_HOURS = 12
# =====================================


def parse_arguments():
    parser = argparse.ArgumentParser(description='حذف فایل‌های صوتی قدیمی بر اساس سن')
    parser.add_argument('--max-age', type=float, default=DEFAULT_MAX_AGE_HOURS,
                        help=f'حداکثر سن مجاز به ساعت (پیش‌فرض: {DEFAULT_MAX_AGE_HOURS})')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='فقط نمایش عملیات بدون حذف واقعی')
    return parser.parse_args()


def cleanup_old_audio(max_age_hours, dry_run):
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

    with open(TIMES_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    deleted_files = 0
    removed_records = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if " | " not in line:
            print(f"⚠️ فرمت نامعتبر (رد شد): {line[:50]}")
            removed_records += 1
            continue

        filename, time_str = line.split(" | ", 1)
        try:
            file_time = datetime.fromisoformat(time_str)
        except Exception as e:
            print(f"⚠️ زمان نامعتبر (رد شد): {line[:50]} - {e}")
            removed_records += 1
            continue

        age = now - file_time
        age_hours = age.total_seconds() / 3600
        file_path = AUDIO_FOLDER / filename

        if file_time < cutoff:
            # فایل قدیمی
            if not dry_run:
                if file_path.exists():
                    try:
                        os.remove(file_path)
                        print(f"🗑️ حذف فایل: {file_path} (سن: {age_hours:.1f} ساعت)")
                        deleted_files += 1
                    except Exception as e:
                        print(f"❌ خطا در حذف {file_path}: {e}")
                else:
                    print(f"⚠️ فایل از قبل وجود ندارد (حذف رکورد): {file_path}")
                removed_records += 1
            else:
                print(f"🔍 [DRY-RUN] حذف خواهد شد: {file_path} (سن: {age_hours:.1f} ساعت)")
                removed_records += 1
                if file_path.exists():
                    deleted_files += 1
        else:
            new_lines.append(line)
            print(f"⏳ نگهداری: {file_path} (سن: {age_hours:.1f} ساعت)")

    if not dry_run:
        # بکاپ و بازنویسی
        backup = TIMES_FILE.with_suffix(".txt.bak")
        TIMES_FILE.rename(backup)
        with open(TIMES_FILE, "w", encoding="utf-8") as f:
            for l in new_lines:
                f.write(l + "\n")
        backup.unlink()  # حذف بکاپ (اختیاری)
        print(f"📝 فایل زمان‌بندی به‌روز شد. {len(new_lines)} رکورد باقی ماند.")

    print("-" * 60)
    print("گزارش نهایی:")
    print(f"  - فایل‌های صوتی حذف شده: {deleted_files}")
    print(f"  - رکوردهای حذف شده: {removed_records}")
    print(f"  - رکوردهای باقی‌مانده: {len(new_lines)}")
    if dry_run:
        print("⚠️ حالت DRY_RUN فعال بود – هیچ تغییری واقعاً اعمال نشد.")
    else:
        print("✅ پاکسازی و به‌روزرسانی انجام شد.")
    print("=" * 60)


def main():
    args = parse_arguments()
    cleanup_old_audio(max_age_hours=args.max_age, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
