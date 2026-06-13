#!/usr/bin/env python3
import os, sys, json, subprocess, requests, zipfile
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

def extract_simple_metadata(post):
    return {
        "shortcode": post.get("shortcode"),
        "username": post.get("owner_username", "unknown"),
        "caption": post.get("caption", ""),
        "like_count": post.get("like_count", 0),
        "comment_count": post.get("comment_count", 0)
    }

def extract_metadata_from_ytdlp(shortcode, cookies_file=None):
    url = f"https://www.instagram.com/p/{shortcode}/"
    cmd = ["yt-dlp", "--dump-json", "--no-playlist", url]
    if cookies_file and Path(cookies_file).exists():
        cmd.extend(["--cookies", cookies_file])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        return {
            "shortcode": shortcode,
            "username": info.get("uploader", "unknown"),
            "caption": info.get("description", ""),
            "like_count": info.get("like_count", 0),
            "comment_count": info.get("comment_count", 0)
        }
    except Exception as e:
        print(f"⚠️ خطا در دریافت متادیتا از yt-dlp: {e}")
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
    cmd = ["yt-dlp", "--no-playlist", "-o", f"{output_dir}/%(title)s.%(ext)s", url]
    if cookies_file and Path(cookies_file).exists():
        cmd.extend(["--cookies", cookies_file])
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ yt-dlp خطا: {e.stderr}")
        return False

def save_metadata(download_dir, metadata):
    if not metadata:
        return
    with open(download_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    simple = {
        "shortcode": metadata.get("shortcode"),
        "username": metadata.get("username", "unknown")
    }
    with open(download_dir / "post_info.json", "w", encoding="utf-8") as f:
        json.dump(simple, f, indent=2)

def main():
    if len(sys.argv) != 2:
        print("Usage: python download_with_fallback.py <shortcode>")
        sys.exit(1)

    shortcode = sys.argv[1]
    print(f"🔍 شروع دانلود برای shortcode: {shortcode}")

    post = find_post_by_shortcode(shortcode)
    metadata = None
    media_urls = []
    username = "unknown"
    post_type = ""

    if post:
        post_type = post.get("post_type", "")
        # ========== اصلاح برای ویدیوها ==========
        if post_type == "VIDEO":
            print("📹 پست ویدیویی است؛ مرحله اول (media_urls) رد می‌شود و مستقیماً yt-dlp استفاده می‌گردد.")
            media_urls = []   # خالی کردن تا مرحله اول انجام نشود
        else:
            media_urls = post.get("media_urls", [])
        username = post.get("owner_username", "unknown")
        print(f"📄 پست در JSON یافت شد. owner: {username}, post_type: {post_type}, media_urls: {len(media_urls)}")
        metadata = extract_simple_metadata(post)
    else:
        print("⚠️ پست در فایل‌های JSON یافت نشد. تلاش برای دریافت متادیتا از yt-dlp...")

    download_dir = Path("instagram_downloads") / shortcode
    download_dir.mkdir(parents=True, exist_ok=True)

    success = False
    method = ""

    # ---------- مرحله ۱: دانلود مستقیم از media_urls (فقط برای عکس و کاروسل) ----------
    if media_urls:
        if download_media_urls(media_urls, download_dir, shortcode, post_type):
            success = True
            method = "media_urls"

    # ---------- مرحله ۲: در صورت عدم موفقیت، yt-dlp بدون کوکی ----------
    if not success:
        print("🔄 مرحله ۲: تلاش با yt-dlp (بدون کوکی)...")
        if download_ytdlp(shortcode, download_dir):
            success = True
            method = "yt-dlp_no_cookie"
            if metadata is None:
                metadata = extract_metadata_from_ytdlp(shortcode)

    # ---------- مرحله ۳: در صورت عدم موفقیت، yt-dlp با کوکی ----------
    if not success:
        cookies_path = os.environ.get("INSTAGRAM_COOKIES_PATH")
        if cookies_path and Path(cookies_path).exists():
            print("🍪 مرحله ۳: تلاش با yt-dlp + کوکی...")
            if download_ytdlp(shortcode, download_dir, cookies_path):
                success = True
                method = "yt-dlp_with_cookie"
                if metadata is None:
                    metadata = extract_metadata_from_ytdlp(shortcode, cookies_path)
        else:
            print("⚠️ فایل کوکی در دسترس نیست. مرحله ۳ رد شد.")

    if success:
        if metadata is None:
            metadata = {
                "shortcode": shortcode,
                "username": username,
                "caption": "",
                "like_count": 0,
                "comment_count": 0
            }
        save_metadata(download_dir, metadata)
        with open(download_dir / "info.txt", "w", encoding="utf-8") as f:
            f.write(f"Method: {method}\nShortcode: {shortcode}\nUsername: {metadata.get('username')}\n")
        print(f"🎉 دانلود نهایی موفق برای {shortcode}")
    else:
        print(f"💥 همه روش‌ها شکست خوردند: {shortcode}")
        sys.exit(1)

if __name__ == "__main__":
    main()
