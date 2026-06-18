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
    if not os.path.exists(STATE_FILE):
        return []
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_state(items):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

def is_duplicate(keyword, platform, url):
    today = str(iran_now().date())
    items = load_state()

    # ۱. چک تکراری بر اساس لینک
    for item in items:
        if item.get('url') == url:
            return True, "لینک تکراری"

    # ۲. چک اولویت ساندکلاد
    for item in items:
        if (item.get('keyword') == keyword and
            item.get('date') == today):
            if platform == 'youtube' and item.get('platform') == 'soundcloud':
                return True, f"قبلاً ساندکلاد برای '{keyword}' امروز دانلود شده است"
            if platform == 'soundcloud' and item.get('platform') == 'soundcloud':
                # اگر قبلاً ساندکلاد برای همین کلیدواژه ثبت شده، تکراری است
                return True, f"قبلاً ساندکلاد برای '{keyword}' امروز دانلود شده است"

    return False, None

def main():
    keyword = os.getenv('INPUT_KEYWORD')
    platform = os.getenv('INPUT_PLATFORM')
    url = os.getenv('INPUT_URL')

    if not keyword or not platform or not url:
        print("❌ پارامترهای ورودی کامل نیستند")
        sys.exit(1)

    is_dup, reason = is_duplicate(keyword, platform, url)
    if is_dup:
        print(f"⏭️ تکراری: {reason}")
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write("duplicate=true\n")
            f.write(f"reason={reason}\n")
        sys.exit(0)
    else:
        print("✅ آیتم جدید است، اجازه دانلود داده می‌شود")
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write("duplicate=false\n")

if __name__ == "__main__":
    main()
