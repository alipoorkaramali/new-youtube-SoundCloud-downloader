#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import random
from pathlib import Path
from typing import List, Tuple

from playwright.async_api import async_playwright, Page, Download

logger = logging.getLogger("TelegramScraper")

async def human_sleep(base: float, jitter: float = 0.4):
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))

class PlaywrightDownloader:
    """
    دانلود رسانه‌ها با کلیک روی اولین مدیای هر پست (بالای متن).
    از layout طبیعی تلگرام استفاده می‌کند: مدیا همیشه بالای کپشن یا حباب خالی است.
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
        self.delay = delay
        self.max_retries = max_retries
        self.media_dir.mkdir(parents=True, exist_ok=True)

    async def download_all(self, tasks: List[Tuple[str, str]]) -> None:
        if not tasks:
            return
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            page = await context.new_page()
            await page.goto("https://web.telegram.org/a/", wait_until="domcontentloaded", timeout=30000)
            await human_sleep(2, 0.3)

            for idx, (post_url, post_id) in enumerate(tasks, start=1):
                logger.info(f"📥 [{idx}/{len(tasks)}] {post_url}")
                try:
                    await self._process_post(page, post_url, post_id)
                except Exception as e:
                    logger.error(f"❌ خطا در {post_url}: {e}")
                if idx < len(tasks):
                    # تأخیر انسانی بین پست‌ها
                    await human_sleep(self.delay, 0.5)
            await context.close()

    async def _process_post(self, page: Page, post_url: str, post_id: str) -> None:
        # بارگذاری صفحه پست
        try:
            await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.error(f"⛔ باز نشد: {e}")
            return

        # صبر برای لود کامل پست (انسان‌گونه)
        await human_sleep(4, 0.5)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await human_sleep(1.5, 0.4)
        await page.evaluate("window.scrollTo(0, 0)")
        await human_sleep(1, 0.3)

        # پیدا کردن پیام با data-message-id
        msg_id = post_url.rstrip('/').split('/')[-1]
        message_locator = page.locator(f'[data-message-id="{msg_id}"]')
        if await message_locator.count() == 0:
            logger.warning(f"⚠️ المان پیام با شناسه {msg_id} پیدا نشد.")
            return

        # بالاترین المان مدیا
        media_container = message_locator.locator('div.media-photo, div.media-video, div.document, '
                                                  'a.media-photo, video, img[src]').first
        if await media_container.count() == 0:
            logger.info("📝 پست بدون مدیا (متن خالص).")
            return

        # تنظیم شنونده دانلود
        download_occurred = False
        async def handle_download(download: Download):
            nonlocal download_occurred
            download_occurred = True
            try:
                fname = "".join(c for c in download.suggested_filename if c.isalnum() or c in "._-() ")
                if not fname:
                    fname = f"{post_id}_file"
                filepath = self.media_dir / fname
                counter = 1
                while filepath.exists():
                    stem = filepath.stem
                    filepath = self.media_dir / f"{stem}_{counter}{filepath.suffix}"
                    counter += 1
                await download.save_as(str(filepath))
                size_mb = filepath.stat().st_size / 1024 / 1024 if filepath.exists() else 0
                logger.info(f"✅ دانلود شد: {fname} ({size_mb:.1f} MB)")
            except Exception as e:
                logger.error(f"❌ ذخیره دانلود: {e}")

        page.on("download", handle_download)

        # ۱) کلیک مستقیم روی مدیا
        try:
            await media_container.scroll_into_view_if_needed()
            await human_sleep(0.5, 0.4)
            await media_container.click(timeout=5000, force=True)
            await human_sleep(4, 0.5)   # افزایش برای اطمینان
            if download_occurred:
                page.remove_listener("download", handle_download)
                return
        except Exception as e:
            logger.debug(f"کلیک اول ناموفق: {e}")

        # ۲) اگر دانلود نشد، بیننده را باز کنیم و دکمه دانلود را بزنیم
        try:
            await page.wait_for_selector('div.media-viewer, div[class*="MediaViewer"]', timeout=5000)
            download_btn = page.locator('button[aria-label="Download"], [title="Download"]').first
            if await download_btn.count() > 0:
                await download_btn.click(timeout=5000)
                await human_sleep(4, 0.5)
                if download_occurred:
                    page.remove_listener("download", handle_download)
                    return
        except Exception:
            pass

        page.remove_listener("download", handle_download)

        # ۳) روش fallback: استخراج مستقیم
        logger.info("🔄 تلاش برای دانلود مستقیم...")
        await self._direct_download(page, post_id, media_container)

    async def _direct_download(self, page: Page, post_id: str, container) -> None:
        """استخراج لینک‌های img, video source از DOM و دانلود با page.request."""
        links = await page.evaluate('''() => {
            const links = new Set();
            const add = (url) => { if (url && url.startsWith('http')) links.add(url); };
            document.querySelectorAll('img[src]').forEach(i => add(i.src));
            document.querySelectorAll('video source[src]').forEach(s => add(s.src));
            document.querySelectorAll('a[href*="/file/"]').forEach(a => add(a.href));
            return Array.from(links);
        }''')
        if not links:
            logger.info("📭 هیچ لینکی پیدا نشد.")
            return
        for idx, link in enumerate(links):
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await page.request.get(link, headers={"Referer": "https://web.telegram.org/"})
                    if resp.ok:
                        body = await resp.body()
                        if len(body) > self.max_bytes:
                            logger.info(f"⏩ حجم بالا ({len(body)/1024/1024:.1f}MB)")
                            break
                        ext = self._guess_ext(resp, link)
                        path = self.media_dir / f"{post_id}_{idx}.{ext}"
                        with open(path, 'wb') as f:
                            f.write(body)
                        logger.info(f"✅ دانلود مستقیم: {path.name}")
                        break
                    else:
                        logger.warning(f"⚠️ HTTP {resp.status}")
                except Exception as e:
                    logger.error(f"❌ خطا: {e}")
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