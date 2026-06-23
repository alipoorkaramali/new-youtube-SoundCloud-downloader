#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from pathlib import Path
from datetime import timedelta
from typing import List, Dict

from apify_client import ApifyClient
from config_loader import Config
from telegram_session import TelegramSession
from downloader import Downloader
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
        self.session_file = Path(config.session_file)
        self.rate_limit = config.rate_limit

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

        self.tg_session = TelegramSession(self.session_file, self.rate_limit)

    async def run(self):
        self.logger.info(f"🚀 شروع اسکریپر برای @{self.channel} (limit={self.limit})")
        items = self._scrape_with_apify()
        if not items:
            self.logger.warning("هیچ پستی از Apify دریافت نشد.")
            return
        self.logger.info(f"📥 {len(items)} پست دریافت شد.")

        if not self.tg_session.load():
            self.logger.error("❌ سشن تلگرام بارگذاری نشد.")
            return

        media_map, downloaded = await self._enrich_and_download(items)
        self.logger.info(f"🖼️ {downloaded} فایل رسانه دانلود شد.")

        gen = OutputGenerator(self.base_dir, self.channel, items, media_map)
        gen.generate_json()
        gen.generate_csv()
        gen.generate_html()
        gen.create_zip()

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
        download_tasks = []
        media_map = {}
        tg_cookies = self.tg_session.cookies

        for idx, item in enumerate(items):
            post_id = str(item.get('id') or item.get('message_id') or f"post_{idx}")
            post_url = item.get('url') or ''

            # جمع‌آوری لینک‌های Apify
            actor_urls = set()
            for key in ['photos', 'videos', 'documents', 'audio']:
                val = item.get(key)
                if isinstance(val, list):
                    for m in val:
                        url = m if isinstance(m, str) else (m.get('url') or m.get('Url') or '')
                        if url: actor_urls.add(url)
                elif isinstance(val, str) and val.startswith('http'):
                    actor_urls.add(val)
            if 'media' in item:
                m = item['media']
                if isinstance(m, list):
                    for u in m:
                        if isinstance(u, str): actor_urls.add(u)
                        elif isinstance(u, dict): actor_urls.add(u.get('url') or u.get('Url') or '')
                elif isinstance(m, str) and m.startswith('http'):
                    actor_urls.add(m)

            best_links = self.tg_session.get_best_media_links(post_url) if post_url else []

            final_urls = {}
            for bl in best_links:
                final_urls[bl['url']] = bl
            for url in actor_urls:
                if url not in final_urls:
                    fn = url.split('/')[-1].split('?')[0]
                    final_urls[url] = {'url': url, 'filename': fn, 'media_type': 'unknown'}

            post_media_rel_paths = []
            for mi, (url, info) in enumerate(final_urls.items()):
                ext = "bin"
                if info.get("filename") and '.' in info["filename"]:
                    ext = info["filename"].split('.')[-1]
                else:
                    fn = url.split('/')[-1].split('?')[0]
                    if '.' in fn: ext = fn.split('.')[-1].split('?')[0][:10]
                filename = f"{post_id}_{mi}.{ext}"
                filepath = self.media_dir / filename
                rel_path = f"media/{filename}"

                if filepath.exists():
                    post_media_rel_paths.append(rel_path)
                    continue
                download_tasks.append({"url": url, "filepath": filepath, "filename": filename})
                post_media_rel_paths.append(rel_path)

            media_map[post_id] = post_media_rel_paths

        if download_tasks:
            downloader = Downloader(self.media_dir, self.max_media_bytes, cookies=tg_cookies)
            await downloader.download_all(download_tasks)

        downloaded_count = sum(1 for p in sum(media_map.values(), []) if (self.base_dir / p).exists())
        return media_map, downloaded_count

    def _cleanup_old_media(self, media_map):
        needed_files = set()
        for paths in media_map.values():
            for p in paths:
                needed_files.add(Path(p).name)
        if not self.media_dir.exists(): return
        removed = 0
        for f in self.media_dir.iterdir():
            if f.is_file() and f.name not in needed_files:
                f.unlink()
                removed += 1
        if removed:
            self.logger.info(f"🧹 {removed} فایل قدیمی پاک شد.")
        else:
            self.logger.info("✅ فایل قدیمی‌ای برای پاکسازی نبود.")