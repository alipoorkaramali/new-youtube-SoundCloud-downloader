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

    # ═══════════════════ جستجو و ورود به کانال ═══════════════════
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
        await asyncio.sleep(5)

        # ۳. کلیک روی تب Channels (اگر وجود دارد)
        try:
            channels_tab = page.get_by_role("tab", name="Channels").first
            if await channels_tab.count() > 0:
                await channels_tab.click()
                await asyncio.sleep(3)
                self.logger.info("📑 تب Channels انتخاب شد.")
        except Exception:
            pass

        # ۴. انتظار هوشمند برای نتایج
        found = False
        for wait_time in [10, 20, 30]:
            await asyncio.sleep(wait_time)
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
        await self._take_screenshot(page, f"search_results_{self.channel}")
        await asyncio.sleep(2)

        # ۵. کلیک روی اولین نتیجه (مقاوم و چندلایه)
        return await self._click_search_result(page)

    # ═══════════════════ کلیک روی نتیجه (force + JS) ═══════════════════
    async def _click_search_result(self, page) -> bool:
        """کلیک هوشمند: ابتدا تلاش با سلکتورهای رایج، سپس کلیک روی متنی که نام کانال باشد."""
        # لایهٔ ۱: سلکتورهای رایج
        click_selectors = [
            'div.chatlist-item', 'div[role="button"]', 'div.search-result',
            'a[data-peer-id]', 'div[class*="chatlist"] div[class*="item"]',
            'div[class*="ListItem"]', 'div[class*="search-result"]'
        ]
        for sel in click_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                # سعی می‌کنیم حتی اگر visible نباشد با force کلیک کنیم
                await loc.click(timeout=8000, force=True)
                await asyncio.sleep(4)
                if await page.locator('div.message, div[data-message-id]').count() > 0:
                    self.logger.info("✅ کانال با موفقیت باز شد (سلکتور %s).", sel)
                    return True
            except Exception as e:
                self.logger.debug("سلکتور %s ناموفق: %s", sel, e)

        # لایهٔ ۲: کلیک با JavaScript روی اسم کانال (در لیست نتایج)
        self.logger.info("🔄 تلاش کلیک با JavaScript روی نام کانال...")
        try:
            await page.evaluate(f'''(channel) => {{
                const els = Array.from(document.querySelectorAll('h3, .fullName, [dir="auto"], div[class*="name"], span[class*="peer-title"]'));
                const target = els.find(el => el.textContent.trim().toLowerCase() === channel.toLowerCase());
                if (target) {{
                    target.closest('div[role="button"], div.chatlist-item, a')?.click();
                }}
            }}''', self.channel)
            await asyncio.sleep(4)
            if await page.locator('div.message, div[data-message-id]').count() > 0:
                self.logger.info("✅ با JavaScript (نام کانال) وارد شدیم.")
                return True
        except Exception as e:
            self.logger.debug("JavaScript name click: %s", e)

        # لایهٔ ۳: کلیک روی اولین آیتم موجود در لیست (بدون توجه به نام)
        self.logger.info("🔄 تلاش کلیک با JavaScript روی اولین نتیجه...")
        try:
            await page.evaluate('''() => {
                const item = document.querySelector('div.chatlist-item, div[role="button"], div.search-result, a[data-peer-id]');
                if (item) item.click();
            }''')
            await asyncio.sleep(4)
            if await page.locator('div.message, div[data-message-id]').count() > 0:
                self.logger.info("✅ با JavaScript (اولین نتیجه) وارد شدیم.")
                return True
        except Exception as e:
            self.logger.debug("JavaScript generic click: %s", e)

        self.logger.error("❌ تمام روش‌های کلیک شکست خورد.")
        await self._take_screenshot(page, "click_failed")
        return False

    # ═══════════════════ اسکرین‌شات از تکتک پست‌ها ═══════════════════
    async def _capture_post_screenshots(self, page, items: List[Dict]):
        self.logger.info(f"📸 گرفتن اسکرین‌شات از {len(items)} پست...")
        for idx, item in enumerate(items):
            msg_id = item['id']
            try:
                locator = page.locator(f'[data-message-id="{msg_id}"]').first
                if await locator.count() == 0:
                    self.logger.warning(f"⚠️ المان پست {msg_id} پیدا نشد، رد می‌شود.")
                    continue

                await locator.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)

                path = self.screenshots_dir / f"{self.channel}_post_{msg_id}.png"
                await page.screenshot(path=path, full_page=False)
                self.logger.debug(f"📸 اسکرین‌شات ذخیره شد: {path.name}")

                if (idx + 1) % 10 == 0:
                    self.logger.info(f"   {idx+1}/{len(items)} اسکرین‌شات گرفته شد.")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در اسکرین‌شات پست {msg_id}: {e}")
                continue

        self.logger.info(f"✅ اسکرین‌شات‌ها تمام شد. مجموع: {len(items)}")

    # ═══════════════════ اسکرین‌شات ساده ═══════════════════
    async def _save_screenshot(self, page, name: str):
        try:
            path = self.screenshots_dir / f"{name}.png"
            await page.screenshot(path=path, full_page=True)
            self.logger.debug(f"📸 اسکرین‌شات ذخیره شد: {path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات: {e}")

    # ═══════════════════ اسکرین‌شات دیباگ ═══════════════════
    async def _take_screenshot(self, page, name: str):
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            path = self.base_dir / f"debug_{self.channel}_{name}.png"
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
