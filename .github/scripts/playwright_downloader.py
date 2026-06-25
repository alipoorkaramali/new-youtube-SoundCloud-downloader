#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional

from playwright.async_api import Page, Download

logger = logging.getLogger("TelegramScraper")


async def human_sleep(base: float, jitter: float = 0.4):
    """خواب انسانی با کمی تصادف"""
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class PlaywrightDownloader:
    """
    دانلود مدیا مستقیماً از داخل کانال باز (بدون باز کردن لینک جداگانه).
    رفتار کاملاً شبیه کاربر واقعی:
    - برای عکس/ویدیو: کلیک → Media Viewer → دانلود → Next (در صورت آلبوم) → بستن بیننده
    - برای فایل/ویس: کلیک روی دکمه دانلود یا خود حباب فایل
    - fallback: استخراج مستقیم لینک از DOM همان پیام
    """

    MIME_TO_EXT = {
        "image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
        "image/webp": "webp", "video/mp4": "mp4", "video/webm": "webm",
        "audio/mpeg": "mp3", "audio/ogg": "ogg", "application/pdf": "pdf",
        "application/zip": "zip", "application/x-rar-compressed": "rar",
        "application/octet-stream": "bin",
    }

    def __init__(self, profile_dir: Path, media_dir: Path, max_bytes: int,
                 delay: float = 5.0, max_retries: int = 2):
        self.profile_dir = profile_dir
        self.media_dir = media_dir
        self.max_bytes = max_bytes
        self.delay = delay          # تأخیر پایه بین پست‌ها
        self.max_retries = max_retries
        self.media_dir.mkdir(parents=True, exist_ok=True)

    async def download_all(self, page: Page, context, post_ids: List[str]) -> None:
        """ورودی: page و context اسکرپر، و لیست شناسه‌های پست‌ها (data-message-id)"""
        if not post_ids:
            logger.info("هیچ پستی برای دانلود وجود ندارد.")
            return

        # تنظیم یک listener کلی برای رویداد دانلود (تا پایان کار همهٔ پست‌ها باقی می‌ماند)
        downloaded_files = []

        async def on_download(download: Download):
            try:
                suggested = download.suggested_filename
                safe_name = "".join(c for c in suggested if c.isalnum() or c in "._-() ")
                if not safe_name:
                    safe_name = f"file_{len(downloaded_files)}"
                filepath = self.media_dir / safe_name
                # جلوگیری از بازنویسی
                counter = 1
                while filepath.exists():
                    stem = filepath.stem
                    filepath = self.media_dir / f"{stem}_{counter}{filepath.suffix}"
                    counter += 1
                await download.save_as(str(filepath))
                size_mb = filepath.stat().st_size / 1024 / 1024 if filepath.exists() else 0
                logger.info(f"✅ دانلود شد: {safe_name} ({size_mb:.1f} MB)")
                downloaded_files.append(str(filepath))
            except Exception as e:
                logger.error(f"❌ خطا در ذخیرهٔ دانلود: {e}")

        page.on("download", on_download)

        try:
            for idx, post_id in enumerate(post_ids, start=1):
                logger.info(f"📥 [{idx}/{len(post_ids)}] پردازش پست {post_id}...")
                try:
                    await self._process_post(page, post_id)
                except Exception as e:
                    logger.error(f"❌ خطا در پردازش پست {post_id}: {e}")
                # تأخیر انسانی بین پست‌ها
                if idx < len(post_ids):
                    await human_sleep(self.delay, 0.5)
        finally:
            page.remove_listener("download", on_download)

    async def _process_post(self, page: Page, post_id: str) -> None:
        """پردازش یک پست با شناسهٔ data-message-id"""
        # ۱. پیدا کردن المان پیام و اطمینان از دیده‌شدن آن
        message_locator = page.locator(f'[data-message-id="{post_id}"]')
        if await message_locator.count() == 0:
            logger.warning(f"⚠️ پست {post_id} در صفحه پیدا نشد (ممکن است نیاز به اسکرول داشته باشد).")
            # اگر پیدا نشد، شاید هنوز در viewport نیست. کل صفحه را به بالا/پایین اسکرول می‌دهیم تا لود شود.
            # اما در حالت عادی پست‌ها در لیست هستند. بی‌خیالش می‌شویم.
            return

        await message_locator.scroll_into_view_if_needed()
        await human_sleep(0.5, 0.3)

        # ۲. تشخیص تمام المان‌های مدیا درون این پیام
        media_elements = message_locator.locator(
            'div.media-photo, div.media-video, div.document, a.media-photo, '
            'video, img[src], div[class*="media"]'
        )
        media_count = await media_elements.count()
        if media_count == 0:
            # شاید متن خالص باشد یا مدیا با ساختار متفاوت
            logger.debug(f"📝 پست {post_id} بدون مدیا یافت شد (متن خالص).")
            return

        logger.info(f"🎯 {media_count} المان مدیا در پست {post_id} یافت شد.")

        # ۳. پردازش هر المان مدیا به‌ترتیب
        for i in range(media_count):
            elem = media_elements.nth(i)
            # تشخیص نوع تقریبی بر اساس کلاس یا تگ
            tag_name = await elem.evaluate("el => el.tagName.toLowerCase()")
            class_attr = await elem.get_attribute("class") or ""

            if "document" in class_attr or "file" in class_attr:
                # فایل / ویس / اسناد
                await self._download_document(page, elem, post_id)
            else:
                # عکس یا ویدیو (با Media Viewer)
                await self._download_media_viewer(page, elem, post_id)

    # ═══════════════════ دانلود فایل / ویس (document) ═══════════════════
    async def _download_document(self, page: Page, element, post_id: str):
        """روی حباب فایل کلیک می‌کند یا دکمهٔ دانلود آن را می‌زند."""
        # ابتدا سعی می‌کنیم روی خود element کلیک کنیم (بعضی فایل‌ها مستقیم دانلود می‌شوند)
        try:
            await element.scroll_into_view_if_needed()
            await human_sleep(0.3, 0.4)
            await element.click(timeout=5000, force=True)
            # منتظر بمانیم شاید download event فعال شود (توسط listener کلی)
            await human_sleep(3, 0.4)
            # اگر دانلود شروع شده باشد که هیچ، وگرنه دنبال دکمه دانلود بگردیم
        except Exception as e:
            logger.debug(f"کلیک مستقیم روی فایل ناموفق: {e}")

        # جستجوی دکمهٔ دانلود مخصوص (درون همان المان یا نزدیک آن)
        download_btn = element.locator(
            'button[aria-label="Download"], [title="Download"], .icon-download, '
            '[class*="download"], button:has(svg)'
        ).first
        if await download_btn.count() > 0:
            try:
                await download_btn.click(timeout=5000, force=True)
                await human_sleep(3, 0.4)
            except Exception as e:
                logger.debug(f"کلیک روی دکمه دانلود فایل ناموفق: {e}")

        # اگر هنوز دانلود نشد، fallback مستقیم روی لینک‌های داخل element
        # (با فرض اینکه ممکن است listener رویداد را نگرفته باشیم، یک بار دیگر تلاش می‌کنیم)
        if not self._last_download_succeeded(page):  # نیاز به یک روش برای تشخیص آسان نیست،
            # می‌توانیم مستقیماً fallback کنیم
            await self._direct_download_from_element(page, element, post_id)

    # ═══════════════════ دانلود عکس/ویدیو با Media Viewer ═══════════════════
    async def _download_media_viewer(self, page: Page, element, post_id: str):
        """کلیک روی عکس/ویدیو ← Media Viewer ← دانلود ← Next (آلبوم) ← بستن"""
        # کلیک روی المان برای باز کردن بیننده
        try:
            await element.scroll_into_view_if_needed()
            await human_sleep(0.3, 0.4)
            await element.click(timeout=5000, force=True)
        except Exception as e:
            logger.debug(f"کلیک روی عکس/ویدیو ناموفق: {e}")
            return

        # منتظر باز شدن Media Viewer
        viewer_selector = 'div.media-viewer, div[class*="MediaViewer"], div[class*="lightbox"]'
        try:
            await page.wait_for_selector(viewer_selector, timeout=8000)
        except Exception:
            logger.debug("Media Viewer باز نشد. ممکن است مستقیماً دانلود شده باشد یا خطا.")
            return

        # اکنون در Media Viewer هستیم. یک حلقه برای پیمایش آلبوم
        while True:
            # کلیک روی دکمهٔ دانلود (معمولاً در نوار بالای بیننده)
            download_btn = page.locator(
                'button[aria-label="Download"], [title="Download"], .btn-download'
            ).first
            if await download_btn.count() > 0:
                try:
                    await download_btn.click(timeout=5000)
                    await human_sleep(2, 0.3)
                except Exception as e:
                    logger.debug(f"کلیک روی دکمه دانلود در بیننده ناموفق: {e}")
            else:
                logger.debug("دکمهٔ دانلود در Media Viewer پیدا نشد.")

            # بررسی وجود دکمهٔ Next (آلبوم)
            next_btn = page.locator(
                'button[aria-label="Next"], [title="Next"], .btn-next, '
                'div[class*="nav-next"], button:has(svg[class*="arrow"])'
            ).first
            if await next_btn.count() > 0:
                # کلیک روی Next و ادامه
                try:
                    await next_btn.click(timeout=5000)
                    await human_sleep(1.5, 0.4)
                except Exception:
                    break  # اگر نشد، خارج شو
            else:
                break  # آلبوم تمام شد

        # بستن Media Viewer (با دکمه Close یا کلید Escape)
        close_btn = page.locator(
            'button[aria-label="Close"], [title="Close"], .btn-close'
        ).first
        if await close_btn.count() > 0:
            try:
                await close_btn.click(timeout=5000)
                await human_sleep(0.5, 0.2)
            except Exception:
                pass
        else:
            # fallback: زدن کلید Escape
            try:
                await page.keyboard.press("Escape")
                await human_sleep(0.5, 0.2)
            except Exception:
                pass

        # اگر به هر دلیلی دانلود نشده بود، fallback مستقیم
        # (اختیاری: اما می‌توانیم بعد از بستن بیننده یک بار دیگر لینک‌های همان پیام را استخراج کنیم)
        await self._direct_download_from_element(page, element, post_id)

    # ═══════════════════ Fallback: استخراج مستقیم لینک از المان مدیا ═══════════════════
    async def _direct_download_from_element(self, page: Page, element, post_id: str):
        """لینک‌های img, video source, a[href*='/file/'] را از درون element استخراج و دانلود می‌کند."""
        links = await element.evaluate('''(el) => {
            const links = new Set();
            const add = (url) => { if (url && url.startsWith('http')) links.add(url); };
            el.querySelectorAll('img[src]').forEach(i => add(i.src));
            el.querySelectorAll('video source[src]').forEach(s => add(s.src));
            el.querySelectorAll('a[href*="/file/"]').forEach(a => add(a.href));
            return Array.from(links);
        }''')
        if not links:
            logger.debug("Fallback: هیچ لینکی در این المان پیدا نشد.")
            return

        for idx, link in enumerate(links):
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await page.request.get(link, headers={"Referer": "https://web.telegram.org/"})
                    if resp.ok:
                        body = await resp.body()
                        if len(body) > self.max_bytes:
                            logger.info(f"⏩ رد شد (حجم {len(body)/1024/1024:.1f}MB): {link}")
                            break
                        ext = self._guess_ext(resp, link)
                        filepath = self.media_dir / f"{post_id}_{idx}.{ext}"
                        with open(filepath, 'wb') as f:
                            f.write(body)
                        logger.info(f"✅ دانلود مستقیم: {filepath.name} ({len(body)/1024/1024:.1f} MB)")
                        break
                    else:
                        logger.warning(f"⚠️ HTTP {resp.status} برای {link}")
                except Exception as e:
                    logger.error(f"❌ خطای دانلود {link}: {e}")
                if attempt < self.max_retries:
                    await human_sleep(2, 0.5)

    def _guess_ext(self, response, url: str) -> str:
        ct = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if ct in self.MIME_TO_EXT:
            return self.MIME_TO_EXT[ct]
        path = url.split("?")[0]
        if '.' in path:
            ext = path.rsplit('.', 1)[-1][:5]
            if ext.isalnum():
                return ext
        return "bin"