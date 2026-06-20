import os
import sys
import json
import csv
import requests
import time
import zipfile
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, unquote
from apify_client import ApifyClient
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════════ تنظیمات ═══════════════════
APIFY_TOKEN = os.environ.get('APIFY_TOKEN') or os.environ.get('APIFY_API_TOKEN', '')
if not APIFY_TOKEN:
    print("❌ APIFY_TOKEN is empty! Make sure the secret is set correctly.")
    sys.exit(1)

CHANNEL = os.environ.get('CHANNEL', 'durov').lstrip('@')
LIMIT = int(os.environ.get('POST_LIMIT', '20'))
MAX_MEDIA_SIZE_MB = int(os.environ.get('MAX_MEDIA_SIZE_MB', '80'))

ACTOR_ID = "automation-lab/telegram-scraper"

BASE_DIR = os.path.join("Download", "telegram_downloads", CHANNEL)
MEDIA_DIR = os.path.join(BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

MAX_MEDIA_SIZE_BYTES = MAX_MEDIA_SIZE_MB * 1024 * 1024

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# ═══════════════════ توابع کمکی ═══════════════════

def download_file(url, save_path, max_bytes=None):
    if max_bytes:
        try:
            resp = requests.head(url, timeout=20, headers=HEADERS)
            size = int(resp.headers.get('Content-Length', 0))
            if size > max_bytes:
                print(f"⏩ Skipped large file ({size / 1024 / 1024:.1f} MB)")
                return False, size
        except:
            pass

    for attempt in range(6):
        try:
            r = requests.get(url, stream=True, timeout=90, headers=HEADERS)
            if r.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        f.write(chunk)
                return True, os.path.getsize(save_path)
            else:
                print(f"   ⚠️ HTTP {r.status_code}")
        except Exception as e:
            print(f"   ⚠️ Download error (attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)
    print(f"   ❌ Failed: {url[:100]}...")
    return False, 0

def format_iran_time(iso_date_str):
    try:
        dt = datetime.fromisoformat(iso_date_str.replace('Z', '+00:00'))
        iran_dt = dt + timedelta(hours=3, minutes=30)
        return iran_dt.strftime('%Y/%m/%d - %H:%M')
    except:
        return iso_date_str

def safe_format_number(value):
    try:
        if isinstance(value, (int, float)):
            return f"{value:,}"
        return str(value)
    except:
        return str(value)

def generate_html(posts, channel_name, channel_info, media_paths):
    iran_date_str = datetime.now(timezone.utc).strftime('%Y/%m/%d - %H:%M')

    html = f'''<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>@{channel_name} - Telegram Posts</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; color: #1c1e21; }}
        .header {{ background: linear-gradient(135deg, #2a6df4, #1e4fcf); color: white; padding: 25px; border-radius: 16px; margin-bottom: 30px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; }}
        .header h1 {{ margin: 5px 0; font-size: 24px; }}
        .stats {{ display: flex; justify-content: center; gap: 30px; margin: 15px 0; font-size: 14px; opacity: 0.9; }}
        .post {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); border-right: 4px solid #2a6df4; }}
        .post-header {{ display: flex; justify-content: space-between; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid #eee; }}
        .media-container img, .media-container video {{ max-width: 100%; max-height: 500px; border-radius: 8px; margin: 10px 0; }}
    </style>
</head>
<body>
<div class="header">
    <h1>@{channel_name}</h1>
    <div class="stats">
        <span>📊 {len(posts)} پست</span>
        <span>📅 بروزرسانی: {iran_date_str}</span>
    </div>
</div>
'''

    for post in posts:
        post_id = str(post.get('id') or post.get('Id') or post.get('messageId', '?'))
        date = format_iran_time(post.get('date') or post.get('Date', ''))
        body = post.get('text') or post.get('Body', '')
        url = post.get('url') or post.get('Url', '#')

        html += f'''
<div class="post">
    <div class="post-header">
        <span>#{post_id}</span>
        <span>{date}</span>
    </div>
    <div>{body}</div>
'''

        if str(post_id) in media_paths:
            for m_path in media_paths[str(post_id)]:
                ext = m_path.split('.')[-1].lower()
                if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    html += f'<div class="media-container"><img src="{m_path}" loading="lazy"></div>'
                elif ext in ['mp4', 'webm', 'mov']:
                    html += f'<div class="media-container"><video controls><source src="{m_path}"></video></div>'
                else:
                    html += f'<div class="media-container"><a href="{m_path}">📎 {ext.upper()}</a></div>'

        html += f'<a href="{url}" target="_blank">🔗 مشاهده در تلگرام</a></div>\n'

    html += '</body></html>'
    return html

def create_zip_archive(base_dir, channel):
    zip_name = f"{channel}_full_archive.zip"
    zip_path = os.path.join(base_dir, zip_name)

    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.endswith(('.html', '.json', '.csv')) or 'media' in root:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, base_dir)
                    zipf.write(file_path, arcname)

    print(f"✅ ZIP created: {zip_name} ({os.path.getsize(zip_path)/1024/1024:.1f} MB)")
    return zip_name

# ═══════════════════ اصلی ═══════════════════

def main():
    client = ApifyClient(APIFY_TOKEN)

    run_input = {
        "channels": [CHANNEL],
        "maxMessages": LIMIT,           # پارامتر درست Actor
        "includeMedia": True,
        "includeReactions": True,
        "sort": "desc"                  # جدیدترین اول
    }

    print(f"🚀 Starting scrape @{CHANNEL} | Requested Limit: {LIMIT}")

    run = client.actor(ACTOR_ID).call(run_input=run_input, wait_duration=timedelta(minutes=15))

    if not run or run.status != 'SUCCEEDED':
        print(f"❌ Run failed!")
        sys.exit(1)

    items = list(client.dataset(run.default_dataset_id).iterate_items())

    # کنترل نهایی تعداد
    items = items[:LIMIT]

    print(f"📥 Final posts: {len(items)}")

    if not items:
        print("⚠️ No posts found!")
        return

    channel_info = items[0]
    media_map = {}
    downloaded_count = 0

    def download_media_for_post(item):
        nonlocal downloaded_count
        msg_id = str(item.get('id') or item.get('Id') or item.get('messageId', 'unknown'))
        local_paths = []

        # تمام مدیاهای ممکن
        media_list = item.get('media', []) or []

        # فیلدهای مستقیم
        for key in ['photoUrl', 'videoUrl', 'mediaUrl', 'fileUrl', 'documentUrl', 'voiceUrl', 'audioUrl']:
            if item.get(key) and str(item.get(key)).startswith('http'):
                media_list.append({'url': item.get(key)})

        for idx, media in enumerate(media_list):
            url = None
            if isinstance(media, dict):
                url = media.get('url') or media.get('mediaUrl') or media.get('photoUrl') or media.get('videoUrl')
            elif isinstance(media, str) and media.startswith('http'):
                url = media

            if not url or not url.startswith('http'):
                continue

            parsed = urlparse(url)
            path_part = unquote(parsed.path).split('/')[-1]
            ext = path_part.split('.')[-1].split('?')[0][:10].lower() if '.' in path_part else 'bin'

            filename = f"post_{msg_id}_{idx}.{ext}"
            filepath = os.path.join(MEDIA_DIR, filename)
            rel_path = f"media/{filename}"

            if os.path.exists(filepath):
                local_paths.append(rel_path)
                continue

            print(f"⬇️ Downloading post {msg_id} media {idx}: {filename}")
            success, size = download_file(url, filepath, MAX_MEDIA_SIZE_BYTES)
            if success:
                downloaded_count += 1
                local_paths.append(rel_path)
                print(f"   ✅ Done")

        return msg_id, local_paths

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(download_media_for_post, item): item for item in items}
        for future in as_completed(futures):
            msg_id, paths = future.result()
            if paths:
                media_map[msg_id] = paths

    # ذخیره خروجی‌ها
    with open(os.path.join(BASE_DIR, 'posts.json'), 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    html_content = generate_html(items, CHANNEL, channel_info, media_map)
    with open(os.path.join(BASE_DIR, 'posts.html'), 'w', encoding='utf-8') as f:
        f.write(html_content)

    zip_name = create_zip_archive(BASE_DIR, CHANNEL)

    print(f"\n🎉 Finished @{CHANNEL}!")
    print(f"   📊 Posts: {len(items)}")
    print(f"   🖼️ Media downloaded: {downloaded_count}")
    print(f"   📦 Archive: {zip_name}")

if __name__ == "__main__":
    main()
