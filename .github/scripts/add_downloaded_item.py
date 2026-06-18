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

def add_new_item(keyword, platform, url):
    today = str(iran_now().date())
    items = load_state()
    items.append({
        "keyword": keyword,
        "platform": platform,
        "url": url,
        "date": today,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    save_state(items)
    print(f"✅ آیتم جدید ثبت شد: {keyword} ({platform})")

def main():
    keyword = os.getenv('INPUT_KEYWORD')
    platform = os.getenv('INPUT_PLATFORM')
    url = os.getenv('INPUT_URL')
    if not keyword or not platform or not url:
        print("❌ پارامترهای ورودی کامل نیستند")
        sys.exit(1)
    add_new_item(keyword, platform, url)

if __name__ == "__main__":
    main()
