#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import requests
import hashlib
import time
from pathlib import Path

# ========================== تنظیمات ==========================
LOG_URL = "https://raw.githubusercontent.com/alipoorkaramali/youtube-news-watcher/main/logs/new_videos.txt"

STATE_FILE = "State/processed.txt"
TITLE_STATE_FILE = "State/processed_titles.txt"
NORM_TITLE_FILE = "State/normalized_titles.txt"
FAILED_SC_FILE = "State/failed_soundcloud_titles.txt"

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
    print("⚠️ استفاده از GITHUB_TOKEN پیش‌فرض")
else:
    raise Exception("❌ هیچ توکنی در متغیرهای محیطی یافت نشد")

AUTO_FOLDER = "audio_downloads"

os.makedirs("State", exist_ok=True)

# ================== بقیه توابع (کاملاً همان قبلی) ==================
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
    if not Path(TITLE_STATE_FILE).exists():
        return set()
    with open(TITLE_STATE_FILE, encoding='utf-8') as f:
        return {line.strip() for line in f if line.strip()}

def add_processed_title(title):
    with open(TITLE_STATE_FILE, "a", encoding='utf-8') as f:
        f.write(title + "\n")

def normalize_title(title: str) -> str:
    if not title:
        return ""
    title = re.sub(r'\s*[\(\[].*?[\)\]]\s*', ' ', title)
    title = re.sub(r'(?i)\b(audio|official|video|music|clip|lyrics|hd|4k|mp3|download|new|full|track|song)\b', '', title)
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
    if not Path(FAILED_SC_FILE).exists():
        return
    titles = load_failed_soundcloud_titles()
    if norm_hash in titles:
        titles.remove(norm_hash)
        with open(FAILED_SC_FILE, "w", encoding='utf-8') as f:
            for h in titles:
                f.write(h + "\n")

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

# ================== تابع اصلی ==================
def main():
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

    processed_hashes = load_processed_hashes()
    normalized_titles = load_normalized_titles()
    failed_sc_titles = load_failed_soundcloud_titles()

    seen_in_run = set()
    new_count = 0
    title_map = {}

    for line in lines:
        info = extract_info(line)
        if not info:
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
        if norm_hash in normalized_titles:
            print(f"⏭️ عنوان تکراری: {norm_hash}")
            for _, _, url in items:
                processed_hashes.add(hashlib.md5(url.encode()).hexdigest())
            continue

        if norm_hash in seen_in_run:
            continue

        selected_platform = selected_url = selected_title = None

        if norm_hash in failed_sc_titles:
            for p, t, u in items:
                if p == "youtube":
                    selected_platform, selected_title, selected_url = p, t, u
                    break
        else:
            for p, t, u in items:
                if p == "soundcloud":
                    selected_platform, selected_title, selected_url = p, t, u
                    break
            if not selected_platform:
                for p, t, u in items:
                    if p == "youtube":
                        selected_platform, selected_title, selected_url = p, t, u
                        break

        if not selected_platform:
            continue

        link_hash = hashlib.md5(selected_url.encode()).hexdigest()
        if link_hash in processed_hashes:
            continue

        print(f"🎧 پردازش عنوان جدید: {selected_title} - {selected_url}")
        seen_in_run.add(norm_hash)

        success = trigger_download(selected_url, selected_platform)

        if success:
            save_normalized_title(norm_hash)
            normalized_titles.add(norm_hash)
            processed_hashes.add(link_hash)
            add_processed_title(selected_title)
            if norm_hash in failed_sc_titles:
                remove_failed_soundcloud_title(norm_hash)
            new_count += 1
        else:
            if selected_platform == "soundcloud":
                if norm_hash not in failed_sc_titles:
                    save_failed_soundcloud_title(norm_hash)

    save_processed_hashes(processed_hashes)

    if new_count:
        print(f"🎉 {new_count} آیتم جدید پردازش شد.")
    else:
        print("🔄 آیتم جدیدی وجود ندارد.")

# ================== اجرای لوپ برای Railway ==================
if __name__ == "__main__":
    print("🚀 Railway Worker started in Loop Mode (every 10 minutes)")
    while True:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting check cycle...")
        main()
        print("⏳ Sleeping for 10 minutes...\n")
        time.sleep(600)  # 10 دقیقه
