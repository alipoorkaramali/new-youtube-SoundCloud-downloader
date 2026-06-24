#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from pathlib import Path
from playwright.async_api import async_playwright

logger = logging.getLogger("TelegramScraper")

class PlaywrightDownloader:
    """دانلود رسانه‌ها با استخراج لینک از DOM و دانلود مستقیم با page.request"""

    def __init__(self, profile_dir: Path, media_dir: Path, max_bytes: int, delay: float = 1.5):
        self.profile_dir = profile_dir
        self.media_dir = media_dir
        self.max_bytes = max_bytes
        self.delay = delay
        self.media_dir.mkdir(parents=True, exist_ok=True)

    async def download_all(self, tasks: list[tuple[str, str]]) -> None:
        if not tasks:
            return

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            page = await context.new_page()

            # ابتدا صفحه اصلی را باز کن تا سشن کاملاً فعال شود
            await page.goto("https://web.telegram.org/a/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            for post_url, post_id in tasks:
                try:
                    await self._process_post(page, post_url, post_id)
                except Exception as e:
                    logger.error(f"❌ خطا در پردازش {post_url}: {e}")
                await asyncio.sleep(self.delay)

            await context.close()

    async def _process_post(self, page, post_url: str, post_id: str):
        logger.info(f"📄 باز کردن {post_url}")
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        # صبر برای بارگذاری کامل رسانه‌ها (lazy-load)
        await asyncio.sleep(5)

        # استخراج تمام لینک‌های رسانه (عکس، ویدئو، فایل، صدا)
        media_links = await page.evaluate('''() => {
            const links = new Set();
            // تصاویر و ویدئوها: src, currentSrc, srcset
            document.querySelectorAll('img, video source, audio source').forEach(el => {
                let src = el.src || el.currentSrc || '';
                if (!src) {
                    const srcset = el.getAttribute('srcset');
                    if (srcset) src = srcset.split(',')[0]?.trim()?.split(' ')[0] || '';
                }
                if (src && src.startsWith('http')) links.add(src);
            });
            // دکمه‌های دانلود فایل
            document.querySelectorAll('a[download], a[href*="/file/"], a[href*="t.me/file"]').forEach(a => {
                if (a.href) links.add(a.href);
            });
            return Array.from(links);
        }''')

        if not media_links:
            logger.info(f"📭 هیچ رسانه‌ای در {post_url} یافت نشد.")
            return

        logger.info(f"🎯 {len(media_links)} لینک رسانه پیدا شد.")

        for idx, link in enumerate(media_links):
            try:
                # درخواست با هدرهای مناسب (Referrer مهم است)
                response = await page.request.get(link, {
                    "headers": {"Referer": "https://web.telegram.org/"}
                })
                if response.ok:
                    body = await response.body()
                    if len(body) > self.max_bytes:
                        logger.info(f"⏩ رد شد (حجم {len(body)/1024/1024:.1f}MB): {link}")
                        continue
                    # استخراج پسوند
                    ext = link.split('.')[-1].split('?')[0][:5] or "bin"
                    filepath = self.media_dir / f"{post_id}_{idx}.{ext}"
                    with open(filepath, 'wb') as f:
                        f.write(body)
                    logger.info(f"✅ دانلود شد: {filepath.name} ({len(body)/1024/1024:.1f} MB)")
                else:
                    logger.warning(f"⚠️ HTTP {response.status} برای {link}")
            except Exception as e:
                logger.error(f"❌ خطا در دانلود {link}: {e}")
