#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from pathlib import Path
from typing import List, Tuple, Optional

from playwright.async_api import async_playwright, Page, Download

logger = logging.getLogger("TelegramScraper")


class PlaywrightDownloader:
    """
    دانلود رسانه‌های تلگرام با شبیه‌سازی کلیک کاربر:
    ۱. تصاویر: کلیک روی عکس → باز شدن Lightbox → کلیک روی دکمهٔ دانلود.
    ۲. ویدئوها: کلیک برای پخش → ظاهر شدن دکمهٔ دانلود → کلیک.
    ۳. فایل‌ها: کلیک روی حباب فایل → فعال شدن دانلود.
    اگر روش تعاملی جواب نداد، به استخراج مستقیم لینک و دانلود با page.request سقوط می‌کند.
    """

    # نگاشت MIME به پسوند فایل
    MIME_TO_EXT = {
        "image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
        "image/webp": "webp", "image/svg+xml": "svg", "video/mp4": "mp4",
        "video/webm": "webm", "video/ogg": "ogv", "audio/mpeg": "mp3",
        "audio/ogg": "ogg", "audio/wav": "wav", "application/pdf": "pdf",
        "application/zip": "zip", "application/x-rar-compressed": "rar",
        "application/x-7z-compressed": "7z", "application/octet-stream": "bin",
    }

    def __init__(self, profile_dir: Path, media_dir: Path, max_bytes: int,
                 delay: float = 2.0, max_retries: int = 2):
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
        """صفحهٔ پست را باز کرده و مدیاها را یکی‌یکی دانلود می‌کند."""
        try:
            await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.error(f"⛔ خطا در باز کردن {post_url}: {e}")
            return

        # صبر برای بارگذاری اولیهٔ پست
        await asyncio.sleep(3)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        # لیست تمام المان‌هایی که احتمالاً قابل کلیک برای دانلود هستند
        # ۱. تصاویر (تکی یا آلبومی)
        image_selectors = [
            'div.media-photo',           # تصویر تکی
            'a.media-photo',             # لینک به عکس
            'div.album-item',            # عکس در آلبوم
            '.photo',                    # حالت عمومی
            'img.thumbnail',             # پیش‌نمایش
        ]
        # ۲. ویدئوها
        video_selectors = [
            'video',                     # المان video
            'div.media-video',           # کانتینر ویدئو
            '.video-thumb',              # پیش‌نمایش ویدئو
        ]
        # ۳. فایل‌ها (اسناد)
        file_selectors = [
            'div.document',              # حباب سند
            'a[href*="/file/"]',         # لینک مستقیم فایل
            '.document-wrapper',         # پوشش سند
            'div[class*="document"]',
        ]

        # سعی کن با کلیک روی عکس/آلبوم دانلود کنی
        media_downloaded = await self._click_and_download(page, image_selectors, post_id,
                                                          open_viewer=True)

        # اگر تصویری نبود، سراغ ویدئو برو
        if not media_downloaded:
            media_downloaded = await self._click_and_download(page, video_selectors, post_id,
                                                              open_viewer=False,
                                                              click_play=True)

        # اگر همچنان چیزی دانلود نشد، فایل‌ها را امتحان کن
        if not media_downloaded:
            await self._click_and_download(page, file_selectors, post_id,
                                           open_viewer=False, direct_download=True)

        # اگر هیچکدام کار نکرد، روش مستقیم (fallback) را اجرا کن
        if not media_downloaded:
            logger.info("🔄 هیچ دانلود تعاملی انجام نشد، تلاش برای استخراج مستقیم...")
            await self._download_inline_media(page, post_id)

    async def _click_and_download(self, page: Page, selectors: List[str], post_id: str,
                                  open_viewer: bool = False, click_play: bool = False,
                                  direct_download: bool = False) -> bool:
        """
        روی المان‌های منطبق کلیک می‌کند و سعی می‌کند رویداد دانلود را بگیرد.
        اگر open_viewer=True باشد، ابتدا یک عکس را کلیک می‌کند تا Lightbox باز شود،
        سپس داخل Lightbox دکمهٔ دانلود را می‌زند.
        """
        for selector in selectors:
            elements = page.locator(selector)
            count = await elements.count()
            for i in range(count):
                elem = elements.nth(i)
                if not await elem.is_visible():
                    continue
                try:
                    await elem.scroll_into_view_if_needed()
                    await asyncio.sleep(0.5)

                    # تنظیم شنوندهٔ دانلود برای این کلیک
                    download_occurred = False
                    downloaded_file = None

                    async def handle_download(download: Download):
                        nonlocal download_occurred, downloaded_file
                        download_occurred = True
                        try:
                            suggested = download.suggested_filename
                            safe_name = "".join(c for c in suggested if c.isalnum() or c in "._-() ")
                            if not safe_name:
                                safe_name = f"{post_id}_file"
                            filepath = self.media_dir / safe_name
                            counter = 1
                            while filepath.exists():
                                stem = filepath.stem
                                filepath = self.media_dir / f"{stem}_{counter}{filepath.suffix}"
                                counter += 1
                            await download.save_as(str(filepath))
                            size_mb = filepath.stat().st_size / 1024 / 1024 if filepath.exists() else 0
                            logger.info(f"✅ دانلود شد (کلیک): {safe_name} ({size_mb:.1f} MB)")
                            downloaded_file = filepath
                        except Exception as e:
                            logger.error(f"❌ خطا در ذخیره دانلود: {e}")

                    page.on("download", handle_download)

                    if open_viewer:
                        # کلیک روی عکس برای باز کردن بیننده
                        await elem.click(timeout=5000)
                        # منتظر ظاهر شدن بیننده (Lightbox)
                        try:
                            await page.wait_for_selector(
                                'div.media-viewer, div[class*="MediaViewer"], div.lightbox',
                                timeout=8000
                            )
                            # حالا داخل بیننده دکمهٔ دانلود را بزن
                            download_btn = page.locator(
                                'button[aria-label="Download"], [title="Download"], .btn-download, '
                                'div[class*="download"]'
                            ).first
                            if await download_btn.count() > 0:
                                await download_btn.click(timeout=5000)
                                await asyncio.sleep(3)
                            else:
                                logger.debug("دکمهٔ دانلود در بیننده پیدا نشد.")
                        except Exception as e:
                            logger.debug(f"بیننده باز نشد یا خطا: {e}")
                    elif click_play:
                        # برای ویدئو: کلیک برای پخش، سپس دکمهٔ دانلود در کنترل‌ها
                        await elem.click(timeout=5000)   # پخش
                        await asyncio.sleep(2)
                        # جستجوی دکمهٔ دانلود (ممکن است در کنترل‌های ویدئو باشد)
                        download_btn = page.locator(
                            'button[aria-label="Download"], [title="Download"], .btn-download'
                        ).first
                        if await download_btn.count() > 0:
                            await download_btn.click(timeout=5000)
                            await asyncio.sleep(3)
                    elif direct_download:
                        # برای فایل‌ها: کلیک مستقیم روی المان فایل (باید دانلود شروع شود)
                        await elem.click(timeout=5000)
                        await asyncio.sleep(3)
                    else:
                        # کلیک ساده و امید به دانلود
                        await elem.click(timeout=5000)
                        await asyncio.sleep(3)

                    # حذف شنونده
                    page.remove_listener("download", handle_download)

                    if download_occurred:
                        return True  # موفقیت
                except Exception as e:
                    logger.debug(f"کلیک روی {selector} ناموفق: {e}")
                    page.remove_listener("download", handle_download)
                    continue
        return False

    async def _download_inline_media(self, page: Page, post_id: str) -> None:
        """استخراج و دانلود مستقیم تصاویر/ویدئوهای بارگذاری‌شده (fallback)."""
        media_links = await page.evaluate('''() => {
            const links = new Set();
            const add = (url) => {
                if (url && url.startsWith('http') && !url.startsWith('data:')) links.add(url);
            };
            document.querySelectorAll('img[src]').forEach(img => add(img.src));
            document.querySelectorAll('video source[src], audio source[src]').forEach(el => add(el.src));
            document.querySelectorAll('a[href*="/file/"]').forEach(a => add(a.href));
            return Array.from(links);
        }''')

        if not media_links:
            logger.info("📭 هیچ رسانهٔ inline یافت نشد.")
            return

        for idx, link in enumerate(media_links):
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
                    await asyncio.sleep(2)

    def _guess_ext(self, response, url: str) -> str:
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type in self.MIME_TO_EXT:
            return self.MIME_TO_EXT[content_type]
        path = url.split("?")[0]
        if '.' in path:
            ext = path.rsplit('.', 1)[-1][:5]
            if ext.isalnum():
                return ext
        return "bin"
