#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from pathlib import Path
from typing import List, Dict

from config_loader import Config
from playwright_downloader import PlaywrightDownloader
from output_generator import OutputGenerator

class TelegramChannelScraper:

    def __init__(self, config: Config):
        self.config = config
        self.channel = config.channel
        self.limit = config.limit
        self.max_media_bytes = config.max_media_mb * 1024 * 1024
        self.base_dir = Path(config.output_dir) / "telegram_downloads" / self.channel
        self.media_dir = self.base_dir / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)

        self.profile_dir = Path(config.profile_dir)
        self.delay_between_posts = config.delay_between_posts

        self.logger = logging.getLogger("TelegramScraper")
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        fh = logging.FileHandler(self.base_dir / "scraper.log", encoding='utf-8')
        fh.setFormatter(formatter)
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(fh)
            self.logger.addHandler(ch)

    async def run(self):
        self.logger.info(f"🚀 شروع اسکریپر مستقل برای @{self.channel} (limit={self.limit})")

        # ۱. دریافت پست‌ها مستقیماً از تلگرام وب
        items = await self._fetch_posts_from_telegram()
        if not items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            return
        self.logger.info(f"📥 {len(items)} پست استخراج شد.")

        # ۲. دانلود رسانه‌ها
        media_map, downloaded = await self._download_media(items)
        self.logger.info(f"🖼️ {downloaded} فایل رسانه دانلود شد.")

        # ۳. تولید خروجی‌ها
        gen = OutputGenerator(self.base_dir, self.channel, items, media_map)
        gen.generate_json()
        gen.generate_csv()
        gen.generate_html()
        gen.create_zip()

        self.logger.info("✅ پایان موفقیت‌آمیز.")

    async def _fetch_posts_from_telegram(self) -> List[Dict]:
        """
        با Playwright وارد کانال می‌شود و اطلاعات پست‌ها را از DOM استخراج می‌کند.
        """
        from playwright.async_api import async_playwright
        items = []

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = await context.new_page()

            # باز کردن صفحهٔ اصلی و رفتن به کانال
            await page.goto("https://web.telegram.org/a/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # جستجو و باز کردن کانال
            search_input = page.locator('input[type="search"]')
            await search_input.fill(self.channel)
            await asyncio.sleep(1)
            await search_input.press("Enter")
            await asyncio.sleep(2)

            # کلیک روی اولین نتیجه (معمولاً کانال)
            first_result = page.locator('div.search-result, a[href*="' + self.channel + '"]').first
            await first_result.click()
            await asyncio.sleep(2)

            # اسکرول تدریجی برای جمع‌آوری پست‌ها
            while len(items) < self.limit:
                # استخراج پست‌های فعلی از DOM
                new_items = await page.evaluate('''() => {
                    const posts = [];
                    document.querySelectorAll('div.message, div[class*="Message"]').forEach(msg => {
                        const id = msg.getAttribute('data-message-id') || msg.id || '';
                        if (!id) return;
                        const textEl = msg.querySelector('div.text-content, div[class*="text"]');
                        const text = textEl ? textEl.innerText : '';
                        const dateEl = msg.querySelector('time, span[class*="date"]');
                        const date = dateEl ? (dateEl.getAttribute('datetime') || dateEl.innerText) : '';
                        const linkEl = msg.querySelector('a[href*="/' + self.channel + '/"]');
                        const url = linkEl ? linkEl.href : '';
                        posts.push({ id, text, date, url });
                    });
                    return posts;
                }''')
                # اضافه کردن پست‌های جدید (بدون تکراری)
                existing_ids = {item['id'] for item in items}
                for post in new_items:
                    if post['id'] and post['id'] not in existing_ids:
                        items.append(post)
                        existing_ids.add(post['id'])
                        if len(items) >= self.limit:
                            break

                if len(items) >= self.limit:
                    break

                # اسکرول به پایین
                await page.evaluate('window.scrollBy(0, 2000)')
                await asyncio.sleep(self.delay_between_posts)

            await context.close()

        return items[:self.limit]

    async def _download_media(self, items: List[Dict]):
        """
        برای هر پست، صفحهٔ آن را باز می‌کند و رسانه‌ها را دانلود می‌کند.
        """
        tasks = []
        media_map = {str(item['id']): [] for item in items}
        for item in items:
            post_url = item.get('url', '')
            if post_url:
                tasks.append((post_url, str(item['id'])))

        if tasks:
            downloader = PlaywrightDownloader(
                self.profile_dir, self.media_dir, self.max_media_bytes,
                self.delay_between_posts
            )
            await downloader.download_all(tasks)

        # پر کردن media_map با فایل‌های واقعی دانلودشده
        for f in self.media_dir.iterdir():
            if f.is_file():
                parts = f.stem.split('_', 1)
                pid = parts[0] if parts else ''
                if pid in media_map:
                    media_map[pid].append(f"media/{f.name}")

        downloaded_count = sum(len(v) for v in media_map.values())
        return media_map, downloaded_count
