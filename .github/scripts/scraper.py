#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import csv
import requests
import time
import zipfile
import subprocess
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, unquote
from apify_client import ApifyClient

# ═══════════════════ تنظیمات ═══════════════════
APIFY_TOKEN = os.environ.get('APIFY_TOKEN') or os.environ.get('APIFY_API_TOKEN', '')
if not APIFY_TOKEN:
    print("❌ APIFY_TOKEN is empty!")
    sys.exit(1)

CHANNEL = os.environ.get('CHANNEL', 'bbcpersian').lstrip('@')
LIMIT = int(os.environ.get('POST_LIMIT', '10'))
MAX_MEDIA_SIZE_MB = int(os.environ.get('MAX_MEDIA_SIZE_MB', '80'))

ACTOR_ID = "ahaham_bytiz/telegram-channel-scraper"

BASE_DIR = os.path.join("Download", "telegram_downloads", CHANNEL)
MEDIA_DIR = os.path.join(BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

MAX_MEDIA_SIZE_BYTES = MAX_MEDIA_SIZE_MB * 1024 * 1024
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# ═══════════════════ توابع کمکی ═══════════════════

def get_remote_file_size(url):
    try:
        resp = requests.head(url, timeout=10, allow_redirects=True, headers=HEADERS)
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
    try:
        dt = datetime.fromisoformat(iso_date_str.replace('Z', '+00:00'))
        iran_dt = dt + timedelta(hours=3, minutes=30)
        return iran_dt.strftime('%Y/%m/%d - %H:%M')
    except:
        return iso_date_str

def generate_html(posts, channel_name, media_map):
    current_iran = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).strftime('%Y/%m/%d - %H:%M')

    print(f"🔍 media_map keys: {list(media_map.keys())}")
    for key, val in media_map.items():
        print(f"   {key} -> {val}")

    html = f'''<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>@{channel_name} - آخرین پست‌ها</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; color: #1c1e21; direction: rtl; }}
        .header {{ background: linear-gradient(135deg, #2a6df4, #1e4fcf); color: white; padding: 25px; border-radius: 16px; margin-bottom: 30px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; }}
        .header h1 {{ margin: 5px 0; font-size: 24px; }}
        .stats {{ display: flex; justify-content: center; gap: 30px; margin: 15px 0; font-size: 14px; opacity: 0.9; }}
        .post {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 25px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); border-right: 4px solid #2a6df4; }}
        .post-header {{ display: flex; justify-content: space-between; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid #eee; }}
        .post-body {{ font-size: 16px; line-height: 2; white-space: pre-wrap; word-break: break-word; }}
        .meta {{ background: #f8f9fa; padding: 12px; border-radius: 8px; font-size: 13px; margin: 10px 0; }}
        .meta span {{ margin-left: 15px; }}
        .hashtag {{ color: #1e4fcf; background: #e7f0ff; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
        .media-container {{ margin-top: 15px; display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; }}
        .media-item {{ background: #fafafa; border-radius: 10px; padding: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.05); max-width: 100%; text-align: center; }}
        .media-item img, .media-item video {{ max-width: 100%; max-height: 400px; border-radius: 8px; }}
        .media-item audio {{ width: 100%; max-width: 300px; }}
        .media-item a {{ display: inline-block; background: #2a6df4; color: white; padding: 6px 14px; border-radius: 6px; text-decoration: none; font-size: 13px; }}
        .no-media {{ color: #999; font-size: 14px; padding: 10px; background: #f9f9f9; border-radius: 8px; }}
        .post-url {{ display: inline-block; margin-top: 15px; background: #2a6df4; color: white !important; padding: 6px 14px; border-radius: 6px; font-size: 13px; text-decoration: none; }}
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

    for idx, post in enumerate(posts):
        temp_id = f"post_{idx}"
        date = format_iran_time(post.get('date') or post.get('Date', ''))
        body = post.get('text') or post.get('Body', '')
        url = post.get('url') or post.get('Url', '#')
        mentions = post.get('mentions') or []
        hashtags = post.get('hashtags') or []
        outlinks = post.get('outlinks') or []

        print(f"🔍 HTML temp_id: {temp_id} | in media_map? {temp_id in media_map}")

        html += f'''
<div class="post">
    <div class="post-header">
        <span>#{idx+1}</span>
        <span>📅 {date}</span>
    </div>
    <div class="post-body">{body}</div>
'''

        if mentions or hashtags or outlinks:
            html += '<div class="meta">'
            if mentions:
                html += f'<span>🔗 منشن‌ها: {", ".join(mentions)}</span>'
            if hashtags:
                html += '<span>🏷️ ' + ' '.join([f'<span class="hashtag">{h}</span>' for h in hashtags]) + '</span>'
            if outlinks:
                html += '<span>🌐 لینک‌های خروجی: ' + ', '.join([f'<a href="{l}">لینک</a>' for l in outlinks]) + '</span>'
            html += '</div>'

        html += '<div class="media-container">'
        if temp_id in media_map:
            for m_path in media_map[temp_id]:
                ext = m_path.split('.')[-1].lower()
                if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    html += f'<div class="media-item"><img src="{m_path}" loading="lazy" alt="media"></div>'
                elif ext in ['mp4', 'webm', 'mov']:
                    html += f'<div class="media-item"><video controls><source src="{m_path}"></video></div>'
                elif ext in ['mp3', 'ogg', 'wav']:
                    html += f'<div class="media-item"><audio controls><source src="{m_path}"></audio></div>'
                else:
                    html += f'<div class="media-item"><a href="{m_path}">📎 {ext.upper()}</a></div>'
        else:
            html += '<div class="no-media">⚠️ بدون مدیا</div>'
        html += '</div>'

        html += f'<a href="{url}" target="_blank" class="post-url">🔗 مشاهده در تلگرام</a>'
        html += '</div>\n'

    html += '''
<div class="footer">
    تولید شده توسط scraper در تاریخ ''' + current_iran + '''
</div>
</body>
</html>'''
    return html

# ═══════════════════ تابع پاکسازی فایل‌های قدیمی ═══════════════════

def cleanup_old_media(base_dir, media_map):
    """
    حذف فایل‌های مدیایی که در آخرین scrape مورد نیاز نیستند.
    """
    media_dir = os.path.join(base_dir, "media")
    if not os.path.exists(media_dir):
        return

    # مجموعه اسامی فایل‌های مورد نیاز (فقط نام فایل، نه مسیر کامل)
    needed_files = set()
    for media_list in media_map.values():
        for rel_path in media_list:
            filename = os.path.basename(rel_path)
            needed_files.add(filename)

    # پیمایش فایل‌های موجود در پوشه media
    removed_count = 0
    for filename in os.listdir(media_dir):
        filepath = os.path.join(media_dir, filename)
        if os.path.isfile(filepath):
            # اگر فایل در لیست نیازمندی‌ها نبود، حذف کن
            if filename not in needed_files:
                os.remove(filepath)
                removed_count += 1
                print(f"🗑️ Removed old media: {filename}")

    if removed_count:
        print(f"🧹 Cleaned up {removed_count} old media file(s).")
    else:
        print("✅ No old media files to clean up.")

# ═══════════════════ تابع زیپ با تقسیم صحیح ═══════════════════

def create_zip_archive(base_dir, channel):
    zip_name = f"{channel}_full_archive.zip"
    zip_path = os.path.join(base_dir, zip_name)

    # حذف فایل‌های قبلی (قطعات قدیمی)
    for f in os.listdir(base_dir):
        if f.startswith(channel + "_full_archive") and (f.endswith(".zip") or f.endswith(".z01") or f.endswith(".z02") or f.endswith(".z03")):
            os.remove(os.path.join(base_dir, f))

    # ساخت یک فایل زیپ موقت با محتوای مورد نظر (با استفاده از zipfile پایتون)
    temp_zip = os.path.join(base_dir, "temp_full.zip")
    with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file == "temp_full.zip" or file == zip_name:
                    continue
                # فقط فایل‌های html, json, csv و محتویات پوشه‌ی media را اضافه کن
                if file.endswith(('.html', '.json', '.csv')) or 'media' in root:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, base_dir)
                    zipf.write(file_path, arcname)

    size_mb = os.path.getsize(temp_zip) / (1024 * 1024)
    print(f"✅ Temporary ZIP created: {size_mb:.1f} MB")

    MAX_SPLIT_MB = 30

    if size_mb > MAX_SPLIT_MB:
        print(f"📦 Splitting into {MAX_SPLIT_MB} MB parts with WinRAR-compatible format...")
        cmd = [
            "zip",
            "-s", f"{MAX_SPLIT_MB}m",
            temp_zip,
            "--out", zip_path
        ]
        subprocess.run(cmd, check=True)
        os.remove(temp_zip)
        print(f"✅ Split completed. Parts: {zip_path}, {zip_path}.z01, ...")
    else:
        os.rename(temp_zip, zip_path)
        print(f"ℹ️ ZIP size is acceptable, no split needed.")

    return zip_name

# ═══════════════════ تابع اصلی ═══════════════════

def main():
    print(f"🚀 Starting scraper for @{CHANNEL} | Limit: {LIMIT}")

    client = ApifyClient(APIFY_TOKEN)

    run_input = {
        "channels": [CHANNEL],
        "maxMessagesPerChannel": LIMIT,
        "includeMedia": True,
        "enableReactions": False,
        "enableViews": True
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

    items.sort(key=lambda x: x.get('date') or x.get('Date', ''), reverse=True)
    print(f"📥 Received {len(items)} posts")

    # ─── دانلود مدیاها ───
    media_map = {}
    downloaded_count = 0

    for idx, item in enumerate(items):
        temp_id = f"post_{idx}"
        print(f"📌 Processing post index {idx} (temp_id: {temp_id})")
        media_list = []

        for key in ['photos', 'videos', 'documents', 'audio']:
            if key in item and item[key]:
                if isinstance(item[key], list):
                    for m in item[key]:
                        if isinstance(m, dict) and m.get('url'):
                            media_list.append(m)
                        elif isinstance(m, str) and m.startswith('http'):
                            media_list.append({'url': m})
                elif isinstance(item[key], str) and item[key].startswith('http'):
                    media_list.append({'url': item[key]})

        if not media_list and 'media' in item:
            if isinstance(item['media'], list):
                media_list = item['media']
            elif isinstance(item['media'], str) and item['media'].startswith('http'):
                media_list = [{'url': item['media']}]

        print(f"   📎 Found {len(media_list)} media items")

        for mi, media in enumerate(media_list):
            if isinstance(media, str):
                url = media
            else:
                url = media.get('url') or media.get('Url') or media.get('link') or ''

            if not url:
                continue

            parsed = urlparse(url)
            path_part = unquote(parsed.path).split('/')[-1]
            if '.' in path_part and len(path_part.split('.')[-1]) <= 5:
                ext = path_part.split('.')[-1].split('?')[0][:10].lower()
            else:
                media_type = media.get('type') or media.get('mediaType') or ''
                if 'photo' in media_type.lower() or 'image' in media_type.lower():
                    ext = 'jpg'
                elif 'video' in media_type.lower():
                    ext = 'mp4'
                elif 'audio' in media_type.lower() or 'voice' in media_type.lower():
                    ext = 'mp3'
                elif 'document' in media_type.lower():
                    ext = 'file'
                else:
                    ext = 'bin'

            filename = f"{temp_id}_{mi}.{ext}"
            filepath = os.path.join(MEDIA_DIR, filename)
            rel_path = f"media/{filename}"

            if os.path.exists(filepath):
                media_map.setdefault(temp_id, []).append(rel_path)
                print(f"   ⏩ Already exists: {filename}")
                continue

            print(f"⬇️ Downloading: {filename} ...")
            success, size = download_file(url, filepath, MAX_MEDIA_SIZE_BYTES)
            if success:
                downloaded_count += 1
                media_map.setdefault(temp_id, []).append(rel_path)
                print(f"   ✅ Done ({size/1024/1024:.1f} MB)")
            else:
                print(f"   ⏩ Skipped/failed")

    # ─── پاکسازی فایل‌های مدیای قدیمی ───
    cleanup_old_media(BASE_DIR, media_map)

    # ─── ذخیره خروجی‌ها ───
    json_path = os.path.join(BASE_DIR, 'posts.json')
    csv_path = os.path.join(BASE_DIR, 'posts.csv')
    html_path = os.path.join(BASE_DIR, 'posts.html')

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    if items:
        sample_keys = set()
        for item in items:
            sample_keys.update(item.keys())
        important_fields = ['id', 'date', 'text', 'url', 'views', 'forwards', 'replies']
        fieldnames = [f for f in important_fields if f in sample_keys]
        for f in ['mentions', 'hashtags', 'outlinks']:
            if f in sample_keys:
                fieldnames.append(f)

        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for item in items:
                row = {}
                for k in fieldnames:
                    val = item.get(k)
                    if isinstance(val, list):
                        val = ', '.join(str(v) for v in val)
                    row[k] = val
                writer.writerow(row)

    html_content = generate_html(items, CHANNEL, media_map)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # ─── ساخت زیپ ───
    zip_name = create_zip_archive(BASE_DIR, CHANNEL)

    # ─── گزارش نهایی ───
    print(f"\n🎉 Finished @{CHANNEL}!")
    print(f"   📊 Posts: {len(items)}")
    print(f"   🖼️ Media downloaded: {downloaded_count}")
    print(f"   📁 Output: {BASE_DIR}/")
    print(f"      ├── posts.json  (همه اطلاعات خام)")
    print(f"      ├── posts.csv   (خلاصه)")
    print(f"      ├── posts.html  (نمایش کامل با مدیاها)")
    print(f"      ├── media/      (فایل‌های دانلود شده)")

    zip_full_path = os.path.join(BASE_DIR, zip_name)
    if os.path.exists(zip_full_path):
        size = os.path.getsize(zip_full_path)
        if size < 1024 * 1024 and any(f.startswith(zip_name + ".z") for f in os.listdir(BASE_DIR)):
            parts = sorted([f for f in os.listdir(BASE_DIR) if f.startswith(zip_name) and f != zip_name])
            print(f"      └── {zip_name} (تقسیم شده به {len(parts)+1} قطعهٔ ۳۰ مگابایتی، قابل باز شدن با وین‌رر):")
            print(f"           ├── {zip_name}")
            for p in parts:
                print(f"           ├── {p}")
        else:
            print(f"      └── {zip_name} (حجم {size/1024/1024:.1f} MB)")
    else:
        print("      └── (هیچ فایل زیپی یافت نشد)")

if __name__ == "__main__":
    main()
