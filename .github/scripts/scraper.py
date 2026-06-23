#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from pathlib import Path
from typing import List, Dict

from config_loader import Config
from playwright_downloader import PlaywrightDownloader
from output_generator import OutputGenerator

# ═══════════════════ Constants ═══════════════════
MAX_SCROLL_ATTEMPTS = 10
SCROLL_STEP = 1800
HOME_URL = "https://web.telegram.org/a/"

class TelegramChannelScraper:

    def __init__(self, config: Config):
        self.config = config
        self.channel = config.channel.lstrip('@')
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

    # ═══════════════════ متد اصلی ═══════════════════
    async def run(self):
        self.logger.info(f"🚀 شروع اسکریپر مستقل برای @{self.channel} (limit={self.limit})")
        items = await self._fetch_posts_from_telegram()
        if not items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            return
        self.logger.info(f"📥 {len(items)} پست استخراج شد.")

        media_map, downloaded = await self._download_media(items)
        self.logger.info(f"🖼️ {downloaded} فایل رسانه دانلود شد.")

        gen = OutputGenerator(self.base_dir, self.channel, items, media_map)
        gen.generate_json()
        gen.generate_csv()
        gen.generate_html()
        gen.create_zip()

        self.logger.info("✅ پایان موفقیت‌آمیز.")

    # ═══════════════════ استخراج پست‌ها ═══════════════════
    async def _fetch_posts_from_telegram(self) -> List[Dict]:
        from playwright.async_api import async_playwright

        items = []
        seen_ids = set()
        channel_clean = self.channel.lstrip('@')

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                viewport={"width": 1366, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

            try:
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                self.logger.error(f"❌ صفحه اصلی باز نشد: {e}")
                await context.close()
                return []

            entered = await self._search_and_enter_channel(page)
            if not entered:
                await context.close()
                return []

            last_height = 0
            scroll_attempts = 0
            max_scrolls = (self.limit // 20) + MAX_SCROLL_ATTEMPTS
            start_time = asyncio.get_event_loop().time()

            while len(items) < self.limit and scroll_attempts < max_scrolls:
                if asyncio.get_event_loop().time() - start_time > 300:
                    self.logger.warning("⏰ محدودیت زمانی ۵ دقیقه‌ای اسکرول فرا رسید.")
                    break

                try:
                    new_posts = await page.evaluate("""
                    (channel) => {
                        const posts = [];
                        const messageSelectors = [
                            'div.message', 'div.bubbles-group > div', 'div[data-message-id]',
                            '[data-peer-id] div.message', 'div.chatlist-message', 'div[class*="Message"]'
                        ];
                        const allMessages = new Set();
                        messageSelectors.forEach(sel => {
                            document.querySelectorAll(sel).forEach(el => allMessages.add(el));
                        });

                        for (const el of allMessages) {
                            let id = el.getAttribute('data-message-id') ||
                                     el.closest('[data-message-id]')?.getAttribute('data-message-id') ||
                                     el.querySelector('[data-message-id]')?.getAttribute('data-message-id');
                            if (!id || posts.some(p => p.id === id)) continue;

                            const textEl = el.querySelector('.text-content, .message-text, .bubble-content, div[class*="text"]');
                            const text = textEl ? textEl.innerText.trim() : '';

                            const dateEl = el.querySelector('time, .message-date, span[class*="date"]');
                            const date = dateEl ? (dateEl.getAttribute('datetime') || dateEl.innerText) : '';

                            const linkEl = el.querySelector(`a[href*="/${channel}/"]`);
                            const url = linkEl ? linkEl.href : '';

                            const hasMedia = !!el.querySelector('img, video, .media-wrapper, a[download], a[href*="/file/"]');
                            const viewsEl = el.querySelector('.views, .message-views, .stats, .view-count');
                            const views = viewsEl ? viewsEl.innerText.trim() : '';
                            const is_forwarded = !!el.querySelector('.forwarded, .fwd, .forward-info');

                            posts.push({ id, text, date, url, has_media: hasMedia, views, is_forwarded });
                        }
                        return posts;
                    }
                    """, channel_clean)
                except Exception as e:
                    self.logger.error(f"❌ خطا در استخراج پست‌ها: {e}")
                    await asyncio.sleep(1)
                    continue

                for post in new_posts:
                    if post.get('id') and post['id'] not in seen_ids:
                        seen_ids.add(post['id'])
                        items.append(post)

                if len(items) >= self.limit:
                    break

                try:
                    current_height = await page.evaluate("document.documentElement.scrollHeight")
                except Exception:
                    current_height = last_height

                if current_height == last_height:
                    scroll_attempts += 1
                    await asyncio.sleep(1.5)
                else:
                    scroll_attempts = 0
                last_height = current_height

                try:
                    await page.evaluate(f"window.scrollBy(0, {SCROLL_STEP})")
                except Exception as e:
                    self.logger.warning(f"⚠️ خطا در اسکرول: {e}")

                await asyncio.sleep(self.delay_between_posts)

            await context.close()

        self.logger.info(f"📊 {len(items)} پست یکتا استخراج شد.")
        return items[:self.limit]

    # ═══════════════════ جستجو و ورود به کانال (اصلاح‌شده) ═══════════════════
    async def _search_and_enter_channel(self, page) -> bool:
        """جستجو و ورود به کانال با پایداری بالاتر"""
        search_selectors = [
            'input[placeholder*="Search"], input[placeholder*="جستجو"]',
            'div.input-search input',
            '[data-testid="search-input"]',
            'input[role="textbox"]'
        ]

        for sel in search_selectors:
            try:
                search_input = await page.wait_for_selector(sel, timeout=8000)
                if search_input:
                    self.logger.info(f"🔍 نوار جستجو پیدا شد: {sel[:50]}")
                    await search_input.fill(self.channel)
                    await asyncio.sleep(1)
                    await search_input.press("Enter")
                    self.logger.info(f"🔎 جستجوی @{self.channel} انجام شد.")
                    break
            except Exception:
                continue
        else:
            self.logger.error("❌ نوار جستجو پیدا نشد.")
            return False

        # منتظر نتایج
        try:
            await page.wait_for_selector('div.search-results, a[data-peer-id]', timeout=12000)
        except Exception:
            self.logger.error("❌ نتایج جستجو ظاهر نشد.")
            return False

        # کلیک روی نتیجه
        click_selectors = ['a[data-peer-id]', 'div.search-result a', 'a.chatlist-chat', '.chatlist .row']
        for sel in click_selectors:
            try:
                first_result = page.locator(sel).first
                await first_result.click(timeout=7000)
                await asyncio.sleep(2)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                self.logger.info(f"✅ با موفقیت وارد کانال @{self.channel} شدیم.")
                return True
            except Exception as e:
                self.logger.debug(f"Selector {sel} کار نکرد: {e}")
                continue

        self.logger.error("❌ نتوانستیم روی هیچ نتیجه‌ای کلیک کنیم.")
        return False

    # ═══════════════════ دانلود رسانه‌ها ═══════════════════
    async def _download_media(self, items: List[Dict]):
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

        for f in self.media_dir.iterdir():
            if f.is_file():
                parts = f.stem.split('_', 1)
                pid = parts[0] if parts else ''
                if pid in media_map:
                    media_map[pid].append(f"media/{f.name}")

        downloaded_count = sum(len(v) for v in media_map.values())
        return media_map, downloaded_count
