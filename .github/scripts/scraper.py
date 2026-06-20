import os
import sys
import json
import csv
import requests
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, unquote
from apify_client import ApifyClient
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════════ تنظیمات ═══════════════════
APIFY_TOKEN = os.environ.get('APIFY_TOKEN') or os.environ.get('APIFY_API_TOKEN', '')
if not APIFY_TOKEN:
    print("❌ APIFY_TOKEN is empty!")
    sys.exit(1)

CHANNEL = os.environ.get('CHANNEL', 'durov').lstrip('@')
LIMIT = int(os.environ.get('POST_LIMIT', '20'))
START_ID = int(os.environ.get('START_ID', '0'))

ACTOR_ID = "thescrapelab/Apify-Telegram-Scraper"

BASE_DIR = os.path.join("Download", "telegram_downloads", CHANNEL)
MEDIA_DIR = os.path.join(BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

MAX_MEDIA_SIZE_MB = int(os.environ.get('MAX_MEDIA_SIZE_MB', '50'))
MAX_MEDIA_SIZE_BYTES = MAX_MEDIA_SIZE_MB * 1024 * 1024

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# ═══════════════════ توابع کمکی ═══════════════════

def get_remote_file_size(url):
    try:
        resp = requests.head(url, timeout=20, allow_redirects=True, headers=HEADERS)
        length = resp.headers.get('Content-Length')
        if length and length.isdigit():
            return int(length)
    except:
        pass
    return None

def download_file(url, save_path, max_bytes=None):
    if max_bytes:
        size = get_remote_file_size(url)
        if size is not None and size > max_bytes:
            print(f"⏩ Skipped (size {size / 1024 / 1024:.1f} MB > limit)")
            return False, size

    for attempt in range(6):
        try:
            r = requests.get(url, stream=True, timeout=90, headers=HEADERS)
            if r.status_code == 200:
                downloaded = 0
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if max_bytes and downloaded > max_bytes:
                            os.remove(save_path)
                            return False, downloaded
                return True, downloaded
            else:
                print(f"   ⚠️ HTTP {r.status_code} (attempt {attempt+1})")
        except Exception as e:
            print(f"   ⚠️ Download error (attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)
    print(f"   ❌ Failed after retries: {url[:100]}...")
    return False, 0

def format_iran_time(iso_date_str):
    try:
        dt = datetime.fromisoformat(iso_date_str.replace('Z', '+00:00'))
        iran_dt = dt + timedelta(hours=3, minutes=30)
        return iran_dt.strftime('%Y/%m/%d - %H:%M')
    except:
        return iso_date_str

def generate_html(posts, channel_name, channel_info, media_paths):
    iran_date = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
    iran_date_str = iran_date.strftime('%Y/%m/%d - %H:%M')

    html = f'''<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>@{channel_name} - Telegram Posts</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; color: #1c1e21; }}
        .header {{ background: linear-gradient(135deg, #2a6df4, #1e4fcf); color: white; padding: 25px; border-radius: 16px; margin-bottom: 30px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; }}
        .header img {{ width: 80px; height: 80px; border-radius: 50%; border: 3px solid white; margin-bottom: 10px; }}
        .header h1 {{ margin: 5px 0; font-size: 24px; }}
        .header p {{ opacity: 0.9; font-size: 14px; margin: 5px 0; }}
        .stats {{ display: flex; justify-content: center; gap: 30px; margin: 15px 0; font-size: 14px; opacity: 0.9; }}
        .post {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); border-right: 4px solid #2a6df4; }}
        .post-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid #eee; }}
        .post-id {{ color: #2a6df4; font-weight: bold; }}
        .post-date {{ color: #65676b; font-size: 13px; }}
        .post-body {{ font-size: 16px; line-height: 2; white-space: pre-wrap; word-break: break-word; margin-bottom: 15px; }}
        .meta {{ background: #f0f2f5; padding: 12px; border-radius: 8px; font-size: 13px; margin-bottom: 10px; }}
        .hashtag {{ color: #1e4fcf; background: #e7f0ff; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
        .media-container {{ margin-top: 15px; text-align: center; }}
        .media-container img, .media-container video {{ max-width: 100%; max-height: 500px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 10px; }}
        .footer {{ text-align: center; margin-top: 40px; color: #65676b; font-size: 12px; border-top: 1px solid #ddd; padding-top: 15px; }}
        .post-url {{ display: inline-block; margin-top: 10px; background: #2a6df4; color: white !important; padding: 6px 14px; border-radius: 6px; font-size: 13px; text-decoration: none; }}
    </style>
</head>
<body>

<div class="header">
    {f'<img src="{channel_info.get("Channel_Photo_Url", "")}" alt="Logo">' if channel_info.get('Channel_Photo_Url') else ''}
    <h1>@{channel_name}</h1>
    <p>{channel_info.get('Channel_Name', '')}</p>
    <div class="stats">
        <span>👥 {channel_info.get('Subscribers', '?'):,}</span>
        <span>📊 {len(posts)} پست</span>
        <span>📅 بروزرسانی: {iran_date_str}</span>
    </div>
</div>
'''

    for post in posts:
        post_id = post.get('Id', '?')
        date = format_iran_time(post.get('Date', ''))
        body = post.get('Body', '')
        url = post.get('Url', '#')
        mentions = post.get('Mentions', [])
        hashtags = post.get('Hashtags', [])
        outlinks = post.get('Outlinks', [])

        html += f'''
<div class="post">
    <div class="post-header">
        <span class="post-id">#{post_id}</span>
        <span class="post-date">📅 {date}</span>
    </div>
    <div class="post-body">{body}</div>
'''

        if mentions or hashtags or outlinks:
            html += '<div class="meta">'
            if mentions:
                html += f'<span>🔗 منشن‌ها: {", ".join(mentions)}</span>'
            if hashtags:
                hashtag_html = " ".join([f'<span class="hashtag">{h}</span>' for h in hashtags])
                html += f'<span>🏷️ {hashtag_html}</span>'
            if outlinks:
                links_html = ", ".join([f'<a href="{l}">لینک</a>' for l in outlinks])
                html += f'<span>🌐 لینک‌ها: {links_html}</span>'
            html += '</div>'

        # نمایش همه مدیاهای دانلود شده برای این پست
        if str(post_id) in media_paths:
            for m_path in media_paths[str(post_id)]:
                ext = m_path.split('.')[-1].lower()
                if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    html += f'<div class="media-container"><img src="{m_path}" loading="lazy" alt="media"></div>'
                elif ext in ['mp4', 'webm', 'mov']:
                    html += f'<div class="media-container"><video controls><source src="{m_path}" type="video/{ext}"></video></div>'
                else:
                    html += f'<div class="media-container"><a href="{m_path}" target="_blank">📎 دانلود فایل ({ext})</a></div>'

        html += f'<a href="{url}" target="_blank" class="post-url">🔗 مشاهده در تلگرام</a>'
        html += '</div>\n'

    html += f'''
<div class="footer">
    تولید شده توسط scraper در تاریخ {iran_date_str}
</div>
</body>
</html>'''
    return html

# ═══════════════════ اصلی ═══════════════════

def main():
    client = ApifyClient(APIFY_TOKEN)

    run_input = {
        "channels": [{"channelName": CHANNEL, "startId": START_ID, "limit": LIMIT}]
    }

    print(f"🚀 Starting scrape @{CHANNEL} | Limit: {LIMIT}")

    run = client.actor(ACTOR_ID).call(run_input=run_input, wait_duration=timedelta(minutes=10))

    if not run or run.status != 'SUCCEEDED':
        print(f"❌ Run failed! Status: {run.status if run else 'None'}")
        sys.exit(1)

    dataset = client.dataset(run.default_dataset_id)
    items = list(dataset.iterate_items())

    if not items:
        print("⚠️ No posts found!")
        return

    print(f"📥 Received {len(items)} posts from Apify")

    channel_info = items[0]
    media_map = {}
    downloaded_count = 0
    skipped_count = 0

    def download_media_for_post(item):
        nonlocal downloaded_count, skipped_count
        msg_id = str(item.get('Id') or item.get('messageId') or 'unknown')
        local_paths = []

        # همه حالت‌های ممکن
        media_list = item.get('media', []) or []

        single_keys = ['MediaUrl', 'mediaUrl', 'photoUrl', 'videoUrl', 'fileUrl', 'LinkPreview_Image_Url', 'documentUrl']
        for key in single_keys:
            if item.get(key):
                media_list.append({'url': item.get(key)})

        for idx, media in enumerate(media_list):
            url = None
            if isinstance(media, dict):
                url = (media.get('url') or media.get('MediaUrl') or media.get('photoUrl') or 
                       media.get('videoUrl') or media.get('fileUrl') or media.get('documentUrl'))
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
                print(f"📁 Skipped existing: {filename}")
                local_paths.append(rel_path)
                continue

            print(f"⬇️ Downloading media for post {msg_id}: {filename} | URL: {url[:80]}...")
            success, size = download_file(url, filepath, MAX_MEDIA_SIZE_BYTES)
            if success:
                downloaded_count += 1
                local_paths.append(rel_path)
                print(f"   ✅ Done ({size / 1024 / 1024:.1f} MB)")
            else:
                skipped_count += 1
                print(f"   ❌ Failed")

        return msg_id, local_paths

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(download_media_for_post, item): item for item in items}
        for future in as_completed(futures):
            msg_id, paths = future.result()
            if paths:
                media_map[msg_id] = paths

    # خروجی‌ها
    json_path = os.path.join(BASE_DIR, 'posts.json')
    csv_path = os.path.join(BASE_DIR, 'posts.csv')
    html_path = os.path.join(BASE_DIR, 'posts.html')

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=items[0].keys())
        writer.writeheader()
        writer.writerows(items)

    html_content = generate_html(items, CHANNEL, channel_info, media_map)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"\n🎉 Finished @{CHANNEL}!")
    print(f"   📊 Posts: {len(items)}")
    print(f"   🖼️ Media downloaded: {downloaded_count}")
    print(f"   ⏩ Skipped/Failed: {skipped_count}")

if __name__ == "__main__":
    main()
