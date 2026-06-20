import os
import sys
import json
import csv
import time
from datetime import datetime, timezone, timedelta
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

# Actor بهتر با قابلیت دانلود مدیا
ACTOR_ID = "webfinity/telegram-channel-content-media-scraper"

BASE_DIR = os.path.join("Download", "telegram_downloads", CHANNEL)
MEDIA_DIR = os.path.join(BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

MAX_MEDIA_SIZE_MB = int(os.environ.get('MAX_MEDIA_SIZE_MB', '80'))  # افزایش برای تست
MAX_MEDIA_SIZE_BYTES = MAX_MEDIA_SIZE_MB * 1024 * 1024

# ═══════════════════ توابع کمکی ═══════════════════

def format_iran_time(iso_date_str):
    try:
        dt = datetime.fromisoformat(iso_date_str.replace('Z', '+00:00'))
        iran_dt = dt + timedelta(hours=3, minutes=30)
        return iran_dt.strftime('%Y/%m/%d - %H:%M')
    except:
        return iso_date_str

def download_from_kvs(client, kvs_id, key, save_path, max_bytes=None):
    """دانلود از Key-Value Store Apify"""
    for attempt in range(5):
        try:
            record = client.key_value_store(kvs_id).get_record(key)
            if not record or 'value' not in record:
                print(f"   ⚠️ Record {key} not found in KVS")
                return False, 0

            data = record['value']
            size = len(data)

            if max_bytes and size > max_bytes:
                print(f"⏩ Skipped (size {size / 1024 / 1024:.1f} MB > limit)")
                return False, size

            with open(save_path, 'wb') as f:
                f.write(data)

            print(f"   ✅ Downloaded from KVS: {key} ({size / 1024 / 1024:.1f} MB)")
            return True, size
        except Exception as e:
            print(f"   ⚠️ KVS download error (attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)
    return False, 0

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
    {f'<img src="{channel_info.get("channelAvatarUrl", "") or channel_info.get("Channel_Photo_Url", "")}" alt="Logo">' if channel_info.get('channelAvatarUrl') or channel_info.get('Channel_Photo_Url') else ''}
    <h1>@{channel_name}</h1>
    <p>{channel_info.get('channelTitle', channel_info.get('Channel_Name', ''))}</p>
    <div class="stats">
        <span>👥 {channel_info.get('subscribers', channel_info.get('Subscribers', '?')):,}</span>
        <span>📊 {len(posts)} پست</span>
        <span>📅 بروزرسانی: {iran_date_str}</span>
    </div>
</div>
'''

    for post in posts:
        post_id = str(post.get('postId') or post.get('Id', '?'))
        date = format_iran_time(post.get('date') or post.get('Date', ''))
        body = post.get('text') or post.get('Body', '')
        url = post.get('postUrl') or post.get('Url', '#')

        mentions = post.get('mentions', []) or []
        hashtags = post.get('hashtags', []) or []
        links = post.get('links', []) or []

        html += f'''
<div class="post">
    <div class="post-header">
        <span class="post-id">#{post_id}</span>
        <span class="post-date">📅 {date}</span>
    </div>
    <div class="post-body">{body}</div>
'''

        if mentions or hashtags or links:
            html += '<div class="meta">'
            if mentions:
                html += f'<span>🔗 منشن‌ها: {", ".join(mentions)}</span>'
            if hashtags:
                hashtag_html = " ".join([f'<span class="hashtag">{h}</span>' for h in hashtags])
                html += f'<span>🏷️ {hashtag_html}</span>'
            if links:
                links_html = ", ".join([f'<a href="{l}">لینک</a>' for l in links])
                html += f'<span>🌐 لینک‌ها: {links_html}</span>'
            html += '</div>'

        # نمایش همه مدیاها
        if post_id in media_paths:
            for m_path in media_paths[post_id]:
                ext = m_path.split('.')[-1].lower()
                if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    html += f'<div class="media-container"><img src="{m_path}" loading="lazy" alt="media"></div>'
                elif ext in ['mp4', 'webm', 'mov']:
                    html += f'<div class="media-container"><video controls><source src="{m_path}" type="video/{ext}"></video></div>'
                else:
                    html += f'<div class="media-container"><a href="{m_path}" target="_blank" style="color:#2a6df4;">📎 دانلود فایل ({ext.upper()})</a></div>'

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
        "channels": CHANNEL,
        "maxPosts": LIMIT,
        "daysRange": 30,
        "includeText": True,
        "mediaOnly": False,
        "downloadMedia": True   # مهم‌ترین گزینه
    }

    print(f"🚀 Starting scrape with better Actor @{CHANNEL} | Limit: {LIMIT}")

    run = client.actor(ACTOR_ID).call(run_input=run_input, wait_duration=timedelta(minutes=15))

    if not run or run.status != 'SUCCEEDED':
        print(f"❌ Run failed! Status: {run.status if run else 'None'}")
        sys.exit(1)

    print(f"✅ Scrape succeeded. Dataset: {run.default_dataset_id} | KVS: {run.default_key_value_store_id}")

    dataset = client.dataset(run.default_dataset_id)
    items = list(dataset.iterate_items())

    if not items:
        print("⚠️ No posts found!")
        return

    channel_info = items[0]
    media_map = {}
    downloaded_count = 0
    skipped_count = 0
    kvs_id = run.default_key_value_store_id

    def download_media_for_post(item):
        nonlocal downloaded_count, skipped_count
        msg_id = str(item.get('postId') or item.get('Id', 'unknown'))
        local_paths = []

        media_items = item.get('media', []) or item.get('mediaAttachments', [])

        for idx, media in enumerate(media_items):
            key = media.get('storeKey') or media.get('key') or None
            if not key:
                url = media.get('url') or media.get('mediaUrl')
                if url and url.startswith('http'):
                    print(f"   ⚠️ No KVS key, trying direct URL for post {msg_id}")
                continue

            ext = key.split('.')[-1].lower() if '.' in key else 'bin'
            filename = f"post_{msg_id}_{idx}.{ext}"
            filepath = os.path.join(MEDIA_DIR, filename)
            rel_path = f"media/{filename}"

            if os.path.exists(filepath):
                local_paths.append(rel_path)
                continue

            print(f"⬇️ Downloading from KVS for post {msg_id}: {filename}")
            success, size = download_from_kvs(client, kvs_id, key, filepath, MAX_MEDIA_SIZE_BYTES)
            if success:
                downloaded_count += 1
                local_paths.append(rel_path)
            else:
                skipped_count += 1

        return msg_id, local_paths

    with ThreadPoolExecutor(max_workers=10) as executor:
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
    print(f"   ⏩ Skipped: {skipped_count}")

if __name__ == "__main__":
    main()
