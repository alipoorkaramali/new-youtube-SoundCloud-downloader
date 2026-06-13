import os
import re
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
WORKFLOW_FILE = "Multi-Platform Downloader-auto🔐.yml"
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

# پوشهٔ مقصد برای دانلودهای خودکار
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
    timestamp | platform | عنوان | relative_time | url
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
    # عنوان = بخش‌های میانی تا یکی‌مانده‌به‌آخر (relative_time حذف می‌شود)
    title_parts = parts[2:-1]
    title = " | ".join(title_parts).strip() if title_parts else None

    return (platform, title, url)


def normalize_title(title: str) -> str:
    """
    نرمالایز کردن عنوان برای مقایسه بهتر بین یوتیوب و ساندکلاد:
    - حذف کلمات اضافی مانند (Audio), (Official Video), [lyrics] و ...
    - حذف کاراکترهای تکراری و فاصله‌های اضافی
    - تبدیل به حروف کوچک
    """
    if not title:
        return ""
    # حذف محتوای داخل پرانتز و کروشه
    title = re.sub(r'\s*[\(\[].*?[\)\]]\s*', ' ', title)
    # حذف عبارات رایج
    title = re.sub(r'(?i)\b(audio|official|video|music|clip|lyrics|hd|4k|mp3|download)\b', '', title)
    # تبدیل چند فاصله به یک فاصله
    title = re.sub(r'\s+', ' ', title)
    # حذف فاصله از ابتدا و انتها و تبدیل به lowercase
    return title.strip().lower()


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
            "folder": AUTO_FOLDER
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

    # دیکشنری موقت برای عناوین نرمالایز شده در همین اجرا (جلوگیری از دانلود همزمان دو پلتفرم)
    seen_normalized_titles = set()

    new_count = 0

    for line in lines:
        info = extract_info(line)
        if info is None:
            print(f"⚠️ نتوانستم اطلاعات را از خط زیر استخراج کنم:\n{line}")
            continue

        platform, title, video_url = info

        # بررسی تکراری بودن لینک
        link_hash = hashlib.md5(video_url.encode()).hexdigest()
        if link_hash in processed_hashes:
            continue

        # نرمالایز کردن عنوان (اگر عنوان داشته باشیم)
        norm_title = normalize_title(title) if title else None

        # بررسی تکراری بودن عنوان در فایل (اجراهای قبلی)
        if title and title in processed_titles:
            print(f"⏭️ عنوان تکراری از منبع دیگر (فایل): {title}")
            processed_hashes.add(link_hash)
            continue

        # بررسی تکراری بودن عنوان نرمالایز شده در همین اجرا (یوتیوب و ساندکلاد همزمان)
        if norm_title and norm_title in seen_normalized_titles:
            print(f"⏭️ عنوان نرمالایز شده تکراری در همین اجرا: '{title}' -> '{norm_title}' - دانلود نمی‌شود.")
            processed_hashes.add(link_hash)
            continue

        print(f"🎧 پردازش {video_url} (platform={platform}, title={title})")
        success = trigger_download(video_url)

        if success:
            processed_hashes.add(link_hash)
            if title:
                processed_titles.add(title)
                add_processed_title(title)
            if norm_title:
                seen_normalized_titles.add(norm_title)
            new_count += 1
        # اگر dispatch ناموفق بود، لینک را ذخیره نمی‌کنیم تا دفعهٔ بعد تلاش شود

    save_processed_hashes(processed_hashes)

    if new_count:
        print(f"🎉 {new_count} ویدیوی جدید پردازش شد.")
    else:
        print("🔄 ویدیوی جدیدی برای پردازش وجود ندارد.")


if __name__ == "__main__":
    main()
