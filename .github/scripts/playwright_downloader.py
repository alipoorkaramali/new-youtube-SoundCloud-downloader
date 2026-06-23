#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from pathlib import Path
from playwright.async_api import async_playwright

logger = logging.getLogger("TelegramScraper")

class PlaywrightDownloader:
    """دانلود رسانه‌ها با کلیک روی دکمهٔ دانلود و دریافت رویداد download."""

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
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = await context.new_page()

            # ابتدا صفحهٔ اصلی برای فعال‌سازی کامل سشن
            logger.info("📄 باز کردن صفحهٔ اصلی تلگرام...")
            await page.goto("https://web.telegram.org/a/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            for post_url, post_id in tasks:
                try:
                    await self._process_post(page, post_url, post_id)
                except Exception as e:
                    logger.error(f"❌ خطا در {post_url}: {e}")
                await asyncio.sleep(self.delay)

            await context.close()

    async def _process_post(self, page, post_url: str, post_id: str):
        logger.info(f"📄 باز کردن {post_url}")
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # پیدا کردن همهٔ دکمه‌های دانلود
        download_buttons = page.locator('a[download]')
        count = await download_buttons.count()
        logger.info(f"🔍 {count} دکمهٔ دانلود پیدا شد.")

        for i in range(count):
            try:
                btn = download_buttons.nth(i)
                async with page.expect_download() as download_info:
                    await btn.click()
                download = await download_info.value
                filename = download.suggested_filename or f"file_{post_id}_{i}"
                filepath = self.media_dir / f"{post_id}_{filename}"

                if filepath.exists():
                    logger.info(f"⏩ از قبل موجود: {filepath.name}")
                    continue

                await download.save_as(str(filepath))
                size = filepath.stat().st_size
                if size > self.max_bytes:
                    filepath.unlink()
                    logger.info(f"⏩ رد شد (حجم {size/1024/1024:.1f}MB): {filename}")
                else:
                    logger.info(f"✅ دانلود شد: {filepath.name} ({size/1024/1024:.1f} MB)")
            except Exception as e:
                logger.error(f"❌ خطا در کلیک/دانلود دکمهٔ {i}: {e}")
