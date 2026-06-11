#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import json
import glob
import subprocess
import requests
import zipfile
from pathlib import Path
from io import BytesIO

def find_post_by_shortcode(shortcode):
    """جستجوی shortcode در همه فایل‌های JSON داخل instagram_data (ساختار recent_posts)"""
    data_dir = Path("instagram_data")
    if not data_dir.exists():
        return None

    for json_file in data_dir.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                content = f.read()
                # حذف خط اول timestamp اگر وجود داشت
                lines = content.split("\n", 1)
                if len(lines) > 1 and lines[0].strip().isdigit():
                    data = json.loads(lines[1])
                else:
                    data = json.loads(content)

            if "recent_posts" in data:
                for post in data["recent_posts"]:
                    if post.get("shortcode") == shortcode:
                        return post
            if data.get("shortcode") == shortcode:
                return data
        except:
            continue
    return None

def download_media_urls(media_urls, download_dir, shortcode, post_type):
    """دانلود مستقیم از media_urls (تکی یا ZIP برای کاروسل)"""
    if not media_urls:
        return False
    print(f"🖼️ دانلود از media_urls (تعداد: {len(media_urls)})...")

    if len(media_urls) > 1 or post_type == "CAROUSEL_ALBUM":
        # ایجاد ZIP
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED, False) as zf:
            for idx, url in enumerate(media_urls, start=1):
                try:
                    ext = 'jpg' if '.mp4' not in url and 'video' not in url else 'mp4'
                    fname = f"{shortcode}_{idx}.{ext}"
                    resp = requests.get(url, stream=True, timeout=30)
                    resp.raise_for_status()
                    zf.writestr(fname, resp.content)
                    print(f"   ✅ {fname} اضافه شد")
                except Exception as e:
                    print(f"   ❌ خطا در {url}: {e}")
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
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            print(f"✅ فایل ذخیره شد: {file_path}")
            return True
        except Exception as e:
            print(f"❌ دانلود مستقیم ناموفق: {e}")
            return False

def download_ytdlp(shortcode, output_dir, cookies_file=None):
    """دانلود با yt-dlp (اختیاری با کوکی)"""
    url = f"https://www.instagram.com/p/{shortcode}/"
    # --no-playlist و --no-overwrites برای اطمینان
    cmd = ["yt-dlp", "--no-playlist", "-o", f"{output_dir}/%(title)s.%(ext)s", url]
    if cookies_file and Path(cookies_file).exists():
        cmd.extend(["--cookies", cookies_file])
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ yt-dlp خطا: {e.stderr}")
        return False

def main():
    if len(sys.argv) != 2:
        print("Usage: python download_with_fallback.py <shortcode>")
        sys.exit(1)

    shortcode = sys.argv[1]
    print(f"🔍 شروع دانلود برای shortcode: {shortcode}")

    # پیدا کردن پست در JSONهای موجود
    post = find_post_by_shortcode(shortcode)
    media_urls = []
    username = "unknown"
    post_type = ""

    if post:
        media_urls = post.get("media_urls", [])
        username = post.get("owner_username", "unknown")
        post_type = post.get("post_type", "")
        print(f"📄 پست در JSON یافت شد. owner: {username}, media_urls: {len(media_urls)}")
    else:
        print("⚠️ پست در فایل‌های JSON یافت نشد. مستقیماً به yt-dlp می‌رویم.")

    # پوشه مقصد
    download_dir = Path("instagram_downloads") / shortcode
    download_dir.mkdir(parents=True, exist_ok=True)

    success = False

    # ---------- مرحله ۱: دانلود مستقیم از media_urls ----------
    if media_urls:
        if download_media_urls(media_urls, download_dir, shortcode, post_type):
            success = True
            method = "media_urls"
            print("✅ دانلود با لینک مستقیم موفق بود.")

    # ---------- مرحله ۲: در صورت عدم موفقیت، yt-dlp بدون کوکی ----------
    if not success:
        print("🔄 مرحله ۲: تلاش با yt-dlp (بدون کوکی)...")
        if download_ytdlp(shortcode, download_dir):
            success = True
            method = "yt-dlp_no_cookie"
            print("✅ دانلود با yt-dlp بدون کوکی موفق بود.")
            # سعی در دریافت username از خروجی yt-dlp (اختیاری)
            try:
                result = subprocess.run(["yt-dlp", "--dump-json", f"https://www.instagram.com/p/{shortcode}/"],
                                        capture_output=True, text=True)
                if result.returncode == 0:
                    info = json.loads(result.stdout)
                    username = info.get("uploader", username)
            except:
                pass

    # ---------- مرحله ۳: در صورت عدم موفقیت، yt-dlp با کوکی ----------
    if not success:
        cookies_path = os.environ.get("INSTAGRAM_COOKIES_PATH")
        if cookies_path and Path(cookies_path).exists():
            print("🍪 مرحله ۳: تلاش با yt-dlp + کوکی...")
            if download_ytdlp(shortcode, download_dir, cookies_path):
                success = True
                method = "yt-dlp_with_cookie"
                print("✅ دانلود با yt-dlp و کوکی موفق بود.")
                # استخراج username
                try:
                    result = subprocess.run(["yt-dlp", "--dump-json", f"https://www.instagram.com/p/{shortcode}/", "--cookies", cookies_path],
                                            capture_output=True, text=True)
                    if result.returncode == 0:
                        info = json.loads(result.stdout)
                        username = info.get("uploader", username)
                except:
                    pass
            else:
                print("❌ حتی با کوکی هم دانلود نشد.")
        else:
            print("⚠️ فایل کوکی در دسترس نیست. مرحله ۳ رد شد.")

    if success:
        # ذخیره post_info.json برای مرحله بعدی workflow
        with open(download_dir / "post_info.json", "w", encoding="utf-8") as f:
            json.dump({"shortcode": shortcode, "username": username}, f, indent=2)
        # همچنین یک info.txt برای جزئیات
        with open(download_dir / "info.txt", "w", encoding="utf-8") as f:
            f.write(f"Method: {method}\nShortcode: {shortcode}\nUsername: {username}\n")
        print(f"🎉 دانلود نهایی موفق برای {shortcode}")
    else:
        print(f"💥 همه روش‌ها شکست خوردند: {shortcode}")
        sys.exit(1)

if __name__ == "__main__":
    main()
