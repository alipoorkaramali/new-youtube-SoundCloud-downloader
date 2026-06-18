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
    """بارگذاری لیست دانلود شده‌ها"""
    if not os.path.exists(STATE_FILE):
        return []
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ خطا در خواندن State: {e}")
        return []

def save_state(items):
    """ذخیره لیست دانلود شده‌ها"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ خطا در ذخیره State: {e}")

def main():
    # دریافت ورودی‌ها (با مقدار پیش‌فرض)
    keyword = os.getenv('INPUT_KEYWORD', '').strip()
    platform = os.getenv('INPUT_PLATFORM', 'youtube').strip()
    url = os.getenv('INPUT_URL', '').strip()

    print("📝 ثبت آیتم جدید در downloaded_items.json")
    print(f"   Platform : {platform}")
    print(f"   Keyword  : {keyword or 'نامشخص'}")
    print(f"   URL      : {url[:80]}{'...' if len(url) > 80 else ''}")

    if not url:
        print("❌ خطا: URL ارسال نشده است")
        sys.exit(1)

    if not platform:
        platform = "youtube"

    items = load_state()

    # جلوگیری از ثبت تکراری URL
    for item in items:
        if item.get('url') == url:
            print("⚠️ این URL قبلاً ثبت شده است")
            sys.exit(0)

    # اضافه کردن آیتم جدید
    new_item = {
        "keyword": keyword or "نامشخص",
        "platform": platform,
        "url": url,
        "date": str(iran_now().date()),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    items.append(new_item)
    save_state(items)

    print(f"✅ آیتم جدید با موفقیت ثبت شد: {keyword or 'نامشخص'} ({platform})")

if __name__ == "__main__":
    main()
