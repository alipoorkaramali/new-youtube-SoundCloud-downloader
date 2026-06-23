#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
import logging
from pathlib import Path
from typing import List, Dict, Optional
from tqdm.asyncio import tqdm

logger = logging.getLogger("TelegramScraper")

class Downloader:
    def __init__(self, media_dir: Path, max_bytes: int, cookies: Optional[Dict] = None, max_retries: int = 3):
        self.media_dir = media_dir
        self.max_bytes = max_bytes
        self.cookies = cookies or {}
        self.max_retries = max_retries
        self.media_dir.mkdir(parents=True, exist_ok=True)

    async def download_all(self, tasks: List[Dict]):
        if not tasks:
            logger.info("هیچ فایلی برای دانلود نیست.")
            return
        connector = aiohttp.TCPConnector(limit=8)
        timeout = aiohttp.ClientTimeout(total=120, connect=15)
        async with aiohttp.ClientSession(cookies=self.cookies, connector=connector, timeout=timeout) as session:
            coros = [self._download_with_retry(session, t) for t in tasks]
            for coro in tqdm(asyncio.as_completed(coros), total=len(coros), desc="📥 دانلود"):
                await coro

    async def _download_with_retry(self, session, task):
        for attempt in range(1, self.max_retries + 1):
            try:
                await self._download_one(session, task)
                return
            except Exception as e:
                logger.error(f"تلاش {attempt}/{self.max_retries} برای {task.get('filename','?')}: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
        logger.error(f"❌ دانلود {task.get('filename','?')} ناموفق ماند.")

    async def _download_one(self, session, task):
        url = task["url"]
        filepath: Path = task["filepath"]
        filename = task.get("filename", filepath.name)

        try:
            async with session.head(url, timeout=15) as resp:
                if resp.status == 200 and resp.content_length and resp.content_length > self.max_bytes:
                    logger.info(f"⏩ رد شد (حجم بالا): {filename}")
                    return
        except Exception:
            pass

        async with session.get(url) as resp:
            if resp.status != 200:
                raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status, message="HTTP error")
            downloaded = 0
            with open(filepath, 'wb') as f:
                async for chunk in resp.content.iter_chunked(16384):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > self.max_bytes:
                        f.close()
                        filepath.unlink(missing_ok=True)
                        logger.info(f"⏩ متوقف شد (حجم): {filename}")
                        return
            logger.info(f"✅ دانلود شد: {filename} ({downloaded/1024/1024:.1f} MB)")