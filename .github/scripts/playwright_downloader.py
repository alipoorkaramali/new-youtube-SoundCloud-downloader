#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from pathlib import Path
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright

logger = logging.getLogger("TelegramScraper")

class PlaywrightDownloader:
    """
    دانلود رسانه‌های پست‌های تلگرام با استفاده از یک پروفایل دائمی Playwright.
    دیگر نیازی به استخراج دستی کوکی یا ساخت سشن نیست.
    """

    def __init__(self,
                 profile_dir: Path,
                 media_dir: Path,
                 max_bytes: int,
                 delay_between_posts: float = 1.5):
        self.profile_dir = profile_dir
        self.media_dir = media_dir
        self.max_bytes = max_bytes
        self.delay = delay_between_posts
        self.media_dir.mkdir(parents=True, exist_ok=True)

    async def download_all(self, tasks: list[tuple[str, str]]) -> None:
        """
        tasks: لیستی از (post_url, post_id)
        """
        if not tasks:
            logger.info("هیچ پستی برای دانلود وجود ندارد.")
            return

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = await context.new_page()

            for post_url, post_id in tasks:
                try:
                    await self._process_post(page, post_url, post_id)
                except Exception as e:
                    logger.error(f"❌ خطا در پردازش {post_url}: {e}")
                # تأخیر بین پست‌ها برای جلوگیری از فشار روی تلگرام
                await asyncio.sleep(self.delay)

            await context.close()

    async def _process_post(self, page, post_url: str, post_id: str):
        """باز کردن یک پست و دانلود همهٔ رسانه‌های آن"""
        logger.info(f"📄 باز کردن {post_url}")
        try:
            await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            logger.error(f"⚠️ بارگذاری صفحه شکست خورد: {post_url}")
            return

        # منتظر بمانیم تا رسانه‌ها بارگذاری شوند (کمی تأخیر یا wait_for_selector)
        try:
            await page.wait_for_selector("img, video, a[download]", timeout=10000)
        except Exception:
            # اگر هیچ رسانه‌ای نبود، اشکالی ندارد
            pass

        # استخراج لینک‌های دانلود از صفحه
        media_links = await page.evaluate('''() => {
            const links = [];
            // 1. دکمه‌های دانلود فایل‌ها (اسناد، ویدئوهای قابل دانلود)
            document.querySelectorAll('a[download]').forEach(a => {
                const url = a.href;
                const filename = a.getAttribute('download') || url.split('/').pop().split('?')[0];
                if (url.startsWith('http')) links.push({url, filename});
            });
            // 2. تصاویر (عکس‌ها معمولاً در img با کلاس‌های خاص هستند)
            document.querySelectorAll('img').forEach(img => {
                const src = img.src;
                if (src && !src.startsWith('data:') && !src.includes('/emoji/') && img.naturalWidth > 50) {
                    const filename = src.split('/').pop().split('?')[0] || 'photo.jpg';
                    links.push({url: src, filename});
                }
            });
            // 3. ویدئوها و صداهای جاسازی‌شده
            document.querySelectorAll('video source, audio source').forEach(el => {
                const src = el.src;
                if (src && src.startsWith('http')) {
                    const filename = src.split('/').pop().split('?')[0] || 'media.mp4';
                    links.push({url: src, filename});
                }
            });
            // 4. لینک‌های مستقیم به فایل‌ها (ممکن است با کلاس‌های دیگر)
            document.querySelectorAll('a[href*="/file/"]').forEach(a => {
                if (!a.hasAttribute('download')) {
                    const filename = a.textContent.trim() || a.href.split('/').pop().split('?')[0];
                    links.push({url: a.href, filename});
                }
            });
            // حذف موارد تکراری
            const unique = [];
            const seen = new Set();
            for (const item of links) {
                if (!seen.has(item.url)) {
                    seen.add(item.url);
                    unique.push(item);
                }
            }
            return unique;
        }''')

        if not media_links:
            logger.info(f"📭 هیچ رسانه‌ای در {post_url} یافت نشد.")
            return

        logger.info(f"🎯 {len(media_links)} رسانه برای دانلود پیدا شد.")
        for item in media_links:
            await self._download_media(page, item["url"], item["filename"], post_id)

    async def _download_media(self, page, url: str, filename: str, post_id: str):
        """دانلود یک فایل رسانه با استفاده از page.request (با کوکی‌های سشن)"""
        safe_filename = self._sanitize_filename(filename)
        filepath = self.media_dir / f"{post_id}_{safe_filename}"
        if filepath.exists():
            logger.info(f"⏩ از قبل موجود: {filepath.name}")
            return

        try:
            response = await page.request.get(url)
            if not response.ok:
                logger.warning(f"⚠️ HTTP {response.status} برای {url}")
                return

            # بررسی حجم فایل
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > self.max_bytes:
                logger.info(f"⏩ رد شد (حجم {int(content_length)/1024/1024:.1f}MB > حد مجاز): {safe_filename}")
                return

            body = await response.body()
            if len(body) > self.max_bytes:
                logger.info(f"⏩ رد شد (حجم واقعی {len(body)/1024/1024:.1f}MB > حد مجاز): {safe_filename}")
                return

            with open(filepath, 'wb') as f:
                f.write(body)
            logger.info(f"✅ دانلود شد: {filepath.name} ({len(body)/1024/1024:.1f} MB)")
        except Exception as e:
            logger.error(f"❌ خطا در دانلود {url}: {e}")

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """حذف کاراکترهای غیرمجاز از نام فایل"""
        # جایگزینی کاراکترهای غیرمجاز در ویندوز/لینوکس
        invalid_chars = '<>:"/\\|?*'
        for ch in invalid_chars:
            filename = filename.replace(ch, '_')
        # محدود کردن طول
        if len(filename) > 150:
            name, ext = Path(filename).stem, Path(filename).suffix
            filename = name[:100] + ext
        return filename
