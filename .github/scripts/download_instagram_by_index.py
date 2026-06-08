#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import json
import subprocess
import requests
import zipfile
from pathlib import Path
from io import BytesIO

def find_post_in_all_data(shortcode):
    """جستجوی shortcode در تمام فایل‌های JSON داخل پوشه instagram_data"""
    data_dir = Path("instagram_data")
    if not data_dir.exists():
        print("⚠️ پوشه instagram_data وجود ندارد.")
        return None

    json_files = list(data_dir.glob("*.json"))
    print(f"📁 تعداد فایل‌های JSON در instagram_data: {len(json_files)}")
    if not json_files:
        print("⚠️ هیچ فایل JSON در پوشه instagram_data یافت نشد.")
        return None

    # مرتب‌سازی بر اساس تاریخ اصلاح (جدیدترین اول)
    json_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    for json_file in json_files:
        print(f"🔍 بررسی فایل: {json_file.name}")
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # بررسی اینکه آیا فایل با timestamp شروع شده (خط اول عدد)
                lines = content.split('\n', 1)
                if len(lines) > 1 and lines[0].strip().isdigit():
                    # حذف خط اول timestamp
                    data = json.loads(lines[1])
                else:
                    data = json.loads(content)

                # حالت 1: فایل شامل recent_posts است (خروجی استاندارد)
                if 'recent_posts' in data:
                    posts = data['recent_posts']
                    print(f"   تعداد پست‌های recent_posts: {len(posts)}")
                    for post in posts:
                        if post.get('shortcode') == shortcode:
                            print(f"   ✅ پیدا شد در recent_posts")
                            return post
                # حالت 2: خود فایل مستقیماً یک پست است
                if data.get('shortcode') == shortcode:
                    print(f"   ✅ پیدا شد (خود فایل)")
                    return data
        except json.JSONDecodeError as e:
            print(f"   ❌ خطا در JSON: {e}")
        except Exception as e:
            print(f"   ❌ خطای دیگر: {e}")
    print(f"❌ shortcode {shortcode} در هیچ فایلی یافت نشد.")
    return None

def download_from_media_urls(media_urls, download_dir, shortcode, post_type):
    if not media_urls:
        return False
    print(f"🖼️ دانلود از media_urls (تعداد: {len(media_urls)})...")
    
    if len(media_urls) > 1 or post_type == "CAROUSEL_ALBUM":
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED, False) as zip_file:
            for idx, url in enumerate(media_urls, start=1):
                try:
                    ext = 'jpg' if '.mp4' not in url and 'video' not in url else 'mp4'
                    fname = f"{shortcode}_{idx}.{ext}"
                    resp = requests.get(url, stream=True, timeout=30)
                    resp.raise_for_status()
                    zip_file.writestr(fname, resp.content)
                    print(f"  - {fname} اضافه شد")
                except Exception as e:
                    print(f"  ❌ خطا در {url}: {e}")
        zip_path = download_dir / f"{shortcode}.zip"
        with open(zip_path, 'wb') as f:
            f.write(zip_buffer.getvalue())
        print(f"✅ ZIP ذخیره شد: {zip_path}")
        return True
    else:
        url = media_urls[0]
        ext = 'jpg' if '.mp4' not in url and 'video' not in url else 'mp4'
        file_path = download_dir / f"{shortcode}.{ext}"
        try:
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            with open(file_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"✅ فایل ذخیره شد: {file_path}")
            return True
        except Exception as e:
            print(f"❌ خطا در دانلود: {e}")
            return False

def main():
    if len(sys.argv) != 2:
        print("Usage: python download_instagram_by_index.py <shortcode>")
        sys.exit(1)
    shortcode = sys.argv[1]
    print(f"🔍 شروع جستجو برای shortcode: {shortcode}")

    # پیدا کردن اطلاعات پست در پوشه instagram_data
    post = find_post_in_all_data(shortcode)
    
    if post:
        post_url = post.get('url', f"https://www.instagram.com/p/{shortcode}/")
        post_type = post.get('post_type', 'UNKNOWN')
        caption = post.get('caption', '')
        media_urls = post.get('media_urls', [])
        username = post.get('owner_username', 'unknown')
        print(f"📸 اطلاعات پست: {shortcode} - {post_type} - @{username}")
        if media_urls:
            print(f"   media_urls موجود است: {len(media_urls)} مورد")
        else:
            print("⚠️ media_urls وجود ندارد، تلاش با yt-dlp...")
    else:
        print(f"❌ shortcode {shortcode} در هیچ فایل JSON یافت نشد.")
        print("لطفاً ابتدا workflow دریافت پست را اجرا کنید.")
        sys.exit(1)

    download_dir = Path("instagram_downloads") / shortcode
    download_dir.mkdir(parents=True, exist_ok=True)

    downloaded = False

    # اولویت اول: استفاده از media_urls
    if media_urls:
        if download_from_media_urls(media_urls, download_dir, shortcode, post_type):
            downloaded = True
            with open(download_dir / "info.txt", 'w', encoding='utf-8') as f:
                f.write(f"Method: media_urls\nShortcode: {shortcode}\nUsername: {username}\nURL: {post_url}\nCaption: {caption}\n")
    else:
        # اگر media_urls نبود، yt-dlp را امتحان کن
        ytdlp_path = download_dir / f"{shortcode}_ytdlp.mp4"
        cmd = ["yt-dlp", "--no-playlist", "-o", str(ytdlp_path), post_url]
        try:
            subprocess.run(cmd, check=False, capture_output=True, text=True)
            if ytdlp_path.exists() and ytdlp_path.stat().st_size > 1024:
                downloaded = True
                with open(download_dir / "info.txt", 'w', encoding='utf-8') as f:
                    f.write(f"Method: yt-dlp\nShortcode: {shortcode}\nUsername: {username}\nURL: {post_url}\nCaption: {caption}\n")
        except Exception as e:
            print(f"⚠️ yt-dlp failed: {e}")

    if downloaded:
        with open(download_dir / "post_info.json", 'w', encoding='utf-8') as f:
            json.dump({"shortcode": shortcode, "username": username}, f, indent=2)
        print(f"🎉 دانلود موفق: {shortcode}")
    else:
        print(f"❌ دانلود ناموفق برای shortcode: {shortcode}")
        sys.exit(1)

if __name__ == '__main__':
    main()
