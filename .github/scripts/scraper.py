#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import random
import json
from pathlib import Path
from typing import List, Dict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

from config_loader import Config
from playwright_downloader import PlaywrightDownloader
from output_generator import OutputGenerator

# ═══════════════════ Constants ═══════════════════
SCROLL_UP = -1200
HOME_URL = "https://web.telegram.org/a/"
OVERALL_TIMEOUT = 35 * 60
IRAN_TZ = ZoneInfo("Asia/Tehran")

# ═══════════════════ Human-like sleep ═══════════════════
async def human_sleep(base: float, jitter: float = 0.4):
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class TelegramChannelScraper:

    def __init__(self, config: Config):
        self.config = config
        self.channel = config.channel.lstrip('@')
        self.channel_name = getattr(config, 'channel_name', '') or ''
        self.limit = config.limit
        self.max_media_bytes = config.max_media_mb * 1024 * 1024
        self.base_dir = Path(config.output_dir) / "telegram_downloads" / self.channel
        self.media_dir = self.base_dir / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir = Path(config.profile_dir)
        self.delay_between_posts = config.delay_between_posts
        self.resume = getattr(config, 'resume', True)
        self.start_from = getattr(config, 'start_from', '')
        self.target_url = getattr(config, 'target_url', '').strip()
        self.max_scroll_attempts = getattr(config, 'max_scroll_attempts', 60)
        self.verbose = getattr(config, 'verbose', False)

        self.screenshots_dir = self.base_dir / "post_screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("TelegramScraper")
        if self.verbose:
            self.logger.setLevel(logging.DEBUG)
        else:
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
        self.logger.info(f"🔢 حداکثر تلاش اسکرول: {self.max_scroll_attempts}")
        if self.verbose:
            self.logger.info("🔊 حالت Verbose فعال است – جزئیات بررسی هر پست نمایش داده می‌شود.")

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

        items, context, page = await self._fetch_posts_from_telegram()
        if not items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            if context:
                await context.close()
            return
        self.logger.info(f"📥 {len(items)} پست استخراج شد (جدیدترین‌ها).")

        await self._update_state_file(items)

        media_map, downloaded = await self._download_media(items, page, context)
        self.logger.info(f"🖼️ {downloaded} فایل رسانه دانلود شد.")
        self.logger.info(f"📊 media_map برای {len(media_map)} پست پر شد.")

        gen = OutputGenerator(self.base_dir, self.channel, items, media_map)
        gen.generate_json()
        gen.generate_csv()
        gen.generate_html()
        gen.create_zip()

        if context:
            await context.close()

        self.logger.info("✅ پایان موفقیت‌آمیز.")

    # ═══════════════════ استخراج پست‌ها (ورود معمولی یا جستجوی مستقیم لینک) ═══════════════════
    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], any, any]:
        from playwright.async_api import async_playwright

        p = await async_playwright().start()
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1366, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # ═══════════════ تعیین نقطهٔ شروع ═══════════════
        start_id = None
        include_start = False

        # ۱. لینک مستقیم داده شده ← جستجوی لینک و ورود مستقیم
        if self.target_url:
            parsed = urlparse(self.target_url)
            path_parts = parsed.path.strip('/').split('/')
            if len(path_parts) < 2 or path_parts[-2] != self.channel:
                self.logger.error(f"❌ لینک وارد شده معتبر نیست یا مربوط به کانال @{self.channel} نمی‌باشد.")
                await context.close()
                return [], None, None
            start_id = path_parts[-1]
            include_start = True
            self.logger.info(f"🎯 جستجوی مستقیم لینک و ورود به پست {start_id}")

            # ورود به صفحهٔ اصلی و جستجوی لینک
            try:
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                self.logger.error(f"❌ صفحه اصلی باز نشد: {e}")
                await context.close()
                return [], None, None

            # پیدا کردن نوار جستجو
            search_input = await self._find_search_input(page)
            if not search_input:
                self.logger.error("❌ نوار جستجو پیدا نشد.")
                await context.close()
                return [], None, None

            # تایپ لینک در نوار جستجو
            await search_input.click()
            await human_sleep(0.3, 0.2)
            await search_input.fill('')
            await human_sleep(0.2, 0.1)
            await search_input.type(self.target_url, delay=random.randint(80, 150))
            self.logger.info(f"🔍 در حال جستجوی لینک: {self.target_url}")
            await self._take_screenshot(page, "search_link_input")
            await human_sleep(1.5, 0.3)
            await search_input.press("Enter")

            # انتظار برای ظاهر شدن نتیجه و کلیک روی آن (با اسکرین‌شات ضربدر)
            self.logger.info("⏳ منتظر نتیجهٔ جستجوی لینک...")
            clicked = await self._click_link_search_result(page, self.channel, start_id)
            if not clicked:
                self.logger.error("❌ کلیک روی نتیجهٔ لینک موفق نبود.")
                await context.close()
                return [], None, None

            # حالا کانال با پیام مورد نظر باز شده – صبر برای لود کامل
            await self._wait_for_channel_loaded(page, min_messages=5)
            await self._save_screenshot(page, "after_link_enter")

        # ۲. شناسهٔ دستی یا ادامهٔ خودکار ← روش معمولی
        else:
            if self.start_from:
                start_id = str(self.start_from)
                include_start = True
                self.logger.info(f"🎯 شروع دستی از پست {start_id}")
            elif self.resume:
                oldest = self._get_oldest_state_id()
                if oldest:
                    start_id = oldest
                    include_start = False
                    self.logger.info(f"🔄 ادامه خودکار از بعد از پست {start_id}")
                else:
                    self.logger.info("ℹ️ فایل State خالی است. شروع از جدیدترین‌ها.")
            else:
                self.logger.info("🆕 شروع تازه از جدیدترین پست‌ها.")

            # ورود معمولی به کانال
            try:
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                self.logger.error(f"❌ صفحه اصلی باز نشد: {e}")
                await context.close()
                return [], None, None

            entered = await self._search_and_enter_channel(page)
            if not entered:
                await context.close()
                return [], None, None

            await self._save_screenshot(page, "after_enter")
            await self._wait_for_channel_loaded(page, min_messages=10)
            await self._go_to_bottom(page)

        # ═══════════════ جمع‌آوری پست‌ها (فیلتر با start_id) ═══════════════
        items = []
        seen_ids = set()
        scroll_attempts = 0

        while len(items) < self.limit and scroll_attempts < self.max_scroll_attempts:
            try:
                messages = await page.locator('div[data-message-id]').all()
                for msg in reversed(messages):
                    try:
                        msg_id = await msg.get_attribute('data-message-id')
                        if not msg_id or msg_id in seen_ids:
                            continue

                        # فیلتر محدودهٔ شروع
                        if start_id:
                            id_int = int(msg_id)
                            start_int = int(start_id)
                            if include_start:
                                if id_int > start_int:      # فقط خود start_id و قدیمی‌تر
                                    continue
                            else:
                                if id_int >= start_int:     # فقط قدیمی‌تر
                                    continue

                        await msg.scroll_into_view_if_needed()
                        await msg.wait_for(state="visible", timeout=5000)

                        text = (await msg.inner_text()).strip()[:1000]
                        date_el = msg.locator('time, .message-date, .date, span[class*="date"]').first
                        date = ""
                        datetime_attr = None
                        if await date_el.count() > 0:
                            date = await date_el.inner_text() or ""
                            datetime_attr = await date_el.get_attribute('datetime')
                            if not date and datetime_attr:
                                date = datetime_attr

                        items.append({
                            'id': msg_id,
                            'text': text,
                            'date': date,
                            'url': f"https://t.me/{self.channel}/{msg_id}",
                            'datetime_attr': datetime_attr
                        })
                        seen_ids.add(msg_id)

                        if len(items) >= self.limit:
                            break
                    except Exception:
                        continue
            except Exception as e:
                self.logger.error(f"❌ خطا در استخراج پست‌ها: {e}")

            if len(items) >= self.limit:
                break

            # اسکرول استاندارد به سمت بالا
            old_height = await page.evaluate("document.documentElement.scrollHeight")
            await page.evaluate(f"window.scrollBy(0, {SCROLL_UP})")
            await human_sleep(2.5, 0.5)
            new_height = await page.evaluate("document.documentElement.scrollHeight")

            if new_height == old_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0

        items = items[:self.limit]
        self.logger.info(f"📊 {len(items)} پست جمع‌آوری شد.")

        await self._save_screenshot(page, "final")
        await self._capture_post_screenshots(page, items)

        # در شروع تازه، به اولین پست اسکرول کن
        if items and not start_id:
            first_id = items[0]['id']
            try:
                await page.locator(f'[data-message-id="{first_id}"]').scroll_into_view_if_needed()
                await human_sleep(1, 0.3)
            except Exception:
                pass

        return items, context, page

    # ═══════════════ متدهای کمکی ═══════════════

    async def _find_search_input(self, page):
        for sel in [
            'input[placeholder*="Search"]',
            'input[role="textbox"]',
            '[data-testid="search-input"]'
        ]:
            try:
                el = await page.wait_for_selector(sel, timeout=10000)
                if el:
                    return el
            except Exception:
                continue
        return None

    async def _screenshot_with_cross(self, page, locator, name: str):
        """اسکرین‌شات از صفحه با یک ضربدر قرمز روی المان مشخص‌شده"""
        try:
            box = await locator.bounding_box()
            if not box:
                return
            x = box['x'] + box['width'] / 2
            y = box['y'] + box['height'] / 2
            # کشیدن ضربدر با دو div
            await page.evaluate('''({x, y}) => {
                const size = 20;
                const color = 'red';
                const container = document.createElement('div');
                container.id = '__debug_cross';
                container.style.position = 'fixed';
                container.style.left = (x - size/2) + 'px';
                container.style.top = (y - size/2) + 'px';
                container.style.width = size + 'px';
                container.style.height = size + 'px';
                container.style.pointerEvents = 'none';
                container.style.zIndex = '99999';
                const line1 = document.createElement('div');
                line1.style.position = 'absolute';
                line1.style.width = size + 'px';
                line1.style.height = '2px';
                line1.style.backgroundColor = color;
                line1.style.top = (size/2 - 1) + 'px';
                line1.style.left = '0';
                line1.style.transform = 'rotate(45deg)';
                const line2 = line1.cloneNode();
                line2.style.transform = 'rotate(-45deg)';
                container.appendChild(line1);
                container.appendChild(line2);
                document.body.appendChild(container);
            }''', {'x': x, 'y': y})
            await page.screenshot(path=str(self.base_dir / f"debug_{self.channel}_{name}.png"), full_page=True)
            # حذف ضربدر
            await page.evaluate('() => { const el = document.getElementById("__debug_cross"); if(el) el.remove(); }')
            self.logger.info(f"📸 اسکرین‌شات ضربدر ذخیره شد: debug_{self.channel}_{name}.png")
        except Exception as e:
            self.logger.warning(f"⚠️ اسکرین‌شات ضربدر ممکن نشد: {e}")

    async def _click_link_search_result(self, page, channel, msg_id) -> bool:
        """بعد از جستجوی لینک، روی نتیجهٔ پیام کلیک می‌کند (با اسکرین‌شات ضربدر)."""
        selectors = [
            'div.search-result',
            'div[class*="chatlist"] div[class*="item"]',
            'div[class*="ListItem"]',
            f'[data-message-id="{msg_id}"]',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=5000):
                    # اسکرین‌شات با ضربدر قبل از کلیک
                    await self._screenshot_with_cross(page, loc, "search_result_before_click")
                    await loc.click(timeout=8000, force=True)
                    await human_sleep(4, 0.5)
                    if await page.locator('div[data-message-id]').count() > 0:
                        self.logger.info("✅ نتیجهٔ لینک کلیک شد و کانال باز شد.")
                        await self._take_screenshot(page, "after_link_click")
                        return True
            except Exception:
                continue

        # روش JavaScript
        self.logger.info("🔄 تلاش کلیک با JavaScript روی نتیجهٔ لینک...")
        try:
            await page.evaluate(f'''(channel, msg_id) => {{
                const url = "https://t.me/" + channel + "/" + msg_id;
                const links = Array.from(document.querySelectorAll('a[href*="' + url + '"]'));
                if (links.length) {{
                    links[0].click();
                    return;
                }}
                const item = document.querySelector('div.chatlist-item, div.search-result, div[class*="ListItem"]');
                if (item) item.click();
            }}''', channel, msg_id)
            await human_sleep(5, 0.4)
            if await page.locator('div[data-message-id]').count() > 0:
                self.logger.info("✅ با JavaScript وارد پیام شدیم.")
                await self._take_screenshot(page, "after_link_click_js")
                return True
        except Exception as e:
            self.logger.debug(f"JavaScript click failed: {e}")

        return False

    async def _wait_for_channel_loaded(self, page, min_messages: int = 10):
        self.logger.info("⏳ در حال منتظر ماندن برای لود کامل کانال...")
        try:
            await page.wait_for_selector('div[data-message-id]', timeout=25000)
            for attempt in range(12):
                msg_count = await page.locator('div[data-message-id]').count()
                self.logger.info(f"   تلاش {attempt+1}/12 - تعداد پیام‌های دیده شده: {msg_count}")
                if msg_count >= min_messages:
                    await human_sleep(2.5, 0.6)
                    break
                await page.evaluate("window.scrollBy(0, -700)")
                await human_sleep(1.8, 0.7)
            self.logger.info("✅ کانال به نظر کافی لود شده.")
        except Exception as e:
            self.logger.warning(f"⚠️ زمان انتظار لود کانال تمام شد: {e}")
            await human_sleep(4, 0.5)

    async def _go_to_bottom(self, page):
        self.logger.info("⬇️ تلاش برای رفتن به جدیدترین پست‌ها...")
        clicked = False
        selectors = [
            'button[title="Go to bottom"]',
            '[aria-label="Scroll to bottom"]',
            'div[class*="scroll-to-bottom"]',
            'button:has(svg[class*="arrow-down"])'
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await btn.click(timeout=8000)
                    clicked = True
                    self.logger.info("✅ کلیک روی دکمهٔ پایین انجام شد.")
                    break
            except Exception:
                continue
        if clicked:
            await human_sleep(5.0, 0.8)
        else:
            self.logger.info("   ⚠️ دکمهٔ پایین پیدا نشد، ادامه با وضعیت فعلی.")
            await human_sleep(3, 0.6)

    async def _search_and_enter_channel(self, page) -> bool:
        search_input = await self._find_search_input(page)
        if not search_input:
            self.logger.error("❌ نوار جستجو پیدا نشد.")
            return False

        await search_input.click()
        await human_sleep(0.3, 0.2)
        await search_input.fill('')
        await human_sleep(0.2, 0.1)
        await search_input.type(self.channel, delay=random.randint(80, 150))
        self.logger.info(f"🔍 در حال جستجوی: @{self.channel}")
        await self._take_screenshot(page, "search_input_filled")
        await human_sleep(1.5, 0.3)
        await search_input.press("Enter")
        self.logger.info("⏳ منتظر نتایج...")

        search_term = self.channel_name if self.channel_name else self.channel
        found = False

        self.logger.info("   🕐 مرحلهٔ اول انتظار (۱۰ ثانیه)...")
        await human_sleep(10, 0.5)
        if await self._check_text_on_page(page, search_term):
            found = True
            self.logger.info(f"   ✅ عبارت '{search_term}' در مرحلهٔ اول یافت شد.")

        if not found:
            self.logger.info("   🕑 مرحلهٔ دوم انتظار (۱۵ ثانیه)...")
            await human_sleep(15, 0.5)
            if await self._check_text_on_page(page, search_term):
                found = True
                self.logger.info(f"   ✅ عبارت '{search_term}' در مرحلهٔ دوم یافت شد.")

        if not found:
            self.logger.info("   🕒 مرحلهٔ سوم انتظار (۲۰ ثانیه)...")
            await human_sleep(20, 0.5)
            if await self._check_text_on_page(page, search_term):
                found = True
                self.logger.info(f"   ✅ عبارت '{search_term}' در مرحلهٔ سوم یافت شد.")

        if not found:
            self.logger.info("   📑 کلیک روی تب Channels (در صورت وجود)...")
            try:
                channels_tab = page.get_by_role("tab", name="Channels").first
                if await channels_tab.count() > 0:
                    await channels_tab.click()
                    await human_sleep(4, 0.4)
                    self.logger.info("   📑 تب Channels انتخاب شد.")
            except Exception:
                pass

            for attempt in range(15):
                await human_sleep(2, 0.3)
                if await self._check_text_on_page(page, search_term):
                    found = True
                    self.logger.info(f"   ✅ عبارت '{search_term}' بعد از کلیک Channels یافت شد (تلاش {attempt+1}).")
                    break

        if not found:
            self.logger.error(f"❌ نتایج جستجو برای '{search_term}' پیدا نشد (حتی پس از ۴۵+ ثانیه).")
            await self._take_screenshot(page, "search_failed")
            return False

        self.logger.info("✅ نتایج جستجو قطعاً ظاهر شدند.")
        await self._take_screenshot(page, f"search_results_{self.channel}")
        await human_sleep(2, 0.3)

        return await self._click_channel_result(page, search_term)

    async def _check_text_on_page(self, page, term: str) -> bool:
        try:
            return await page.evaluate(f'''(t) => {{
                const bodyText = document.body.innerText || '';
                return bodyText.toLowerCase().includes(t.toLowerCase());
            }}''', term)
        except Exception:
            return False

    async def _click_channel_result(self, page, search_term: str) -> bool:
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
                await loc.click(timeout=8000, force=True)
                await human_sleep(5, 0.4)
                if await page.locator('div.message, div[data-message-id]').count() > 0:
                    self.logger.info("✅ کانال با موفقیت باز شد (سلکتور %s).", sel)
                    return True
            except Exception as e:
                self.logger.debug("سلکتور %s ناموفق: %s", sel, e)

        self.logger.info("🔄 تلاش کلیک با JavaScript روی عبارت جستجو...")
        try:
            await page.evaluate(f'''(term) => {{
                const els = Array.from(document.querySelectorAll('h3, .fullName, [dir="auto"], div[class*="name"], span[class*="peer-title"]'));
                const target = els.find(el => el.textContent.trim().toLowerCase() === term.toLowerCase());
                if (target) {{
                    target.closest('div[role="button"], div.chatlist-item, a')?.click();
                }}
            }}''', search_term)
            await human_sleep(5, 0.4)
            if await page.locator('div.message, div[data-message-id]').count() > 0:
                self.logger.info("✅ با JavaScript (عبارت جستجو) وارد شدیم.")
                return True
        except Exception as e:
            self.logger.debug("JavaScript name click: %s", e)

        self.logger.info("🔄 تلاش کلیک با JavaScript روی اولین نتیجه...")
        try:
            await page.evaluate('''() => {
                const item = document.querySelector('div.chatlist-item, div[role="button"], div.search-result, a[data-peer-id]');
                if (item) item.click();
            }''')
            await human_sleep(5, 0.4)
            if await page.locator('div.message, div[data-message-id]').count() > 0:
                self.logger.info("✅ با JavaScript (اولین نتیجه) وارد شدیم.")
                return True
        except Exception as e:
            self.logger.debug("JavaScript generic click: %s", e)

        self.logger.error("❌ تمام روش‌های کلیک شکست خورد.")
        await self._take_screenshot(page, "click_failed")
        return False

    # ═══════════════ بقیهٔ متدها (بدون تغییر) ═══════════════
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
                await human_sleep(0.5, 0.2)

                path = self.screenshots_dir / f"{self.channel}_post_{msg_id}.png"
                await page.screenshot(path=path, full_page=False)
                self.logger.debug(f"📸 اسکرین‌شات ذخیره شد: {path.name}")

                if (idx + 1) % 10 == 0:
                    self.logger.info(f"   {idx+1}/{len(items)} اسکرین‌شات گرفته شد.")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در اسکرین‌شات پست {msg_id}: {e}")
                continue
        self.logger.info(f"✅ اسکرین‌شات‌ها تمام شد. مجموع: {len(items)}")

    async def _save_screenshot(self, page, name: str):
        try:
            path = self.screenshots_dir / f"{name}.png"
            await page.screenshot(path=path, full_page=True)
            self.logger.debug(f"📸 اسکرین‌شات ذخیره شد: {path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات: {e}")

    async def _take_screenshot(self, page, name: str):
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            path = self.base_dir / f"debug_{self.channel}_{name}.png"
            await page.screenshot(path=path, full_page=True)
            self.logger.info(f"📸 اسکرین‌شات ذخیره شد: {path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ ذخیره اسکرین‌شات شکست: {e}")

    async def _download_media(self, items: List[Dict], page, context) -> tuple[dict, int]:
        post_ids = [str(item['id']) for item in items]
        media_map = {}
        downloaded = 0
        if post_ids:
            downloader = PlaywrightDownloader(
                self.profile_dir, self.media_dir, self.max_media_bytes,
                self.delay_between_posts
            )
            await downloader.download_all(page, context, post_ids, media_map)
            for files in media_map.values():
                downloaded += len(files)
        return media_map, downloaded

    def _get_oldest_state_id(self) -> str | None:
        file_path = Path("State") / f"@{self.channel}.jsonl"
        if not file_path.exists():
            return None
        ids = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    ids.append(int(record['id']))
                except Exception:
                    continue
        return str(min(ids)) if ids else None

    async def _update_state_file(self, items: List[Dict]):
        state_dir = Path("State")
        state_dir.mkdir(parents=True, exist_ok=True)

        file_path = state_dir / f"@{self.channel}.jsonl"
        self.logger.info(f"📌 در حال به‌روزرسانی State: {file_path} (تعداد آیتم‌ها: {len(items)})")

        existing_ids = set()
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        existing_ids.add(record['id'])
                    except Exception:
                        continue
            self.logger.info(f"   📋 {len(existing_ids)} شناسهٔ موجود در State یافت شد.")

        new_records = []
        for item in items:
            if item['id'] in existing_ids:
                continue

            caption = item['text'][:200].strip()
            if len(item['text']) > 200:
                last_space = caption.rfind(' ')
                if last_space > 0:
                    caption = caption[:last_space]

            date_iran = item.get('date', '')
            raw_dt = item.get('datetime_attr')
            if raw_dt:
                try:
                    dt = datetime.fromisoformat(raw_dt.replace('Z', '+00:00'))
                    dt_iran = dt.astimezone(IRAN_TZ)
                    date_iran = dt_iran.strftime('%Y/%m/%d %H:%M')
                except Exception:
                    pass

            record = {
                'id': item['id'],
                'url': item['url'],
                'date_iran': date_iran,
                'caption': caption
            }
            new_records.append(record)

        if new_records:
            with open(file_path, 'a', encoding='utf-8') as f:
                for record in new_records:
                    f.write(json.dumps(record, ensure_ascii=False) + '\n')
            self.logger.info(f"📝 {len(new_records)} پست جدید به State اضافه شد: {file_path}")
        else:
            self.logger.info("ℹ️ هیچ پست جدیدی برای State وجود نداشت (همه تکراری بودند).")
