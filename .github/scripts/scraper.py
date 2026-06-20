#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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

# ═══════════════════ تنظیمات از متغیرهای محیطی ═══════════════════
APIFY_TOKEN = os.environ.get('APIFY_TOKEN') or os.environ.get('APIFY_API_TOKEN', '')
if not APIFY_TOKEN:
    print("❌ APIFY_TOKEN is empty! Set it as environment variable.")
    sys.exit(1)

CHANNEL = os.environ.get('CHANNEL', 'bbcpersian').lstrip('@')
LIMIT = int(os.environ.get('POST_LIMIT', '10'))
MAX_MEDIA_SIZE_MB = int(os.environ.get('MAX_MEDIA_SIZE_MB', '80'))

ACTOR_ID = "thescrapelab/Apify-Telegram-Scraper"

# پوشه‌های خروجی
BASE_DIR = os.path.join("Download", "telegram_downloads", CHANNEL)
MEDIA_DIR = os.path.join(BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

MAX_MEDIA_SIZE_BYTES = MAX_MEDIA_SIZE_MB * 1024 * 1024
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# ═══════════════════ توابع کمکی ═══════════════════

def get_remote_file_size(url):
    """دریافت حجم فایل از هدر Content-Length بدون دانلود."""
    try:
        resp = requests.head(url, timeout=10, allow_redirects=True, headers=HEADERS)
        length = resp.headers.get('Content-Length')
        if length and length.isdigit():
            return int(length)
    except:
        pass
    return None

def download_file(url, save_path, max_bytes=None):
    """
    دانلود فایل با بررسی حجم.
    اگر max_bytes مشخص باشد و حجم بیشتر باشد، دانلود نمی‌کند.
    """
    if max_bytes:
        size = get_remote_file_size(url)
        if size is not None and size > max_bytes:
            print(f"⏩ Skipped (size {size/1024/1024:.1f} MB > {MAX_MEDIA_SIZE_MB} MB)")
            return False, size

    for attempt in range(5):
        try:
            r = requests.get(url, stream=True, timeout=60, headers=HEADERS)
            if r.status_code == 200:
                downloaded = 0
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if max_bytes and downloaded > max_bytes:
                            f.close()
                            os.remove(save_path)
                            print(f"⏩ Stopped: exceeded {MAX_MEDIA_SIZE_MB} MB during download")
                            return False, downloaded
                return True, downloaded
            else:
                print(f"   ⚠️ HTTP {r.status_code}")
        except Exception as e:
            print(f"   ⚠️ Download error (attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)
    print(f"   ❌ Failed: {url[:100]}...")
    return False, 0

def format_iran_time(iso_date_str):
    """تبدیل تاریخ ISO به زمان ایران (+3:30)."""
    try:
        dt = datetime.fromisoformat(iso_date_str.replace('Z', '+00:00'))
        iran_dt = dt + timedelta(hours=3, minutes=30)
        return iran_dt.strftime('%Y/%m/%d - %H:%M')
    except:
        return iso_date_str

def generate_html(posts, channel_name, media_map):
    """
    تولید فایل HTML کامل با نمایش تمام اطلاعات هر پست (به جز دیتای خام).
    """
    current_iran = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).strftime('%Y/%m/%d - %H:%M')

    html = f'''<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>@{channel_name} - آخرین پست‌ها</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; color: #1c1e21; direction: rtl; }}
        .header {{ background: linear-gradient(135deg, #2a6df4, #1e4fcf); color: white; padding: 25px; border-radius: 16px; margin-bottom: 30px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; }}
        .header h1 {{ margin: 5px 0; font-size: 24px; }}
        .stats {{ display: flex; justify-content: center; gap: 30px; margin: 15px 0; font-size: 14px; opacity: 0.9; }}
        .post {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); border-right: 4px solid #2a6df4; }}
        .post-header {{ display: flex; justify-content: space-between; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid #eee; }}
        .post-body {{ font-size: 16px; line-height: 2; white-space: pre-wrap; word-break: break-word; }}
        .meta {{ background: #f8f9fa; padding: 12px; border-radius: 8px; font-size: 13px; margin: 10px 0; }}
        .meta span {{ margin-left: 15px; }}
        .hashtag {{ color: #1e4fcf; background: #e7f0ff; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
        .media-container {{ margin-top: 15px; text-align: center; }}
        .media-container img, .media-container video {{ max-width: 100%; max-height: 400px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .post-url {{ display: inline-block; margin-top: 10px; background: #2a6df4; color: white !important; padding: 6px 14px; border-radius: 6px; font-size: 13px; text-decoration: none; }}
        .footer {{ text-align: center; margin-top: 40px; color: #65676b; font-size: 12px; border-top: 1px solid #ddd; padding-top: 15px; }}
    </style>
</head>
<body>
<div class="header">
    <h1>@{channel_name}</h1>
    <div class="stats">
        <span>📊 {len(posts)} پست</span>
        <span>📅 بروزرسانی: {current_iran}</span>
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
        <span>#{post_id}</span>
        <span>📅 {date}</span>
    </div>
    <div class="post-body">{body}</div>
'''

        # متا (منشن‌ها، هشتگ‌ها، لینک‌های خروجی)
        if mentions or hashtags or outlinks:
            html += '<div class="meta">'
            if mentions:
                html += f'<span>🔗 منشن‌ها: {", ".join(mentions)}</span>'
            if hashtags:
                html += '<span>🏷️ ' + ' '.join([f'<span class="hashtag">{h}</span>' for h in hashtags]) + '</span>'
            if outlinks:
                html += '<span>🌐 لینک‌های خروجی: ' + ', '.join([f'<a href="{l}">لینک</a>' for l in outlinks]) + '</span>'
            html += '</div>'

        # مدیاهای دانلود شده
        if str(post_id) in media_map:
            for m_path in media_map[str(post_id)]:
                ext = m_path.split('.')[-1].lower()
                if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    html += f'<div class="media-container"><img src="{m_path}" loading="lazy" alt="media"></div>'
                elif ext in ['mp4', 'webm', 'mov']:
                    html += f'<div class="media-container"><video controls><source src="{m_path}"></video></div>'
                elif ext in ['mp3', 'ogg', 'wav']:
                    html += f'<div class="media-container"><audio controls><source src="{m_path}"></audio></div>'
                else:
                    html += f'<div class="media-container"><a href="{m_path}">📎 {ext.upper()}</a></div>'

        # لینک پست
        html += f'<a href="{url}" target="_blank" class="post-url">🔗 مشاهده در تلگرام</a>'

        html += '</div>\n'   # بستن .post

    html += '''
<div class="footer">
    تولید شده توسط scraper در تاریخ ''' + current_iran + '''
</div>
</body>
</html>'''
    return html

def create_zip_archive(base_dir, channel):
    """ساخت فایل ZIP از کل پوشه خروجی."""
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

# ═══════════════════ تابع اصلی ═══════════════════

def main():
    print(f"🚀 Starting scraper for @{CHANNEL} | Limit: {LIMIT}")

    client = ApifyClient(APIFY_TOKEN)

    run_input = {
        "channels": [{
            "channelName": CHANNEL,
            "startId": 0,          # از آخرین (جدیدترین) پست شروع کن
            "limit": LIMIT
        }]
    }

    run = client.actor(ACTOR_ID).call(
        run_input=run_input,
        wait_duration=timedelta(minutes=5)
    )

    if run is None or run.status != 'SUCCEEDED':
        print(f"❌ Run failed! Status: {run.status if run else 'None'}")
        sys.exit(1)

    print(f"✅ Run succeeded. Dataset ID: {run.default_dataset_id}")
    dataset = client.dataset(run.default_dataset_id)
    items = list(dataset.iterate_items())

    if not items:
        print("⚠️ No posts found!")
        return

    # مرتب‌سازی بر اساس تاریخ (جدیدترین اول) – اطمینان
    items.sort(key=lambda x: x.get('Date', ''), reverse=True)

    print(f"📥 Received {len(items)} posts")

    # ─── دانلود مدیاها ───
    media_map = {}
    downloaded_count = 0

    for item in items:
        post_id = str(item.get('Id', 'unknown'))
        media_list = item.get('media', []) or []

        # برخی خروجی‌های قدیمی ممکن است MediaUrl داشته باشند
        if not media_list and item.get('MediaUrl'):
            media_list = [{
                'url': item['MediaUrl'],
                'mediaType': item.get('MediaType', 'unknown')
            }]

        for idx, media in enumerate(media_list):
            url = media.get('url')
            if not url:
                continue

            # تشخیص پسوند
            parsed = urlparse(url)
            path_part = unquote(parsed.path).split('/')[-1]
            if '.' in path_part:
                ext = path_part.split('.')[-1].split('?')[0][:10].lower()
            else:
                mtype = str(media.get('mediaType', '')).lower()
                if 'photo' in mtype or 'image' in mtype:
                    ext = 'jpg'
                elif 'video' in mtype:
                    ext = 'mp4'
                elif 'audio' in mtype or 'voice' in mtype:
                    ext = 'mp3'
                else:
                    ext = 'file'

            filename = f"post_{post_id}_{idx}.{ext}"
            filepath = os.path.join(MEDIA_DIR, filename)
            rel_path = f"media/{filename}"

            if os.path.exists(filepath):
                media_map.setdefault(post_id, []).append(rel_path)
                continue

            print(f"⬇️ Downloading: {filename} ...")
            success, size = download_file(url, filepath, MAX_MEDIA_SIZE_BYTES)
            if success:
                downloaded_count += 1
                media_map.setdefault(post_id, []).append(rel_path)
                print(f"   ✅ Done ({size/1024/1024:.1f} MB)")
            else:
                print(f"   ⏩ Skipped/failed")

    # ─── ذخیره خروجی‌ها ───
    json_path = os.path.join(BASE_DIR, 'posts.json')
    csv_path = os.path.join(BASE_DIR, 'posts.csv')
    html_path = os.path.join(BASE_DIR, 'posts.html')

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    # CSV با فیلدهای اصلی
    if items:
        fieldnames = ['Id', 'Date', 'Body', 'Url', 'Mentions', 'Hashtags', 'Outlinks']
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for item in items:
                # تبدیل لیست‌ها به رشته برای CSV
                row = item.copy()
                for k in ['Mentions', 'Hashtags', 'Outlinks']:
                    if isinstance(row.get(k), list):
                        row[k] = ', '.join(row[k])
                writer.writerow(row)

    html_content = generate_html(items, CHANNEL, media_map)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # ─── ساخت ZIP ───
    zip_name = create_zip_archive(BASE_DIR, CHANNEL)

    print(f"\n🎉 Finished @{CHANNEL}!")
    print(f"   📊 Posts: {len(items)}")
    print(f"   🖼️ Media downloaded: {downloaded_count}")
    print(f"   📁 Output: {BASE_DIR}/")
    print(f"      ├── posts.json  (همه اطلاعات خام)")
    print(f"      ├── posts.csv   (خلاصه)")
    print(f"      ├── posts.html  (نمایش کامل بدون دیتای خام)")
    print(f"      ├── media/      (فایل‌های دانلود شده)")
    print(f"      └── {zip_name}  (بایگانی کامل)")

if __name__ == "__main__":
    main()