#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download one Instagram post by shortcode into:
Download/instagram_downloads/{username}/{shortcode}/

Username resolution order:
1) ISSUE_USERNAME env (from issue title @handle)
2) Apify fields: ownerUsername / owner_username / username
3) Parent JSON target_username (instagram_data/*_*.json)
4) yt-dlp uploader
"""
import os
import re
import sys
import json
import shutil
import subprocess
import requests
import zipfile
from pathlib import Path
from io import BytesIO


def post_shortcode(post: dict) -> str:
    for key in ("shortcode", "shortCode", "code"):
        v = post.get(key)
        if v:
            return str(v).strip()
    url = str(post.get("url") or "")
    m = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else ""


def post_username(post: dict) -> str:
    for key in ("ownerUsername", "owner_username", "username", "owner"):
        v = post.get(key)
        if isinstance(v, dict):
            v = v.get("username") or v.get("username")
        if v and str(v).strip() and str(v).strip().lower() != "unknown":
            return str(v).strip().lstrip("@")
    return ""


def find_post_by_shortcode(shortcode: str):
    """Return (post_dict, channel_username_or_empty)."""
    data_dir = Path("instagram_data")
    if not data_dir.exists():
        return None, ""

    for json_file in sorted(data_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.split("\n", 1)
            if len(lines) > 1 and lines[0].strip().isdigit():
                data = json.loads(lines[1])
            else:
                data = json.loads(content)

            channel = str(data.get("target_username") or "").strip().lstrip("@")

            if "recent_posts" in data:
                for post in data["recent_posts"]:
                    if post_shortcode(post) == shortcode:
                        return post, channel
            if post_shortcode(data) == shortcode:
                return data, channel
        except Exception:
            continue
    return None, ""


def extract_simple_metadata(post: dict, username: str) -> dict:
    return {
        "shortcode": post_shortcode(post) or post.get("shortcode"),
        "username": username,
        "caption": post.get("caption") or "",
        "like_count": post.get("likesCount") or post.get("like_count") or 0,
        "comment_count": post.get("commentsCount") or post.get("comment_count") or 0,
    }


def extract_metadata_from_ytdlp(shortcode, cookies_file=None):
    url = f"https://www.instagram.com/p/{shortcode}/"
    cmd = ["yt-dlp", "--dump-json", "--no-playlist", url]
    if cookies_file and Path(cookies_file).exists():
        cmd.extend(["--cookies", cookies_file])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        uploader = (info.get("uploader") or info.get("channel") or info.get("creator") or "").strip().lstrip("@")
        return {
            "shortcode": shortcode,
            "username": uploader or "unknown",
            "caption": info.get("description") or "",
            "like_count": info.get("like_count") or 0,
            "comment_count": info.get("comment_count") or 0,
        }
    except Exception as e:
        print(f"⚠️ خطا در دریافت متادیتا از yt-dlp: {e}")
        return None


def collect_media_urls(post: dict) -> list:
    urls = []
    for key in ("media_urls", "images", "displayUrl", "videoUrl", "video_url"):
        v = post.get(key)
        if isinstance(v, list):
            urls.extend([u for u in v if u])
        elif isinstance(v, str) and v.startswith("http"):
            urls.append(v)
    # dedupe preserve order
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def download_media_urls(media_urls, download_dir, shortcode, post_type):
    if not media_urls:
        return False
    print(f"🖼️ دانلود از media_urls (تعداد: {len(media_urls)})...")
    multi = len(media_urls) > 1 or str(post_type).upper() in ("CAROUSEL_ALBUM", "SIDECAR")
    if multi:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zf:
            for idx, url in enumerate(media_urls, start=1):
                try:
                    ext = "mp4" if (".mp4" in url or "video" in url.lower()) else "jpg"
                    fname = f"{shortcode}_{idx}.{ext}"
                    resp = requests.get(url, stream=True, timeout=60)
                    resp.raise_for_status()
                    zf.writestr(fname, resp.content)
                    print(f"   ✅ {fname} اضافه شد")
                except Exception as e:
                    print(f"   ❌ خطا در {url}: {e}")
        zip_path = download_dir / f"{shortcode}.zip"
        with open(zip_path, "wb") as f:
            f.write(zip_buffer.getvalue())
        print(f"✅ ZIP ذخیره شد: {zip_path}")
        return True

    url = media_urls[0]
    ext = "mp4" if (".mp4" in url or "video" in url.lower()) else "jpg"
    file_path = download_dir / f"{shortcode}.{ext}"
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        with open(file_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        print(f"✅ فایل ذخیره شد: {file_path}")
        return True
    except Exception as e:
        print(f"❌ دانلود مستقیم ناموفق: {e}")
        return False


def download_ytdlp(shortcode, output_dir, cookies_file=None):
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
        "username": metadata.get("username", "unknown"),
    }
    with open(download_dir / "post_info.json", "w", encoding="utf-8") as f:
        json.dump(simple, f, indent=2, ensure_ascii=False)
    with open(download_dir / "username.txt", "w", encoding="utf-8") as f:
        f.write(str(metadata.get("username") or "unknown"))


def resolve_username(post, channel_from_file: str) -> str:
    # 1) from issue title (workflow sets ISSUE_USERNAME)
    env_user = (os.environ.get("ISSUE_USERNAME") or "").strip().lstrip("@")
    if env_user and env_user.lower() != "unknown":
        return env_user

    # 2) from post object
    if post:
        u = post_username(post)
        if u:
            return u

    # 3) from parent JSON target_username
    if channel_from_file and channel_from_file.lower() != "unknown":
        return channel_from_file

    return "unknown"


def main():
    if len(sys.argv) != 2:
        print("Usage: python download_with_fallback.py <shortcode>")
        sys.exit(1)

    shortcode = sys.argv[1].strip()
    print(f"🔍 شروع دانلود برای shortcode: {shortcode}")

    post, channel_from_file = find_post_by_shortcode(shortcode)
    username = resolve_username(post, channel_from_file)
    metadata = None
    media_urls = []
    video_url = None
    post_type = ""

    if post:
        post_type = str(post.get("type") or post.get("post_type") or "")
        media_urls = collect_media_urls(post)
        video_url = post.get("videoUrl") or post.get("video_url")
        metadata = extract_simple_metadata(post, username)
        print(
            f"📄 پست در JSON یافت شد | channel={username} | type={post_type} | "
            f"media_urls={len(media_urls)} | video={'yes' if video_url else 'no'}"
        )
    else:
        print("⚠️ پست در فایل‌های JSON یافت نشد. مستقیماً به yt-dlp می‌رویم...")

    # Download/instagram_downloads/{username}/{shortcode}
    base = Path("Download") / "instagram_downloads"
    download_dir = base / username / shortcode
    download_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 مسیر دانلود: {download_dir}")

    success = False
    method = ""

    is_video = bool(video_url) or post_type.lower() in ("video", "reel", "clips")
    if post and not is_video and media_urls:
        print("📸 پست عکس/کاروسل – تلاش با media_urls")
        if download_media_urls(media_urls, download_dir, shortcode, post_type):
            success = True
            method = "media_urls"

    if not success:
        print("🔄 مرحله ۲: yt-dlp (بدون کوکی)...")
        if download_ytdlp(shortcode, download_dir):
            success = True
            method = "yt-dlp_no_cookie"
            if metadata is None or username == "unknown":
                meta2 = extract_metadata_from_ytdlp(shortcode)
                if meta2:
                    metadata = meta2
                    if meta2.get("username") and meta2["username"] != "unknown":
                        username = meta2["username"]

    if not success:
        cookies_path = os.environ.get("INSTAGRAM_COOKIES_PATH")
        if cookies_path and Path(cookies_path).exists():
            print("🍪 مرحله ۳: yt-dlp + کوکی...")
            if download_ytdlp(shortcode, download_dir, cookies_path):
                success = True
                method = "yt-dlp_with_cookie"
                if metadata is None or username == "unknown":
                    meta2 = extract_metadata_from_ytdlp(shortcode, cookies_path)
                    if meta2:
                        metadata = meta2
                        if meta2.get("username") and meta2["username"] != "unknown":
                            username = meta2["username"]
        else:
            print("⚠️ فایل کوکی در دسترس نیست. مرحله ۳ رد شد.")

    if not success:
        print(f"💥 همه روش‌ها شکست خوردند: {shortcode}")
        sys.exit(1)

    # If username was refined after download into unknown/, move files
    final_dir = base / username / shortcode
    if final_dir.resolve() != download_dir.resolve():
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        if final_dir.exists():
            for item in download_dir.iterdir():
                dest = final_dir / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(item), str(dest))
            try:
                download_dir.rmdir()
            except OSError:
                pass
        else:
            shutil.move(str(download_dir), str(final_dir))
        download_dir = final_dir
        print(f"📦 منتقل شد به: {download_dir}")

    if metadata is None:
        metadata = {
            "shortcode": shortcode,
            "username": username,
            "caption": "",
            "like_count": 0,
            "comment_count": 0,
        }
    else:
        metadata["username"] = username
        metadata["shortcode"] = shortcode

    save_metadata(download_dir, metadata)
    with open(download_dir / "info.txt", "w", encoding="utf-8") as f:
        f.write(f"Method: {method}\nShortcode: {shortcode}\nUsername: {username}\n")

    print(f"🎉 دانلود موفق | @{username} | {shortcode} | {download_dir}")


if __name__ == "__main__":
    main()
