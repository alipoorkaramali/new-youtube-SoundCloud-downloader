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
SCROLL_UP = -2000
HOME_URL = "https://web.telegram.org/a/"
OVERALL_TIMEOUT = 35 * 60

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

        self.screenshots_dir = self.base_dir / "post_screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

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

        self.logger.info(f"📁 دایرکتوری خروجی: {self.base_dir}")

    # ═══════════════════ متد اصلی ═══════════════════
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
        self._page = None

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                viewport={"width": 1366, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            self._page = page

            try:
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                self.logger.error(f"❌ صفحه اصلی باز نشد: {e}")
                await context.close()
                return []

            # ═══════════ بررسی لود کامل صفحه اصلی ═══════════
            self.logger.info("🔎 بررسی لود کامل صفحه اصلی...")
            try:
                await page.wait_for_selector('input[type="search"], div.chat-list, div.bubbles', timeout=15000)
                self.logger.info("✅ صفحه اصلی به درستی لود شد.")
            except Exception:
                self.logger.warning("⚠️ المان‌های صفحه اصلی پیدا نشدند. شاید سشن منقضی شده باشد.")
                await self._take_screenshot(page, "homepage_not_loaded")
                # ادامه می‌دهیم چون ممکن است با این حال کار کند

            entered = await self._search_and_enter_channel(page)
            if not entered:
                await context.close()
                return []

            await self._save_screenshot(page, "initial")

            # پرش به آخرین پست‌ها
            self.logger.info("⬇️ تلاش برای پرش به آخرین پست‌ها...")
            try:
                scroll_button_selectors = [
                    'button[title="Go to bottom"]',
                    'div[class*="scroll-to-bottom"]',
                    'div[class*="ScrollButton"]',
                    '[aria-label="Scroll to bottom"]',
                    'button:has(svg[class*="arrow-down"])',
                ]
                for sel in scroll_button_selectors:
                    btn = page.locator(sel).first
                    if await btn.count() > 0:
                        await btn.click(timeout=3000)
                        self.logger.info("   ✅ روی دکمهٔ فلش کلیک شد. منتظر بارگذاری آخرین پست‌ها...")
                        await asyncio.sleep(3)
                        break
                else:
                    self.logger.info("   ℹ️ دکمهٔ پرش به پایین پیدا نشد.")
            except Exception as e:
                self.logger.warning(f"   ⚠️ خطا در کلیک دکمه پرش: {e}")

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
                await page.evaluate("window.scrollBy(0, -2000)")
                await asyncio.sleep(2)
                new_height = await page.evaluate("document.documentElement.scrollHeight")

                if new_height == old_height:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0

            await self._save_screenshot(page, "final")
            await self._capture_post_screenshots(page, items)

            await context.close()
            self._page = None

        self.logger.info(f"📊 {len(items)} پست یکتا استخراج شد.")
        return items[:self.limit]

    # ═══════════════════ جستجو و ورود به کانال (مقاوم‌سازی شده) ═══════════════════
    async def _search_and_enter_channel(self, page) -> bool:
        # ۱. پیدا کردن نوار جستجو
        search_input = None
        for sel in [
            'input[placeholder*="Search"]',
            'input[role="textbox"]',
            '[data-testid="search-input"]'
        ]:
            try:
                search_input = await page.wait_for_selector(sel, timeout=10000)
                if search_input:
                    self.logger.info("🔍 نوار جستجو پیدا شد.")
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
        self.logger.info("⏳ منتظر نتایج...")

        # ۳. انتظار هوشمند برای نتایج (تا ۳۰ ثانیه)
        found = False
        for _ in range(15):  # 15 * 2s = 30s
            await asyncio.sleep(2)
            for sel in ['div[role="button"]', 'div.search-result', 'div.chatlist-item', 'a[data-peer-id]']:
                try:
                    if await page.locator(sel).count() > 0:
                        self.logger.info(f"✅ نتیجه پیدا شد با سلکتور '{sel}'")
                        found = True
                        break
                except Exception:
                    continue
            if found:
                break

        if not found:
            self.logger.error("❌ نتایج پیدا نشد.")
            await self._take_screenshot(page, "search_failed")
            return False

        self.logger.info("✅ نتایج جستجو ظاهر شدند.")
        await asyncio.sleep(2)

        # ۴. کلیک روی اولین نتیجه (با force و JavaScript)
        return await self._click_with_js_fallback(page)

    # ═══════════════════ کلیک مقاوم با JavaScript ═══════════════════
    async def _click_with_js_fallback(self, page) -> bool:
        """تلاش برای کلیک با force و در صورت شکست، کلیک از طریق JavaScript"""
        click_selectors = ['div.chatlist-item', 'div[role="button"]', 'div.search-result', 'a[data-peer-id]']

        for sel in click_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue

                # صبر برای visible با timeout بیشتر
                await loc.wait_for(state="visible", timeout=8000)
                self.logger.info(f" → کلیک با {sel}")
                await loc.click(timeout=10000, force=True)
                await asyncio.sleep(4)

                # بررسی موفقیت
                if await self._check_channel_opened(page):
                    return True
            except Exception as e:
                self.logger.debug(f"سلکتور {sel} با force click ناموفق: {e}")

        # ۵. کلیک با JavaScript (دور زدن مشکلات visibility)
        self.logger.info("🔄 تلاش کلیک با JavaScript...")
        try:
            # مستقیماً روی اولین عنصر معتبر کلیک کن
            await page.evaluate('''() => {
                const sel = 'div.chatlist-item, div[role="button"], div.search-result, a[data-peer-id]';
                const el = document.querySelector(sel);
                if (el) el.click();
                else {
                    // fallback: پیدا کردن با متن
                    const channel = document.querySelector('h3, .fullName, [dir="auto"]');
                    if (channel) channel.closest('a, div[role="button"]')?.click() || channel.click();
                }
            }''')
            await asyncio.sleep(4)

            if await self._check_channel_opened(page):
                return True
        except Exception as e:
            self.logger.error(f"❌ کلیک با JavaScript شکست: {e}")

        # ۶. Fallback نهایی: get_by_text با JavaScript
        self.logger.info(" 🔄 fallback نهایی با متن...")
        for name in [self.channel, self.channel.upper(), "BBCPersian"]:
            try:
                # با JavaScript المان را پیدا و کلیک کن
                await page.evaluate(f'''(name) => {{
                    const el = Array.from(document.querySelectorAll('h3, .fullName, [dir="auto"]'))
                        .find(e => e.textContent.trim() === name);
                    if (el) {{
                        el.click();
                        return true;
                    }}
                    return false;
                }}''', name)
                await asyncio.sleep(4)
                if await self._check_channel_opened(page):
                    return True
            except Exception:
                continue

        self.logger.error("❌ تمام روش‌های کلیک شکست خورد.")
        await self._take_screenshot(page, "click_failed")
        return False

    # ═══════════════════ بررسی ورود به کانال ═══════════════════
    async def _check_channel_opened(self, page) -> bool:
        try:
            await page.wait_for_selector('div.message, div[data-message-id], article[role="article"]', timeout=8000)
            self.logger.info("✅ کانال با موفقیت باز شد.")
            return True
        except Exception:
            self.logger.debug("⚠️ هنوز پیامی مشاهده نشد.")
            return False

    # ═══════════════════ سایر توابع (بدون تغییر) ═══════════════════
    async def _capture_post_screenshots(self, page, items): ...
    async def _save_screenshot(self, page, name): ...
    async def _take_screenshot(self, page, name): ...
    async def _download_media(self, items): ...
