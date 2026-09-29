#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
پاکسازی فایل‌های صوتی قدیمی‌تر از N ساعت.

منطق مقاوم (برای جلوگیری از مشکلات قبلی):
1. اولویت با زمان ثبت‌شده در فایل times (اگر وجود داشته باشد)
2. اگر رکوردی نبود → از تاریخ آخرین کامیت گیت استفاده می‌شود
3. اگر آن هم نبود → mtime (فقط fallback محلی)
4. بعد از پاکسازی، فایل times همیشه با رکوردهای باقی‌مانده
   همگام می‌شود (حتی اگر قبلاً خالی شده باشد).
"""

import os
import sys
import argparse
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIMES_FILE = Path("State/upload_times_Download_YoutubeDownloads.txt")
AUDIO_FOLDER = Path("Download/YoutubeDownloads")
DEFAULT_MAX_AGE_HOURS = 12


def parse_arguments():
    parser = argparse.ArgumentParser(description='حذف فایل‌های صوتی قدیمی بر اساس سن')
    parser.add_argument('--max-age', type=float, default=DEFAULT_MAX_AGE_HOURS,
                        help=f'حداکثر سن مجاز به ساعت (پیش‌فرض: {DEFAULT_MAX_AGE_HOURS})')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='فقط نمایش عملیات بدون حذف واقعی')
    return parser.parse_args()


def get_git_commit_time(file_path: Path):
    """تاریخ آخرین کامیتی که این فایل را تغییر داده (UTC)."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", str(file_path)],
            capture_output=True, text=True, check=True
        )
        ts = result.stdout.strip()
        if ts:
            return datetime.fromisoformat(ts)
    except Exception as e:
        print(f"⚠️ نتوانست تاریخ گیت را برای {file_path} بگیرد: {e}")
    return None


def ensure_aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def cleanup_old_audio(max_age_hours, dry_run):
    print("=" * 60)
    print("پاکسازی فایل‌های صوتی قدیمی و همگام‌سازی رکوردها")
    print(f"زمان اجرا: {datetime.now(timezone.utc).isoformat()}")
    print(f"حداکثر سن مجاز: {max_age_hours} ساعت")
    print(f"حالت Dry-run: {dry_run}")
    print("=" * 60)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)

    # ---- 1) خواندن رکوردهای موجود ----
    recorded = {}
    if TIMES_FILE.exists():
        with open(TIMES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or " | " not in line:
                    continue
                filename, time_str = line.split(" | ", 1)
                try:
                    recorded[filename] = ensure_aware(datetime.fromisoformat(time_str))
                except Exception as e:
                    print(f"⚠️ زمان نامعتبر (رد شد): {line[:60]} - {e}")

    deleted_files = 0
    kept_records = []
    backfilled = 0

    # ---- 2) اسکن واقعی پوشه ----
    if not AUDIO_FOLDER.exists():
        print(f"⚠️ پوشه یافت نشد: {AUDIO_FOLDER}")
    else:
        for fname in sorted(os.listdir(AUDIO_FOLDER)):
            file_path = AUDIO_FOLDER / fname
            if not file_path.is_file():
                continue

            # اولویت: رکورد موجود → git → mtime
            file_time = recorded.get(fname)
            source = "times"

            if file_time is None:
                file_time = get_git_commit_time(file_path)
                source = "git"
                if file_time is not None:
                    backfilled += 1

            if file_time is None:
                try:
                    file_time = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
                    source = "mtime"
                except Exception as e:
                    print(f"❌ خطا در خواندن mtime {file_path}: {e}")
                    continue

            file_time = ensure_aware(file_time)
            age_hours = (now - file_time).total_seconds() / 3600

            if file_time < cutoff:
                if not dry_run:
                    try:
                        os.remove(file_path)
                        print(f"🗑️ حذف: {fname} (سن: {age_hours:.1f}h | منبع: {source} | {file_time.isoformat()})")
                        deleted_files += 1
                    except Exception as e:
                        print(f"❌ خطا در حذف {file_path}: {e}")
                else:
                    print(f"🔍 [DRY-RUN] حذف خواهد شد: {fname} (سن: {age_hours:.1f}h | منبع: {source})")
                    deleted_files += 1
            else:
                kept_records.append(f"{fname} | {file_time.isoformat()}")
                print(f"⏳ نگه: {fname} (سن: {age_hours:.1f}h | منبع: {source})")

    # ---- 3) همیشه فایل times را همگام کن ----
    if not dry_run:
        TIMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TIMES_FILE, "w", encoding="utf-8") as f:
            for rec in kept_records:
                f.write(rec + "\n")
        print(f"📝 فایل زمان‌بندی همگام شد → {len(kept_records)} رکورد")
        if backfilled:
            print(f"   (از این تعداد {backfilled} رکورد از تاریخ گیت پر شد)")

    print("-" * 60)
    print("گزارش نهایی:")
    print(f"  - فایل‌های حذف‌شده: {deleted_files}")
    print(f"  - رکوردهای باقی‌مانده: {len(kept_records)}")
    if dry_run:
        print("⚠️ DRY_RUN – هیچ تغییری اعمال نشد.")
    else:
        print("✅ پاکسازی و همگام‌سازی انجام شد.")
    print("=" * 60)


def main():
    args = parse_arguments()
    cleanup_old_audio(max_age_hours=args.max_age, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
