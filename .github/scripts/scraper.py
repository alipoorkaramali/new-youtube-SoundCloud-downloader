#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from pathlib import Path
from datetime import timedelta
from typing import List, Dict

from apify_client import ApifyClient
from config_loader import Config
from playwright_downloader import PlaywrightDownloader   # ← جدید
from output_generator import OutputGenerator

class TelegramChannelScraper:
    ACTOR_ID = "ahaham_bytiz/telegram-channel-scraper"

    def __init__(self, config: Config):
        self.config = config
        self.channel = config.channel.lstrip('@')
        self.limit = config.limit
        self.max_media_bytes = config.max_media_mb * 1024 * 1024
        self.base_dir = Path(config.output_dir) / "telegram_downloads" / self.channel
        self.media_dir = self.base_dir / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # مسیر پروفایل دائمی مرورگر (همان که save_session.py ساخت)
        self.profile_dir = Path(config.profile_dir)
        # فاصلهٔ زمانی بین بارگذاری پست‌ها (ثانیه)
        self.delay_between_posts = config.delay_between_posts

        # راه‌اندازی لاگر
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
        self.logger.info(f"🚀 شروع اسکریپر برای @{self.channel} (limit={self.limit})")
        items = self._scrape_with_apify()
        if not items:
            self.logger.warning("هیچ پستی از Apify دریافت نشد.")
            return
        self.logger.info(f"📥 {len(items)} پست دریافت شد.")

        # دانلود رسانه‌ها با Playwright (بدون نیاز به سشن دستی)
        media_map, downloaded = await self._enrich_and_download(items)
        self.logger.info(f"🖼️ {downloaded} فایل رسانه دانلود شد.")

        # تولید خروجی‌ها
        gen = OutputGenerator(self.base_dir, self.channel, items, media_map)
        gen.generate_json()
        gen.generate_csv()
        gen.generate_html()
        gen.create_zip()

        # پاکسازی فایل‌های قدیمی
        self._cleanup_old_media(media_map)
        self.logger.info("✅ پایان موفقیت‌آمیز.")

    def _scrape_with_apify(self) -> List[Dict]:
        client = ApifyClient(self.config.apify_token)
        run_input = {
            "channels": [self.channel],
            "maxMessagesPerChannel": self.limit,
            "includeMedia": True,
            "enableReactions": False,
            "enableViews": True
        }
        run = client.actor(self.ACTOR_ID).call(
            run_input=run_input,
            wait_duration=timedelta(minutes=5)
        )
        if run is None or run.status != 'SUCCEEDED':
            self.logger.error(f"Apify اجرا ناموفق. وضعیت: {run.status if run else 'None'}")
            return []
        dataset = client.dataset(run.default_dataset_id)
        items = list(dataset.iterate_items())
        items.sort(key=lambda x: x.get('date') or x.get('Date', ''), reverse=True)
        return items

    async def _enrich_and_download(self, items: List[Dict]):
        """
        به‌جای استخراج دستی لینک‌های دانلود، مستقیماً با Playwright
        صفحهٔ هر پست را باز می‌کنیم و فایل‌های رسانه را دانلود می‌کنیم.
        """
        tasks = []
        media_map = {}
        for item in items:
            post_id = str(item.get('id') or item.get('message_id') or '')
            post_url = item.get('url', '')
            if post_url:
                tasks.append((post_url, post_id))
                media_map[post_id] = []

        if not tasks:
            return media_map, 0

        # دانلود با Playwright
        downloader = PlaywrightDownloader(
            self.profile_dir, self.media_dir, self.max_media_bytes,
            self.delay_between_posts
        )
        await downloader.download_all(tasks)

        # پر کردن media_map با فایل‌های واقعی دانلودشده
        for f in self.media_dir.iterdir():
            if f.is_file():
                # نام فایل‌ها به‌صورت {post_id}_{rest}.ext ذخیره شده‌اند
                parts = f.stem.split('_', 1)
                pid = parts[0] if parts else ''
                if pid in media_map:
                    media_map[pid].append(f"media/{f.name}")

        downloaded_count = sum(len(v) for v in media_map.values())
        return media_map, downloaded_count

    def _cleanup_old_media(self, media_map):
        needed_files = set()
        for paths in media_map.values():
            for p in paths:
                needed_files.add(Path(p).name)
        if not self.media_dir.exists():
            return
        removed = 0
        for f in self.media_dir.iterdir():
            if f.is_file() and f.name not in needed_files:
                f.unlink()
                removed += 1
        if removed:
            self.logger.info(f"🧹 {removed} فایل قدیمی پاک شد.")
        else:
            self.logger.info("✅ فایل قدیمی‌ای برای پاکسازی نبود.")
