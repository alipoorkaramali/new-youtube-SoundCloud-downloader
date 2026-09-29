#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ثبت زمان آپلود فایل‌های جدید.

تغییر مهم (برای جلوگیری از مشکلات قبلی):
- برای فایل‌های جدید همیشه از datetime.now(UTC) استفاده می‌کنیم
  نه از mtime فایل‌سیستم.
  دلیل: در GitHub Actions بعد از checkout، mtime همه فایل‌ها
  به زمان checkout تبدیل می‌شود و سن واقعی از بین می‌رود.
- فقط فایل‌هایی که هنوز روی دیسک هستند نگه داشته می‌شوند.
"""

import sys
import os
from datetime import datetime, timezone

def main():
    if len(sys.argv) < 2:
        print("❌ خطا: پوشه مقصد مشخص نشده است.")
        sys.exit(1)

    folder = sys.argv[1].rstrip('/')
    safe_folder_name = folder.replace('/', '_')
    times_file = f"State/upload_times_{safe_folder_name}.txt"

    os.makedirs("State", exist_ok=True)

    # خواندن رکوردهای موجود
    existing = {}
    if os.path.exists(times_file):
        with open(times_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if " | " in line:
                    fname, time_str = line.split(" | ", 1)
                    existing[fname] = time_str

    now_iso = datetime.now(timezone.utc).isoformat()

    # پیدا کردن فایل‌های جدید و ثبت زمان فعلی (نه mtime)
    new_entries = []
    if os.path.isdir(folder):
        for fname in os.listdir(folder):
            if fname in existing:
                continue
            file_path = os.path.join(folder, fname)
            if os.path.isfile(file_path):
                new_entries.append(f"{fname} | {now_iso}")
                print(f"➕ ثبت جدید: {fname} @ {now_iso}")

    # بازنویسی: فقط رکوردهایی که فایلشان هنوز وجود دارد + رکوردهای جدید
    with open(times_file, "w", encoding="utf-8") as f:
        kept = 0
        for fname, t in existing.items():
            file_path = os.path.join(folder, fname)
            if os.path.isfile(file_path):
                f.write(f"{fname} | {t}\n")
                kept += 1
        for entry in new_entries:
            f.write(entry + "\n")

    print(f"✅ رکورد زمان برای پوشه '{folder}' به‌روز شد.")
    print(f"   - رکوردهای قبلی نگه داشته‌شده: {kept}")
    print(f"   - رکوردهای جدید: {len(new_entries)}")
    print(f"   - فایل: {times_file}")

if __name__ == "__main__":
    main()
