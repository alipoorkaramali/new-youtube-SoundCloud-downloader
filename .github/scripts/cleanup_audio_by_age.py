#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
اسکریپت حذف فایل‌های صوتی قدیمی (بیش از ۱۲ ساعت)
بر اساس فایل زمان‌بندی ذخیره شده در State/upload_times_Download_audio_downloads.txt
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ========== تنظیمات ==========
# مسیر فایل زمان‌بندی (نسبت به ریشه مخزن)
TIMES_FILE = Path("State/upload_times_Download_audio_downloads.txt")

# مسیر پوشه حاوی فایل‌های صوتی
AUDIO_FOLDER = Path("Download/audio_download")

# حداکثر سن مجاز به ساعت (بیشتر از این مقدار حذف می‌شوند)
MAX_AGE_HOURS = 12

# حالت Dry-run: اگر True باشد، فقط نمایش می‌دهد و هیچ فایلی حذف نمی‌شود
DRY_RUN = False  # برای اجرای واقعی مقدار False بگذارید
# =============================


def cleanup_old_audio(max_age_hours=MAX_AGE_HOURS, dry_run=DRY_RUN):
    """
    حذف فایل‌های صوتی که سن آن‌ها بیشتر از max_age_hours ساعت است.
    
    Args:
        max_age_hours (int): حداکثر سن مجاز به ساعت
        dry_run (bool): اگر True باشد، فقط گزارش می‌دهد و حذف نمی‌کند
    """
    print("=" * 60)
    print("پاکسازی خودکار فایل‌های صوتی قدیمی")
    print(f"زمان اجرا: {datetime.now(timezone.utc).isoformat()}")
    print(f"حداکثر سن مجاز: {max_age_hours} ساعت")
    print(f"حالت Dry-run: {dry_run}")
    print("=" * 60)

    # بررسی وجود فایل زمان‌بندی
    if not TIMES_FILE.exists():
        print(f"⚠️ فایل زمان‌بندی یافت نشد: {TIMES_FILE}")
        print("   (هیچ فایلی برای پاکسازی وجود ندارد)")
        return

    # محاسبه زمان برش (cutoff): زمان فعلی منهای حداکثر سن
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    print(f"زمان حال (UTC): {now.isoformat()}")
    print(f"مرز سنی (UTC): {cutoff.isoformat()}")
    print("-" * 60)

    # خواندن فایل زمان‌بندی
    try:
        with open(TIMES_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"❌ خطا در خواندن فایل زمان‌بندی: {e}")
        return

    if not lines:
        print("⚠️ فایل زمان‌بندی خالی است.")
        return

    deleted_count = 0
    skipped_count = 0
    error_count = 0

    # پردازش هر خط
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue

        # جداسازی نام فایل و زمان با استفاده از جداکننده " | "
        if " | " not in line:
            print(f"⚠️ خط {line_num}: فرمت نامعتبر (بدون جداکننده ' | '): {line[:50]}")
            error_count += 1
            continue

        filename, time_str = line.split(" | ", 1)
        
        # اعتبارسنجی زمان
        try:
            file_time = datetime.fromisoformat(time_str)
        except Exception as e:
            print(f"⚠️ خط {line_num}: زمان نامعتبر '{time_str}' - {e}")
            error_count += 1
            continue

        # محاسبه سن فایل
        age = now - file_time
        age_hours = age.total_seconds() / 3600

        # ساخت مسیر کامل فایل
        file_path = AUDIO_FOLDER / filename

        # تصمیم‌گیری برای حذف یا نگهداری
        if file_time < cutoff:
            # فایل قدیمی‌تر از مرز سنی است
            if file_path.exists():
                if not dry_run:
                    try:
                        os.remove(file_path)
                        print(f"🗑️ حذف شد: {file_path} | سن: {age_hours:.1f} ساعت | ثبت: {time_str}")
                        deleted_count += 1
                    except Exception as e:
                        print(f"❌ خطا در حذف {file_path}: {e}")
                        error_count += 1
                else:
                    print(f"🔍 [DRY-RUN] حذف خواهد شد: {file_path} | سن: {age_hours:.1f} ساعت")
                    deleted_count += 1
            else:
                print(f"⚠️ فایل وجود ندارد (ممکن است قبلاً حذف شده باشد): {file_path}")
                skipped_count += 1
        else:
            # فایل جوان‌تر از مرز سنی است
            print(f"⏳ نگهداری: {file_path} | سن: {age_hours:.1f} ساعت | ثبت: {time_str}")
            skipped_count += 1

    # گزارش نهایی
    print("-" * 60)
    print("گزارش نهایی:")
    print(f"  - فایل‌های حذف شده (یا آماده حذف): {deleted_count}")
    print(f"  - فایل‌های نگهداری شده (جوان‌تر از {max_age_hours} ساعت): {skipped_count}")
    print(f"  - خطاها / خطوط نامعتبر: {error_count}")
    if dry_run:
        print("⚠️ حالت DRY_RUN فعال بود – هیچ فایلی واقعاً حذف نشد.")
    else:
        print("✅ پاکسازی با موفقیت انجام شد.")
    print("=" * 60)


def main():
    """نقطه ورودی اصلی"""
    # پشتیبانی از آرگومان خط فرمان برای تنظیم dry-run
    global DRY_RUN
    if len(sys.argv) > 1 and sys.argv[1].lower() in ["--dry-run", "-n"]:
        DRY_RUN = True
        print("🔧 حالت Dry-run از طریق آرگومان خط فرمان فعال شد.")
    
    cleanup_old_audio(max_age_hours=MAX_AGE_HOURS, dry_run=DRY_RUN)


if __name__ == "__main__":
    main()
