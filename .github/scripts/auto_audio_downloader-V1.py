import os
import re
import requests
import hashlib
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta

LOG_URL = "https://raw.githubusercontent.com/alipoorkaramali/youtube-news-watcher/main/logs/new_videos.txt"
STATE_FILE = "State/downloaded_items.json"   # استفاده از فایل وضعیت یکسان
REPO_OWNER = "alipoorkaramali"
REPO_NAME = "new-youtube-SoundCloud-downloader"
WORKFLOW_FILE = "Multi-Platform Downloader-auto🔐.yml"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
AUTO_FOLDER = "audio_downloads"

os.makedirs("State", exist_ok=True)

# ============= توابع بارگذاری/ذخیره وضعیت (هماهنگ با ورک‌فلو) =============
def load_state():
    if not os.path.exists(STATE_FILE):
        return []
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_state(items):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

# ============= استخراج اطلاعات از خط لاگ =============
def extract_info(line: str):
    parts = line.split(" | ")
    if len(parts) < 4:
        return None
    platform = parts[1].strip()
    if platform not in ("youtube", "soundcloud"):
        url = parts[-1].strip()
        if "youtube.com" in url:
            platform = "youtube"
        elif "soundcloud.com" in url:
            platform = "soundcloud"
        else:
            return None
    url = parts[-1].strip()
    title_parts = parts[2:-1]
    title = " | ".join(title_parts).strip() if title_parts else None
    return (platform, title, url)

# ============= نرمال‌سازی عنوان (برای تشخیص شباهت) =============
def normalize_title(title: str) -> str:
    if not title:
        return ""
    title = re.sub(r'\s*[\(\[].*?[\)\]]\s*', ' ', title)
    title = re.sub(r'(?i)\b(audio|official|video|music|clip|lyrics|hd|4k|mp3|download)\b', '', title)
    title = re.sub(r'\s+', ' ', title)
    return title.strip().lower()

# ============= تریگر ورک‌فلو با workflow_dispatch =============
def trigger_download(video_url: str, platform: str, keyword: str):
    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN موجود نیست.")
        return False
    workflow_id = requests.utils.quote(WORKFLOW_FILE, safe='')
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{workflow_id}/dispatches"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "ref": "main",
        "inputs": {
            "platform": platform,
            "url": video_url,
            "format": "audio",
            "folder": AUTO_FOLDER,
            "keyword": keyword   # اضافه شد
        }
    }
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code == 204:
        print(f"✅ دانلود آغاز شد: {video_url}")
        return True
    else:
        print(f"❌ خطا برای {video_url}: {resp.status_code} {resp.text}")
        return False

# ============= اصلی =============
def main():
    if not GITHUB_TOKEN:
        print("⚠️ GITHUB_TOKEN تنظیم نشده. خروج.")
        return

    resp = requests.get(LOG_URL)
    if resp.status_code != 200:
        print(f"⚠️ دریافت لاگ ناموفق: {resp.status_code}")
        return

    lines = [line.strip() for line in resp.text.splitlines() if line.strip()]
    state_items = load_state()
    # استخراج لینک‌های قبلی
    processed_urls = {item['url'] for item in state_items}
    # دیکشنری برای تشخیص کلیدواژه‌های ساندکلاد شده در امروز
    today = datetime.now(timezone.utc).date().isoformat()
    soundcloud_keywords = {
        item['keyword'] for item in state_items
        if item.get('platform') == 'soundcloud' and item.get('date') == today
    }

    new_count = 0
    for line in lines:
        info = extract_info(line)
        if info is None:
            continue
        platform, title, video_url = info
        if video_url in processed_urls:
            continue

        # استخراج کلیدواژه از عنوان (با نرمال‌سازی)
        norm_title = normalize_title(title) if title else ""
        # سعی می‌کنیم کلیدواژه را از عنوان حدس بزنیم (برای تطابق با اسکنر)
        # اما بهتر است از لاگ کلیدواژه را نداشته باشیم، پس از عنوان استفاده می‌کنیم.
        # برای ساده‌سازی، کلیدواژه را همان عنوان نرمال‌شده در نظر می‌گیریم.
        # ولی در عمل، اسکنر keyword را به همراه trigger می‌فرستد، بنابراین این مسیر کمکی است.
        keyword = norm_title  # تقریبی

        # بررسی اولویت ساندکلاد
        if platform == 'youtube' and keyword in soundcloud_keywords:
            print(f"⏭️ اولویت با ساندکلاد: '{keyword}' قبلاً امروز دانلود شده است.")
            continue

        # اگر اینجا رسیدیم، یعنی جدید است
        print(f"🎧 پردازش {video_url} (platform={platform})")
        success = trigger_download(video_url, platform, keyword)
        if success:
            # ثبت در وضعیت (با یک آیتم جدید)
            state_items.append({
                "keyword": keyword,
                "platform": platform,
                "url": video_url,
                "date": today,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            save_state(state_items)
            processed_urls.add(video_url)
            if platform == 'soundcloud':
                soundcloud_keywords.add(keyword)
            new_count += 1

    if new_count:
        print(f"🎉 {new_count} ویدیوی جدید پردازش شد.")
    else:
        print("🔄 ویدیوی جدیدی برای پردازش وجود ندارد.")

if __name__ == "__main__":
    main()
