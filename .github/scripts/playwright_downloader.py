#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from pathlib import Path
from typing import List, Tuple, Optional

from playwright.async_api import async_playwright, Page, Download

logger = logging.getLogger("TelegramScraper")


class PlaywrightDownloader:
    """دانلود رسانه‌ها با کلیک روی دکمه‌های دانلود در خود مرورگر (Playwright download event)
    + استخراج مستقیم تصاویر/ویدئوهایی که دکمهٔ دانلود ندارند.
    """

    def __init__(self, profile_dir: Path, media_dir: Path, max_bytes: int,
                 delay: float = 1.5, max_retries: int = 2):
        self.profile_dir = profile_dir
        self.media_dir = media_dir
        self.max_bytes = max_bytes
        self.delay = delay
        self.max_retries = max_retries
        self.media_dir.mkdir(parents=True, exist_ok=True)

    async def download_all(self, tasks: List[Tuple[str, str]]) -> None:
        if not tasks:
            logger.info("هیچ وظیفه‌ای برای دانلود وجود ندارد.")
            return

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            page = await context.new_page()

            # فعال‌سازی سشن
            await page.goto("https://web.telegram.org/a/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            for idx, (post_url, post_id) in enumerate(tasks, start=1):
                logger.info(f"📥 [{idx}/{len(tasks)}] پردازش {post_url}")
                try:
                    await self._process_post(page, post_url, post_id)
                except Exception as e:
                    logger.error(f"❌ شکست در پردازش {post_url}: {e}", exc_info=True)
                if idx < len(tasks):
                    await asyncio.sleep(self.delay)

            await context.close()

    async def _process_post(self, page: Page, post_url: str, post_id: str) -> None:
        """صفحهٔ پست را باز کرده و دانلودها را با کلیک انجام می‌دهد."""
        try:
            await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.error(f"⛔ خطا در باز کردن {post_url}: {e}")
            return

        # صبر برای بارگذاری کامل مدیا
        await asyncio.sleep(3)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1.5)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        # لیستی از دانلودهای قابل کلیک را پیدا کن
        clickable_selectors = [
            'a[download]',                     # لینک با صفت download
            'button[aria-label="Download"]',   # دکمه با برچسب Download
            'button[title="Download"]',
            'div[role="button"][aria-label="Download"]',
            '[data-testid="download-button"]', # در صورت وجود
            'a[href*="/file/"]',               # لینک‌های فایل تلگرام
        ]

        download_triggered = False
        # یک listener برای دریافت فایل‌های دانلود شده
        async def handle_download(download: Download):
            nonlocal download_triggered
            download_triggered = True
            try:
                suggested = download.suggested_filename
                # حذف کاراکترهای غیرمجاز از نام فایل (اختیاری)
                safe_name = "".join(c for c in suggested if c.isalnum() or c in "._-() ")
                if not safe_name:
                    safe_name = f"{post_id}_file"
                filepath = self.media_dir / safe_name
                # اگر فایل با همین نام وجود داشت، یک شماره اضافه کن
                counter = 1
                while filepath.exists():
                    stem = filepath.stem
                    filepath = self.media_dir / f"{stem}_{counter}{filepath.suffix}"
                    counter += 1
                await download.save_as(str(filepath))
                size_mb = filepath.stat().st_size / 1024 / 1024 if filepath.exists() else 0
                logger.info(f"✅ دانلود شد (click): {safe_name} ({size_mb:.1f} MB)")
            except Exception as e:
                logger.error(f"❌ خطا در ذخیره دانلود: {e}")

        # حذف listener قبلی (اگر باشد) و اضافه کردن جدید
        page.remove_listener("download", handle_download)
        page.on("download", handle_download)

        # کلیک روی هر المان دانلود
        for selector in clickable_selectors:
            elements = page.locator(selector)
            count = await elements.count()
            for i in range(count):
                if download_triggered:  # اگر قبلاً دانلودی انجام شده، از حلقه بیرون برو
                    # فقط برای جلوگیری از چند دانلود همزمان در یک پست (اختیاری)
                    pass
                elem = elements.nth(i)
                if await elem.is_visible():
                    try:
                        # قبل از کلیک، مطمئن شو که روی المان دیگری کلیک نشده (scroll)
                        await elem.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        await elem.click(timeout=5000)
                        # منتظر بمان تا دانلود آغاز شود
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.debug(f"کلیک روی {selector} ناموفق: {e}")
                if download_triggered:
                    break
            if download_triggered:
                break

        # اگر هیچ کلیکی منجر به دانلود نشد، رسانه‌های inline (عکس/ویدئو) را با روش قبلی دانلود کن
        if not download_triggered:
            logger.info("🖼️ دانلود با کلیک میسر نشد، تلاش برای استخراج مستقیم عکس/ویدئو...")
            await self._download_inline_media(page, post_id)

        # حذف listener بعد از پایان کار این پست
        page.remove_listener("download", handle_download)

    async def _download_inline_media(self, page: Page, post_id: str) -> None:
        """استخراج لینک عکس‌ها و ویدئوهای بدون دکمهٔ دانلود و دریافت مستقیم."""
        media_links = await page.evaluate('''() => {
            const links = new Set();
            const add = (url) => {
                if (url && url.startsWith('http') && !url.startsWith('data:')) links.add(url);
            };
            document.querySelectorAll('img[src]').forEach(img => add(img.src));
            document.querySelectorAll('video source[src], audio source[src]').forEach(el => add(el.src));
            return Array.from(links);
        }''')

        if not media_links:
            logger.info("📭 هیچ رسانهٔ inline یافت نشد.")
            return

        for idx, link in enumerate(media_links):
            success = False
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await page.request.get(link, headers={"Referer": "https://web.telegram.org/"})
                    if resp.ok:
                        body = await resp.body()
                        if len(body) > self.max_bytes:
                            logger.info(f"⏩ رد شد (حجم {len(body)/1024/1024:.1f}MB): {link}")
                            success = True  # رد عمدی
                            break
                        # تعیین پسوند
                        ext = self._guess_ext(resp, link)
                        filepath = self.media_dir / f"{post_id}_{idx}.{ext}"
                        with open(filepath, 'wb') as f:
                            f.write(body)
                        logger.info(f"✅ دانلود مستقیم: {filepath.name} ({len(body)/1024/1024:.1f} MB)")
                        success = True
                        break
                    else:
                        logger.warning(f"⚠️ HTTP {resp.status} برای {link}")
                except Exception as e:
                    logger.error(f"❌ خطای دانلود {link}: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2)
            if not success:
                logger.warning(f"🚫 دانلود {link} ناموفق ماند.")

    def _guess_ext(self, response, url: str) -> str:
        """حدس پسوند از Content-Type یا URL."""
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        mapping = {
            "image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
            "image/webp": "webp", "video/mp4": "mp4", "video/webm": "webm",
            "audio/mpeg": "mp3", "audio/ogg": "ogg"
        }
        if content_type in mapping:
            return mapping[content_type]
        # حدس از URL
        path = url.split("?")[0]
        if '.' in path:
            ext = path.rsplit('.', 1)[-1][:5]
            if ext.isalnum():
                return ext
        return "bin"
