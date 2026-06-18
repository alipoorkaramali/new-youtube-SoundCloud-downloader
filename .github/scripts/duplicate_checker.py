#!/usr/bin/env python3
import os
import json
import sys
from datetime import datetime, timezone, timedelta

STATE_FILE = "State/downloaded_items.json"
IRAN_OFFSET = timedelta(hours=3, minutes=30)

def iran_now():
    return datetime.now(timezone.utc) + IRAN_OFFSET

def load_state():
    """بارگذاری لیست آیتم‌های دانلود شده"""
    if not os.path.exists(STATE_FILE):
        return []
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ خطا در خواندن فایل State: {e}")
        return []

def save_state(items):
    """ذخیره لیست آیتم‌های دانلود شده"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ خطا در ذخیره State: {e}")

def is_duplicate(keyword, platform, url):
    """بررسی تکراری بودن"""
    if not url:
        return True, "لینک (URL) ارسال نشده است"

    today = str(iran_now().date())
    items = load_state()

    # ۱. چک تکراری بر اساس لینک (مهم‌ترین و مطمئن‌ترین روش)
    for item in items:
        if item.get('url') == url:
            return True, "لینک قبلاً دانلود شده است"

    # ۲. چک بر اساس keyword + تاریخ (اگر keyword وجود داشت)
    if keyword and keyword.strip():
        for item in items:
            if (item.get('keyword') == keyword and 
                item.get('date') == today):
                
                # اولویت SoundCloud
                if platform == 'youtube' and item.get('platform') == 'soundcloud':
                    return True, f"قبلاً نسخه SoundCloud برای '{keyword}' امروز دانلود شده است"
                
                if platform == 'soundcloud' and item.get('platform') == 'soundcloud':
                    return True, f"قبلاً ساندکلاد برای '{keyword}' امروز دانلود شده است"

    return False, None

def main():
    # دریافت ورودی‌ها از محیط (GitHub Actions)
    keyword = os.getenv('INPUT_KEYWORD', '').strip()
    platform = os.getenv('INPUT_PLATFORM', '').strip()
    url = os.getenv('INPUT_URL', '').strip()

    print(f"🔍 Duplicate Checker")
    print(f"   Platform : {platform or 'نامشخص'}")
    print(f"   Keyword  : {keyword or 'خالی'}")
    print(f"   URL      : {url[:60]}{'...' if len(url) > 60 else ''}")

    # فقط URL اجباری است
    if not url:
        print("❌ خطا: لینک (URL) ارسال نشده است")
        sys.exit(1)

    if not platform:
        print("⚠️ هشدار: پلتفرم مشخص نشده، فرض بر youtube")
        platform = "youtube"

    is_dup, reason = is_duplicate(keyword, platform, url)

    if is_dup:
        print(f"⏭️ تکراری: {reason}")
        with open(os.environ.get('GITHUB_OUTPUT', '/dev/null'), 'a', encoding='utf-8') as f:
            f.write("duplicate=true\n")
            if reason:
                f.write(f"reason={reason}\n")
        sys.exit(0)
    else:
        print("✅ آیتم جدید است، دانلود انجام خواهد شد")
        with open(os.environ.get('GITHUB_OUTPUT', '/dev/null'), 'a', encoding='utf-8') as f:
            f.write("duplicate=false\n")

if __name__ == "__main__":
    main()
