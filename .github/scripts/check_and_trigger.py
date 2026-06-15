#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import requests
import hashlib
from pathlib import Path

# ========================== تنظیمات ==========================
LOG_URL = "https://raw.githubusercontent.com/alipoorkaramali/youtube-news-watcher/main/logs/new_videos.txt"

STATE_FILE = "State/processed.txt"                 # هش لینک‌های پردازش شده (موفق یا رد شده)
TITLE_STATE_FILE = "State/processed_titles.txt"    # عنوان خام (برای سازگاری با نسخه‌های قبل)
NORM_TITLE_FILE = "State/normalized_titles.txt"    # هش عنوان نرمالایز شده (برای جلوگیری از تکرار)
FAILED_SC_FILE = "State/failed_soundcloud_titles.txt"  # عناوینی که SoundCloud آن‌ها شکست خورده

REPO_OWNER = "alipoorkaramali"
REPO_NAME = "new-youtube-SoundCloud-downloader"
WORKFLOW_FILE = "Multi-Platform Downloader-auto🔐.yml"

CROSS_REPO_PAT = os.environ.get("CROSS_REPO_PAT")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

if CROSS_REPO_PAT:
    TOKEN = CROSS_REPO_PAT
    print("✅ استفاده از توکن شخصی (CROSS_REPO_PAT)")
elif GITHUB_TOKEN:
    TOKEN = GITHUB_TOKEN
    print("⚠️ استفاده از GITHUB_TOKEN پیش‌فرض (ممکن است دسترسی کافی نداشته باشد)")
else:
    raise Exception("❌ هیچ توکنی در متغیرهای محیطی یافت نشد")

AUTO_FOLDER = "audio_downloads"

os.makedirs("State", exist_ok=True)


# ================== توابع وضعیت (قبلی) ==================
def load_processed_hashes():
    if not Path(STATE_FILE).exists():
        return set()
    with open(STATE_FILE) as f:
        return {line.strip() for line in f if line.strip()}

def save_processed_hashes(hashes):
    with open(STATE_FILE, "w") as f:
        for h in hashes:
            f.write(h + "\n")

def load_processed_titles():
    """فقط برای سازگاری با نسخه قبل (عنوان خام)"""
    if not Path(TITLE_STATE_FILE).exists():
        return set()
    with open(TITLE_STATE_FILE, encoding='utf-8') as f:
        return {line.strip() for line in f if line.strip()}

def add_processed_title(title):
    with open(TITLE_STATE_FILE, "a", encoding='utf-8') as f:
        f.write(title + "\n")


# ================== توابع جدید برای عنوان نرمالایز شده ==================
def normalize_title(title: str) -> str:
    """نرمالایز کردن عنوان: حذف پرانتز، کلمات اضافی، زمان نسبی، تبدیل به حروف کوچک و هش MD5"""
    if not title:
        return ""
    # حذف داخل پرانتز یا کروشه
    title = re.sub(r'\s*[\(\[].*?[\)\]]\s*', ' ', title)
    # حذف کلمات رایج اضافی (مستقل از حروف بزرگ/کوچک)
    title = re.sub(r'(?i)\b(audio|official|video|music|clip|lyrics|hd|4k|mp3|download|new|full|track|song)\b', '', title)
    # حذف بخش زمان نسبی (مثل "| 2 hours ago")
    parts = title.split('|')
    if len(parts) > 1:
        last_part = parts[-1].strip()
        if re.search(r'\b(hours?|minutes?|ago)\b', last_part, re.I):
            parts = parts[:-1]
    title = '|'.join(parts).strip()
    title = re.sub(r'\s+', ' ', title)
    title = title.strip()
    return hashlib.md5(title.lower().encode('utf-8')).hexdigest()

def load_normalized_titles():
    if not Path(NORM_TITLE_FILE).exists():
        return set()
    with open(NORM_TITLE_FILE, encoding='utf-8') as f:
        return {line.strip() for line in f if line.strip()}

def save_normalized_title(norm_hash):
    with open(NORM_TITLE_FILE, "a", encoding='utf-8') as f:
        f.write(norm_hash + "\n")

def load_failed_soundcloud_titles():
    if not Path(FAILED_SC_FILE).exists():
        return set()
    with open(FAILED_SC_FILE, encoding='utf-8') as f:
        return {line.strip() for line in f if line.strip()}

def save_failed_soundcloud_title(norm_hash):
    with open(FAILED_SC_FILE, "a", encoding='utf-8') as f:
        f.write(norm_hash + "\n")

def remove_failed_soundcloud_title(norm_hash):
    """حذف یک هش از فایل شکست SoundCloud (بازنویسی فایل)"""
    if not Path(FAILED_SC_FILE).exists():
        return
    titles = load_failed_soundcloud_titles()
    if norm_hash in titles:
        titles.remove(norm_hash)
        with open(FAILED_SC_FILE, "w", encoding='utf-8') as f:
            for h in titles:
                f.write(h + "\n")


# ================== توابع پردازش لاگ و فراخوانی ==================
def extract_info(line: str):
    parts = line.split(" | ")
    if len(parts) < 4:
        return None
    platform = parts[1].strip()
    if platform not in ("youtube", "soundcloud"):
        url = parts[-1].strip()
        if "youtube.com" in url or "youtu.be" in url:
            platform = "youtube"
        elif "soundcloud.com" in url:
            platform = "soundcloud"
        else:
            return None
    url = parts[-1].strip()
    title_parts = parts[2:-1]
    title = " | ".join(title_parts).strip() if title_parts else None
    return (platform, title, url)

def trigger_download(video_url: str, platform: str):
    workflow_id = requests.utils.quote(WORKFLOW_FILE, safe='')
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{workflow_id}/dispatches"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "ref": "main",
        "inputs": {
            "platform": platform,
            "url": video_url,
            "format": "audio",
            "folder": AUTO_FOLDER
        }
    }
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code == 204:
        print(f"✅ دانلود آغاز شد: {video_url} (platform={platform})")
        return True
    else:
        print(f"❌ خطا در فراخوانی برای {video_url}: {resp.status_code} {resp.text}")
        return False


# ================== تابع اصلی با اولویت و مدیریت عنوان تکراری ==================
def main():
    # دریافت لاگ
    try:
        resp = requests.get(LOG_URL, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ دریافت لاگ ناموفق: {e}")
        return

    lines = [line.strip() for line in resp.text.splitlines() if line.strip()]
    if not lines:
        print("⚠️ لاگ خالی است.")
        return

    # بارگذاری وضعیت‌ها
    processed_hashes = load_processed_hashes()
    normalized_titles = load_normalized_titles()       # عناوین نرمالایز شده موفق
    failed_sc_titles = load_failed_soundcloud_titles() # عناوینی که SoundCloud آن‌ها شکست خورده

    # برای جلوگیری از پردازش تکراری در همین اجرا
    seen_in_run = set()

    new_count = 0

    # گروه‌بندی بر اساس عنوان نرمالایز شده (هر عنوان ممکن است چندین لینک از پلتفرم‌های مختلف داشته باشد)
    title_map = {}
    for line in lines:
        info = extract_info(line)
        if not info:
            print(f"⚠️ خطای استخراج: {line}")
            continue
        platform, title, url = info
        if not title:
            continue
        norm_hash = normalize_title(title)
        if not norm_hash:
            continue
        if norm_hash not in title_map:
            title_map[norm_hash] = []
        title_map[norm_hash].append((platform, title, url))

    for norm_hash, items in title_map.items():
        # 1. اگر عنوان قبلاً موفق شده باشد → رد کن و تمام لینک‌های آن را به processed اضافه کن
        if norm_hash in normalized_titles:
            print(f"⏭️ عنوان تکراری (نرمالایز شده): {norm_hash} - قبلاً دانلود شده.")
            for _, _, url in items:
                link_hash = hashlib.md5(url.encode()).hexdigest()
                processed_hashes.add(link_hash)
            continue

        # 2. اگر در همین اجرا قبلاً برای این عنوان اقدامی شده → رد کن
        if norm_hash in seen_in_run:
            continue

        # 3. تعیین پلتفرم بر اساس اولویت و فایل شکست SoundCloud
        selected_platform = None
        selected_url = None
        selected_title = None

        # اگر این عنوان در فایل شکست SoundCloud است → فقط YouTube را در نظر بگیر
        if norm_hash in failed_sc_titles:
            for platform, title, url in items:
                if platform == "youtube":
                    selected_platform = platform
                    selected_url = url
                    selected_title = title
                    break
            if not selected_platform:
                print(f"⚠️ عنوان {norm_hash} در فایل شکست SoundCloud است اما لینک YouTube وجود ندارد. رد می‌شود.")
                # تمام لینک‌های این عنوان را به processed اضافه کن تا دیگر نیایند
                for _, _, url in items:
                    link_hash = hashlib.md5(url.encode()).hexdigest()
                    processed_hashes.add(link_hash)
                continue
        else:
            # اولویت با SoundCloud
            for platform, title, url in items:
                if platform == "soundcloud":
                    selected_platform = platform
                    selected_url = url
                    selected_title = title
                    break
            # اگر SoundCloud نبود، YouTube را انتخاب کن
            if not selected_platform:
                for platform, title, url in items:
                    if platform == "youtube":
                        selected_platform = platform
                        selected_url = url
                        selected_title = title
                        break
            # اگر هیچکدام (فقط موارد دیگر) → رد کن
            if not selected_platform:
                continue

        # 4. چک کردن هش لینک انتخابی (در صورتی که قبلاً پردازش شده باشد)
        link_hash = hashlib.md5(selected_url.encode()).hexdigest()
        if link_hash in processed_hashes:
            print(f"⚠️ لینک {selected_url} قبلاً پردازش شده، عنوان را رد می‌کنیم.")
            # بقیه لینک‌های این عنوان را هم به processed اضافه کن
            for _, _, url in items:
                processed_hashes.add(hashlib.md5(url.encode()).hexdigest())
            continue

        # 5. عنوان جدید است → اقدام به دانلود
        print(f"🎧 پردازش عنوان جدید (اولویت: {selected_platform}): {selected_title} - {selected_url}")
        seen_in_run.add(norm_hash)

        success = trigger_download(selected_url, selected_platform)

        if success:
            # موفقیت: ثبت عنوان نرمالایز شده، هش لینک، و حذف از فایل شکست (اگر بود)
            save_normalized_title(norm_hash)
            normalized_titles.add(norm_hash)
            processed_hashes.add(link_hash)
            # برای سازگاری با نسخه قبل، عنوان خام را هم ذخیره کن
            add_processed_title(selected_title)
            if norm_hash in failed_sc_titles:
                remove_failed_soundcloud_title(norm_hash)
                print(f"✅ عنوان {norm_hash} از فایل شکست SoundCloud حذف شد (چون YouTube با موفقیت دانلود شد).")
            new_count += 1
        else:
            # شکست در فراخوانی
            if selected_platform == "soundcloud":
                # ثبت در فایل شکست SoundCloud تا دفعه بعد YouTube امتحان شود
                if norm_hash not in failed_sc_titles:
                    save_failed_soundcloud_title(norm_hash)
                    print(f"⚠️ SoundCloud برای عنوان {norm_hash} ناموفق بود. در دفعات بعد YouTube امتحان می‌شود.")
            else:
                # YouTube شکست خورده (موقتاً هیچ کاری نمی‌کنیم، دفعه بعد دوباره تلاش می‌شود)
                print(f"❌ YouTube نیز برای عنوان {norm_hash} ناموفق بود. بعداً دوباره تلاش می‌شود.")
            # لینک را به processed اضافه نمی‌کنیم تا دوباره تلاش شود

    # ذخیره نهایی هش لینک‌های پردازش شده
    save_processed_hashes(processed_hashes)

    if new_count:
        print(f"🎉 {new_count} آیتم جدید با موفقیت پردازش شد.")
    else:
        print("🔄 آیتم جدیدی برای پردازش وجود ندارد.")


if __name__ == "__main__":
    main()
