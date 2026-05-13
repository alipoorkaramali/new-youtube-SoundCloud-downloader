import os
import requests
import hashlib
from pathlib import Path

# آدرس فایل لاگ در مخزن اسکنر
LOG_URL = "https://raw.githubusercontent.com/alipoorkaramali/youtube-news-watcher/main/logs/new_videos.txt"

# فایل‌های وضعیت
STATE_FILE = "processed.txt"               # هش لینک‌های پردازش‌شده
TITLE_STATE_FILE = "processed_titles.txt"  # عناوین دانلودشده (جلوگیری از تکراری)

# اطلاعات مخزن دانلودر
REPO_OWNER = "alipoorkaramali"
REPO_NAME = "youtube-SoundCloud-downloader"
WORKFLOW_FILE = "Multi-Platform Downloader-auto🔐.yml"   # <---- تغییر این خط
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

# پوشهٔ مقصد برای دانلودهای خودکار (جدا از دانلودهای دستی)
AUTO_FOLDER = "audio_downloads"


def load_processed_hashes():
    if not Path(STATE_FILE).exists():
        return set()
    with open(STATE_FILE) as f:
        return set(line.strip() for line in f if line.strip())


def save_processed_hashes(hashes):
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


def extract_info(line: str):
    """
    ساختار خط لاگ:
    timestamp | platform | عنوان (ممکن است شامل | باشد) | relative_time | url
    خروجی: (platform, title, url) یا None
    """
    parts = line.split(" | ")
    if len(parts) < 4:
        return None

    platform = parts[1].strip()
    # اگر platform غیر از youtube/soundcloud بود، از URL حدس بزن
    if platform not in ("youtube", "soundcloud"):
        url = parts[-1].strip()
        if "youtube.com" in url:
            platform = "youtube"
        elif "soundcloud.com" in url:
            platform = "soundcloud"
        else:
            return None

    url = parts[-1].strip()
    # عنوان = بخش‌های میانی تا یکی‌مانده‌به‌آخر (همان relative_time حذف می‌شود)
    title_parts = parts[2:-1]
    title = " | ".join(title_parts).strip() if title_parts else None

    return (platform, title, url)


def trigger_download(video_url: str):
    workflow_id = requests.utils.quote(WORKFLOW_FILE, safe='')
    url = (
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
        f"/actions/workflows/{workflow_id}/dispatches"
    )
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "ref": "main",
        "inputs": {
            "platform": "youtube" if "youtube.com" in video_url else "soundcloud",
            "url": video_url,
            "format": "audio",
            "folder": AUTO_FOLDER          # 👈 دانلودهای خودکار در audio_downloads
        }
    }
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code == 204:
        print(f"✅ دانلود آغاز شد: {video_url}")
        return True
    else:
        print(f"❌ خطا برای {video_url}: {resp.status_code} {resp.text}")
        return False


def main():
    resp = requests.get(LOG_URL)
    if resp.status_code != 200:
        print(f"⚠️ دریافت لاگ ناموفق: {resp.status_code}")
        return

    lines = [line.strip() for line in resp.text.splitlines() if line.strip()]
    processed_hashes = load_processed_hashes()
    processed_titles = load_processed_titles()

    new_count = 0

    for line in lines:
        info = extract_info(line)
        if info is None:
            print(f"⚠️ نتوانستم اطلاعات را از خط زیر استخراج کنم:\n{line}")
            continue

        platform, title, video_url = info

        # ۱. بررسی تکراری بودن لینک (با MD5)
        link_hash = hashlib.md5(video_url.encode()).hexdigest()
        if link_hash in processed_hashes:
            continue

        # ۲. بررسی تکراری بودن عنوان (جلوگیری از دانلود یک خبر از دو پلتفرم مختلف)
        if title and title in processed_titles:
            print(f"⏭️ عنوان تکراری از منبع دیگر («{title}») - دانلود نمی‌شود.")
            processed_hashes.add(link_hash)   # لینک را هم علامت بزنیم که دوباره بررسی نشود
            continue

        print(f"🎧 پردازش {video_url} (platform={platform}, title={title})")
        success = trigger_download(video_url)

        if success:
            processed_hashes.add(link_hash)
            if title:
                processed_titles.add(title)
                add_processed_title(title)   # بلافاصله در فایل processed_titles.txt ذخیره می‌شود
            new_count += 1
        # اگر dispatch ناموفق بود، لینک را ذخیره نمی‌کنیم تا دفعهٔ بعد دوباره تلاش شود

    # ذخیرهٔ وضعیت نهایی هش‌ها (processed.txt)
    save_processed_hashes(processed_hashes)

    if new_count:
        print(f"🎉 {new_count} ویدیوی جدید پردازش شد.")
    else:
        print("🔄 ویدیوی جدیدی برای پردازش وجود ندارد.")


if __name__ == "__main__":
    main()
