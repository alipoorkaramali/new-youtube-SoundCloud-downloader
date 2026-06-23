#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import time
import base64
import re
import random
import os
import subprocess
import tempfile
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from cryptography.fernet import Fernet

class TelegramSession:
    """مدیریت سشن تلگرام وب (نسخه A / Z) با پشتیبانی از چند روش ذخیره‌سازی:
    1. فایل رمزنگاری‌شدهٔ Fernet (session.enc) – اولویت اول
    2. فایل GPG (session.json.gpg)
    3. فایل JSON ساده (session.json)
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://web.telegram.org/z/",
        "Origin": "https://web.telegram.org",
    }

    API_URL = "https://web.telegram.org/z/api?hash=0"

    def __init__(self, session_file: Path, rate_limit: float):
        """
        session_file: مسیر فایل session (بدون پسوند، مثلاً config/session)
        rate_limit: حداقل فاصلهٔ زمانی (ثانیه) بین درخواست‌ها
        """
        self.session_file = session_file
        self.rate_limit = rate_limit
        self.cookies: dict = {}
        self.sess = requests.Session()
        self.last_request = 0.0

    # ═══════════════ بارگذاری سشن ═══════════════
    def load(self) -> bool:
        """بارگذاری سشن به ترتیب اولویت: Fernet → JSON → GPG"""
        # ۱. فایل رمزنگاری‌شدهٔ Fernet
        enc_file = self.session_file.with_suffix('.enc')
        key_file = self.session_file.parent / ".session_key"
        if enc_file.exists() and key_file.exists():
            return self._load_from_fernet(enc_file, key_file)

        # ۲. فایل JSON ساده
        json_file = self.session_file.with_suffix('.json')
        if json_file.exists():
            return self._load_from_json(json_file)

        # ۳. فایل GPG
        gpg_file = self.session_file.with_suffix('.json.gpg')
        if gpg_file.exists():
            return self._load_from_gpg(gpg_file)

        print("⚠️ هیچ فایل سشنی (enc/json/gpg) پیدا نشد.")
        return False

    def _load_from_fernet(self, enc_file: Path, key_file: Path) -> bool:
        """رمزگشایی فایل Fernet و بارگذاری کوکی‌ها"""
        try:
            key = key_file.read_bytes()
            f = Fernet(key)
            data = json.loads(f.decrypt(enc_file.read_bytes()).decode('utf-8'))

            # استخراج کوکی‌ها و تبدیل به دیکشنری ساده
            self.cookies = {c["name"]: c["value"] for c in data.get("cookies", [])}
            self.sess.cookies.update(self.cookies)
            self.sess.headers.update(self.HEADERS)

            print("✅ سشن از فایل Fernet بارگذاری شد.")
            return self.is_valid()
        except Exception as e:
            print(f"❌ خطا در بارگذاری سشن Fernet: {e}")
            return False

    def _load_from_json(self, json_file: Path) -> bool:
        """بارگذاری مستقیم از فایل JSON"""
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.cookies = data
            self.sess.cookies.update(self.cookies)
            self.sess.headers.update(self.HEADERS)
            print("✅ سشن از فایل JSON بارگذاری شد.")
            return self.is_valid()
        except Exception as e:
            print(f"❌ خطا در بارگذاری session.json: {e}")
            return False

    def _load_from_gpg(self, gpg_file: Path) -> bool:
        """رمزگشایی GPG و بارگذاری"""
        passphrase = os.environ.get('GPG_PASSPHRASE', '')
        if not passphrase:
            print("❌ متغیر محیطی GPG_PASSPHRASE تنظیم نشده است.")
            return False
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as tmp:
                subprocess.run(
                    ['gpg', '--batch', '--yes', '--passphrase', passphrase,
                     '--decrypt', str(gpg_file)],
                    stdout=tmp,
                    stderr=subprocess.DEVNULL,
                    check=True
                )
                tmp_path = Path(tmp.name)
            tmp_path.rename(self.session_file.with_suffix('.json'))
            print("✅ فایل GPG با موفقیت رمزگشایی شد.")
            return self._load_from_json(self.session_file.with_suffix('.json'))
        except subprocess.CalledProcessError:
            print("❌ خطا در رمزگشایی GPG: رمز عبور اشتباه یا فایل خراب.")
        except Exception as e:
            print(f"❌ خطای غیرمنتظره در GPG: {e}")
        return False

    # ═══════════════ اعتبارسنجی ═══════════════
    def is_valid(self) -> bool:
        """بررسی زنده بودن سشن با یک درخواست سبک"""
        try:
            resp = self._api_request("help.getNearestDc")
            if resp and resp.get("result"):
                print("✅ سشن تلگرام معتبر است.")
                return True
        except Exception:
            pass
        print("⚠️ سشن تلگرام نامعتبر است. لطفاً کوکی‌ها را به‌روز کنید.")
        return False

    # ═══════════════ Rate Limiting ═══════════════
    def _rate_limit(self):
        """تأخیر تصادفی برای طبیعی‌تر شدن رفتار"""
        elapsed = time.time() - self.last_request
        delay = self.rate_limit * random.uniform(0.7, 1.3)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self.last_request = time.time()

    # ═══════════════ درخواست به API ═══════════════
    def _api_request(self, method: str, data: dict = None) -> dict:
        """ارسال درخواست به API داخلی تلگرام وب"""
        self._rate_limit()
        try:
            if data is None:
                resp = self.sess.get(self.API_URL, params={"method": method})
            else:
                payload = {"method": method, **data}
                resp = self.sess.post(self.API_URL, json=payload)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ خطا در درخواست API تلگرام ({method}): {e}")
            raise

    # ═══════════════ ابزارهای کمکی ═══════════════
    def resolve_username(self, username: str) -> Optional[Tuple[int, str]]:
        """تبدیل username کانال به (channel_id, access_hash)"""
        username = username.lstrip("@")
        resp = self._api_request("contacts.resolveUsername", {"username": username})
        peer = resp.get("result", {}).get("peer")
        if not peer:
            return None
        channel_id = peer.get("channel_id") or peer.get("chat_id")
        access_hash = peer.get("access_hash")
        if not channel_id or not access_hash:
            return None
        return int(channel_id), access_hash

    def get_best_media_links(self, post_url: str) -> List[Dict]:
        """
        دریافت بهترین لینک‌های دانلود مستقیم از یک پست.
        خروجی: لیستی از دیکشنری‌های {'url', 'filename', 'media_type'}
        """
        match = re.search(r't\.me/([^/]+)/(\d+)', post_url)
        if not match:
            return []

        channel_username, msg_id = match.groups()
        msg_id = int(msg_id)

        info = self.resolve_username(channel_username)
        if not info:
            return []
        channel_id, access_hash = info

        data = {
            "peer": {
                "_": "inputPeerChannel",
                "channel_id": channel_id,
                "access_hash": access_hash
            },
            "add_offset": 0,
            "limit": 5,
            "offset_id": msg_id + 2,
            "min_id": msg_id - 1,
            "max_id": msg_id
        }

        try:
            resp = self._api_request("messages.getHistory", data)
            messages = resp.get("result", {}).get("messages", [])
            target = next((m for m in messages if m.get("id") == msg_id), None)
            if not target:
                return []

            media = target.get("media")
            if not media:
                return []

            links = []
            media_type = media["_"]

            # --- عکس ---
            if media_type == "messageMediaPhoto":
                photo = media.get("photo", {})
                sizes = photo.get("sizes", [])
                if sizes:
                    largest = sizes[-1]  # بالاترین وضوح
                    dl_url = self._build_download_url(largest, photo.get("file_reference", b""))
                    links.append({
                        "url": dl_url,
                        "filename": f"photo_{msg_id}.jpg",
                        "media_type": "photo"
                    })

            # --- سند (شامل ویدئو، ویس، فایل، گیف و ...) ---
            elif media_type == "messageMediaDocument":
                doc = media.get("document", {})
                mime = doc.get("mime_type", "")
                attributes = doc.get("attributes", [])
                file_ref = doc.get("file_reference", b"")
                dl_url = self._build_download_url(doc, file_ref)

                # تشخیص نام فایل
                filename = None
                for attr in attributes:
                    if attr.get("_") == "documentAttributeFilename":
                        filename = attr.get("file_name")
                        break

                if not filename:
                    # حدس بر اساس نوع
                    if any(attr.get("_") == "documentAttributeAudio" for attr in attributes):
                        if any(a.get("voice") for a in attributes if a.get("_") == "documentAttributeAudio"):
                            filename = f"voice_{msg_id}.ogg"
                        else:
                            filename = f"audio_{msg_id}.mp3"
                    elif any(attr.get("_") == "documentAttributeVideo" for attr in attributes):
                        filename = f"video_{msg_id}.mp4"
                    elif "image/gif" in mime:
                        filename = f"gif_{msg_id}.mp4"
                    elif "image" in mime:
                        filename = f"image_{msg_id}.jpg"
                    elif "pdf" in mime:
                        filename = f"document_{msg_id}.pdf"
                    else:
                        ext = mime.split("/")[-1] if "/" in mime else "file"
                        filename = f"file_{msg_id}.{ext}"

                links.append({
                    "url": dl_url,
                    "filename": filename,
                    "media_type": "document"
                })

            return links

        except Exception:
            return []

    @staticmethod
    def _build_download_url(media_obj: dict, file_reference: bytes) -> str:
        """ساخت لینک دانلود مستقیم"""
        fid = media_obj["id"]
        ah = media_obj["access_hash"]
        ref_b64 = base64.b64encode(file_reference).decode()
        return f"https://web.telegram.org/a/file.html?prefix={fid}&access_hash={ah}&file_reference={ref_b64}"