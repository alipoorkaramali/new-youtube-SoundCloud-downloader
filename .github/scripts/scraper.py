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
MAX_SCROLL_ATTEMPTS = 12
SCROLL_STEP = 2000
HOME_URL = "https://web.telegram.org/a/"
OVERALL_TIMEOUT = 35 * 60  # 35 دقیقه

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

    # ═══════════════════ متد اصلی (با timeout کلی و محافظت) ═══════════════════
    async def run(self):
        try:
            await asyncio.wait_for(self._run_impl(), timeout=OVERALL_TIMEOUT)
        except asyncio.TimeoutError:
            self.logger.error("⏰ اسکریپت به دلیل محدودیت زمانی کلی متوقف شد.")
        except Exception as e:
            self.logger.critical(f"❌ خطای مرگبار در اجرای اصلی: {e}", exc_info=True)

    async def _run_impl(self):
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
        last_count = 0

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                viewport={"width": 1366, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

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

            scroll_attempts = 0

            while len(items) < self.limit and scroll_attempts < MAX_SCROLL_ATTEMPTS:
                try:
                    messages = page.locator(
                        'div.message, div[data-message-id], article[role="article"], div.bubbles-group > div'
                    )
                    count = await messages.count()
                    self.logger.info(f"🔍 {count} المان پیام پیدا شد (قبلاً {last_count} تا).")

                    for i in range(last_count, count):
                        try:
                            msg = messages.nth(i)
                            msg_id = await msg.get_attribute('data-message-id')
                            if not msg_id:
                                inner = msg.locator('[data-message-id]').first
                                if await inner.count() > 0:
                                    msg_id = await inner.get_attribute('data-message-id')
                            if not msg_id or msg_id in seen_ids:
                                continue

                            text = (await msg.inner_text()).strip()[:600]
                            date_el = msg.locator('time, .message-date, .date, span[class*="date"]').first
                            date = ""
                            if await date_el.count() > 0:
                                date = await date_el.inner_text() or await date_el.get_attribute('datetime') or ""

                            items.append({
                                'id': msg_id,
                                'text': text,
                                'date': date,
                                'url': f"https://t.me/{self.channel}/{msg_id}"
                            })
                            seen_ids.add(msg_id)
                        except Exception:
                            continue

                    last_count = count
                    self.logger.info(f"📊 {len(items)} پست یکتا جمع‌آوری شد.")
                except Exception as e:
                    self.logger.error(f"❌ خطا در استخراج پست‌ها: {e}")

                if len(items) >= self.limit:
                    break

                old_height = await page.evaluate("document.documentElement.scrollHeight")
                await page.evaluate(f"window.scrollBy(0, {SCROLL_STEP})")
                await asyncio.sleep(2)
                new_height = await page.evaluate("document.documentElement.scrollHeight")

                if new_height == old_height:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0

            await context.close()

        self.logger.info(f"📊 {len(items)} پست یکتا استخراج شد.")
        return items[:self.limit]

    # ═══════════════════ جستجو و ورود به کانال (مقاوم‌سازی شده) ═══════════════════
    async def _search_and_enter_channel(self, page) -> bool:
        # ۱. پیدا کردن نوار جستجو
        search_input = None
        for sel in [
            'input[placeholder*="Search"], input[placeholder*="جستجو"]',
            'div.input-search input',
            '[data-testid="search-input"]',
            'input[role="textbox"]'
        ]:
            try:
                search_input = await page.wait_for_selector(sel, timeout=8000)
                if search_input:
                    self.logger.info(f"🔍 نوار جستجو پیدا شد: {sel[:50]}")
                    break
            except Exception:
                continue
        if not search_input:
            self.logger.error("❌ نوار جستجو پیدا نشد.")
            return False

        # ۲. جستجوی کانال
        await search_input.fill(self.channel)
        await asyncio.sleep(1)
        await search_input.press("Enter")

        self.logger.info("⏳ منتظر بارگذاری نتایج جستجو...")
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            self.logger.warning("⚠️ networkidle تایم‌اوت شد، ادامه با selector...")

        await asyncio.sleep(4)  # زمان مهم برای رندر نتایج

        # ۳. تلاش‌های متعدد برای تشخیص نتایج
        search_result_selectors = [
            'div.search-result',
            'div.chatlist-item',
            'a[data-peer-id]',
            'div.search-results',
            '[role="listitem"]',
            'div[role="button"]'
        ]

        has_results = False
        for sel in search_result_selectors:
            try:
                await page.wait_for_selector(sel, timeout=8000)
                self.logger.info(f"✅ نتایج جستجو با سلکتور پیدا شد: {sel}")
                has_results = True
                break
            except Exception:
                continue

        if not has_results:
            has_results = await page.evaluate(
                """() => !!document.querySelector('div.search-result, div.chatlist-item, a[data-peer-id], div.search-results')"""
            )

        if not has_results:
            self.logger.error("❌ نتایج جستجو پیدا نشدند.")
            await self._take_screenshot(page, "search_failed")
            return False

        self.logger.info("✅ نتایج جستجو ظاهر شدند.")
        return await self._click_search_result(page)

    async def _click_search_result(self, page) -> bool:
        click_selectors = [
            'div.search-result [role="link"]',
            'div.chatlist-item',
            'a[href*="/c/"]',
            'div.search-results div[role="button"]',
            'div.search-result',
        ]

        for attempt in range(2):
            for sel in click_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() == 0:
                        continue
                    await loc.wait_for(state="visible", timeout=3000)
                    self.logger.info(f"🖱️ تلاش برای کلیک با سلکتور: {sel} (دفعه {attempt+1})")
                    await loc.click(timeout=5000)
                    await asyncio.sleep(3)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=12000)
                        await asyncio.sleep(2)
                        await page.wait_for_selector(
                            'div.message, div[data-message-id], article[role="article"]',
                            timeout=8000
                        )
                        self.logger.info("✅ پیام‌ها به طور کامل بارگذاری شدند.")
                        return True
                    except Exception:
                        self.logger.warning("⚠️ کانال باز شد — اما پیام‌ها کامل لود نشدند. ادامه می‌دهیم.")
                        return True
                except Exception:
                    continue

        # روش کمکی get_by_role / get_by_text
        self.logger.info("🔄 تلاش با get_by_role/get_by_text...")
        for _ in range(2):
            try:
                link = page.get_by_role("link", name=self.channel).first
                if await link.count() == 0:
                    link = page.get_by_text(self.channel, exact=False).first
                if await link.count() > 0:
                    await link.click(timeout=5000)
                    await asyncio.sleep(3)
                    await page.wait_for_load_state("networkidle", timeout=12000)
                    await asyncio.sleep(2)
                    try:
                        await page.wait_for_selector('div.message, div[data-message-id]', timeout=8000)
                        self.logger.info("✅ با get_by_role/text وارد کانال شدیم.")
                    except Exception:
                        self.logger.warning("⚠️ ورود با get_by_role/text موفق بود، پیام‌ها شاید کامل نباشند.")
                    return True
            except Exception as e:
                self.logger.error(f"❌ get_by_role/text شکست: {e}")
            await asyncio.sleep(1)

        self.logger.error("❌ نتوانستیم روی هیچ نتیجه‌ای کلیک کنیم.")
        return False

    # ═══════════════════ اسکرین‌شات برای دیباگ ═══════════════════
    async def _take_screenshot(self, page, name: str):
        try:
            path = self.base_dir / f"debug_{name}.png"
            await page.screenshot(path=path, full_page=True)
            self.logger.info(f"📸 اسکرین‌شات ذخیره شد: {path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ ذخیره اسکرین‌شات شکست: {e}")

    # ═══════════════════ دانلود رسانه‌ها ═══════════════════
    async def _download_media(self, items: List[Dict]):
        tasks = []
        media_map = {str(item['id']): [] for item in items}
        for item in items:
            post_url = item.get('url', '')
            if post_url:
                tasks.append((post_url, str(item['id'])))

        downloaded = 0
        if tasks:
            downloader = PlaywrightDownloader(
                self.profile_dir, self.media_dir, self.max_media_bytes,
                self.delay_between_posts
            )
            await downloader.download_all(tasks)

            for f in self.media_dir.iterdir():
                if f.is_file() and '_' in f.stem:
                    pid = f.stem.split('_', 1)[0]
                    if pid in media_map:
                        media_map[pid].append(f"media/{f.name}")
                        downloaded += 1

        return media_map, downloaded
