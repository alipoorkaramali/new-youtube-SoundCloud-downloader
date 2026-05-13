# ================== auto_audio_downloader.py ==================
import os
import subprocess
import requests
import hashlib
from pathlib import Path

LOG_URL = "https://raw.githubusercontent.com/alipoorkaramali/youtube-news-watcher/main/logs/new_videos.txt"
STATE_FILE = "processed_audio.txt"
TITLE_STATE_FILE = "processed_titles.txt"
DEST_FOLDER = "audio_downloads"

# ---------- تنظیمات فراخوانی ورک‌فلو ----------
TARGET_WORKFLOW_FILENAME = "Multi-Platform Downloader-auto.yml"
REPO = os.environ.get("GITHUB_REPOSITORY", "alipoorkaramali/youtube-news-watcher")
GITHUB_TOKEN = os.environ.get("WORKFLOW_DISPATCH_TOKEN")
REF = "main"
# ------------------------------------------------

def get_processed():
    if not Path(STATE_FILE).exists():
        return set()
    with open(STATE_FILE) as f:
        return set(line.strip() for line in f if line.strip())

def save_processed(hashes):
    with open(STATE_FILE, "w") as f:
        for h in hashes:
            f.write(h + "\n")

def load_processed_titles():
    if not Path(TITLE_STATE_FILE).exists():
        return set()
    with open(TITLE_STATE_FILE, encoding='utf-8') as f:
        return set(line.strip() for line in f if line.strip())

def add_processed_title(title):
    with open(TITLE_STATE_FILE, "a", encoding='utf-8') as f:
        f.write(title + "\n")

def parse_log_line(line):
    parts = line.split(" | ")
    if len(parts) < 4:
        return None, None, None

    platform = parts[1].strip()
    if platform not in ("youtube", "soundcloud"):
        url = parts[-1].strip()
        if "youtube.com" in url:
            platform = "youtube"
        elif "soundcloud.com" in url:
            platform = "soundcloud"
        else:
            return None, None, None

    url = parts[-1].strip()
    title_parts = parts[2:-1]
    title = " | ".join(title_parts).strip() if title_parts else None

    return platform, title, url

def dispatch_workflow(platform, url, folder):
    if not GITHUB_TOKEN:
        raise RuntimeError("توکن WORKFLOW_DISPATCH_TOKEN تنظیم نشده است.")

    api_url = f"https://api.github.com/repos/{REPO}/actions/workflows/{TARGET_WORKFLOW_FILENAME}/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    payload = {
        "ref": REF,
        "inputs": {
            "platform": platform,
            "format": "audio",
            "url": url,
            "folder": folder
        }
    }

    print(f"🚀 ارسال درخواست دانلود {platform} به ورک‌فلو: {url}")
    resp = requests.post(api_url, json=payload, headers=headers)

    if resp.status_code == 204:
        print("✅ درخواست با موفقیت ثبت شد.")
        return True
    else:
        print(f"❌ خطا در فراخوانی ورک‌فلو ({resp.status_code}): {resp.text}")
        return False

def download_audio_directly(platform, url):
    Path(DEST_FOLDER).mkdir(parents=True, exist_ok=True)

    # ========== اضافه شده: بررسی وجود فایل کوکی برای یوتیوب ==========
    if platform == "youtube":
        if not os.path.exists("cookies.txt"):
            print("❌ خطا: فایل cookies.txt یافت نشد!")
            print("لطفاً فایل cookies.txt را در همان پوشه برنامه قرار دهید.")
            print("برای راهنما، فایل cookies.example.txt را ببینید.")
            return False
    # =================================================================

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

    if platform == "youtube":
        cmd = [
            "yt-dlp",
            "-f", "bestaudio[ext=m4a]/bestaudio/best",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--cookies", "cookies.txt",
            "--user-agent", user_agent,
            "--force-overwrites",
            "--no-playlist",
            url,
            "-o", f"{DEST_FOLDER}/%(title)s.%(ext)s"
        ]
    else:  # soundcloud
        cmd = [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--no-playlist",
            "--force-ipv4",
            "--user-agent", user_agent,
            url,
            "-o", f"{DEST_FOLDER}/%(title)s.%(ext)s"
        ]

    print(f"⬇️ دانلود مستقیم صوت {platform}: {url}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print("✅ دانلود موفق")
        return True
    else:
        print(f"❌ خطا در دانلود:\n{result.stderr}")
        return False

def main():
    resp = requests.get(LOG_URL)
    if resp.status_code != 200:
        print(f"⚠️ دریافت لاگ ناموفق: {resp.status_code}")
        return

    lines = [line.strip() for line in resp.text.splitlines() if line.strip()]
    processed_urls = get_processed()
    processed_titles = load_processed_titles()

    new_dispatches = 0
    new_downloads = 0

    for line in lines:
        plat, title, url = parse_log_line(line)
        if not url:
            print(f"⚠️ نتوانستم لینکی از خط زیر استخراج کنم:\n{line}")
            continue

        url_hash = hashlib.md5(url.encode()).hexdigest()
        if url_hash in processed_urls:
            continue

        if title and title in processed_titles:
            print(f"⏭️ عنوان تکراری از منبع دیگر: {title}")
            processed_urls.add(url_hash)
            continue

        if plat == "youtube":
            success = dispatch_workflow("youtube", url, DEST_FOLDER)
            if success:
                processed_urls.add(url_hash)
                if title:
                    processed_titles.add(title)
                    add_processed_title(title)
                new_dispatches += 1
            else:
                print(f"⚠️ ارسال ناموفق، لینک برای اجرای بعدی باقی می‌ماند: {url}")
        else:
            success = download_audio_directly(plat, url)
            if success:
                processed_urls.add(url_hash)
                if title:
                    processed_titles.add(title)
                    add_processed_title(title)
                new_downloads += 1
            else:
                processed_urls.add(url_hash)

    save_processed(processed_urls)

    if new_dispatches:
        print(f"🚀 {new_dispatches} درخواست دانلود یوتیوب به ورک‌فلو ارسال شد.")
    if new_downloads:
        print(f"🎉 {new_downloads} فایل صوتی (غیر یوتیوب) مستقیماً دانلود شد.")
    if not new_dispatches and not new_downloads:
        print("🔄 فایل جدیدی برای دانلود وجود ندارد.")

if __name__ == "__main__":
    main()
