#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import random
from pathlib import Path
from typing import List, Dict

from config_loader import Config
from playwright_downloader import PlaywrightDownloader
from output_generator import OutputGenerator

# ═══════════════════ Constants ═══════════════════
MAX_SCROLL_ATTEMPTS = 8
SCROLL_UP = -1200
HOME_URL = "https://web.telegram.org/a/"
OVERALL_TIMEOUT = 35 * 60

# ═══════════════════ Human-like sleep ═══════════════════
async def human_sleep(base: float, jitter: float = 0.4):
    """خواب با زمان تصادفی حول مقدار base (base ± jitter) برای شبیه‌سازی رفتار انسانی"""
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class TelegramChannelScraper:

    def __init__(self, config: Config):
        self.config = config
        self.channel = config.channel.lstrip('@')
        self.channel_name = getattr(config, 'channel_name', '') or ''
        self.start_link = getattr(config, 'start_link', None)
        self.target_msg_id = None
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

    async def run(self):
        try:
            await asyncio.wait_for(self._run_impl(), timeout=OVERALL_TIMEOUT)
        except asyncio.TimeoutError:
            self.logger.error("⏰ اسکریپت به دلیل محدودیت زمانی کلی متوقف شد.")
        except Exception as e:
            self.logger.critical(f"❌ خطای مرگبار در اجرای اصلی: {e}", exc_info=True)

    async def _run_impl(self):
        if self.start_link:
            self.logger.info(f"🚀 شروع اسکریپر با لینک: {self.start_link} (limit={self.limit})")
        else:
            self.logger.info(f"🚀 شروع اسکریپر مستقل برای @{self.channel} (limit={self.limit})")

        items, context, page = await self._fetch_posts_from_telegram()
        if not items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            if context:
                await context.close()
            return
        self.logger.info(f"📥 {len(items)} پست استخراج شد (جدیدترین‌ها).")

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

        try:
            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            self.logger.error(f"❌ صفحه اصلی باز نشد: {e}")
            await context.close()
            return [], None, None

        if self.start_link:
            entered = await self._navigate_to_start_link(page)
        else:
            entered = await self._search_and_enter_channel(page)

        if not entered:
            await context.close()
            return [], None, None
        await self._save_screenshot(page, "initial")

        if not self.start_link:
            self.logger.info("⬇️ تلاش برای پرش به جدیدترین پست‌ها...")
            clicked = False
            scroll_button_selectors = [
                'button[title="Go to bottom"]',
                'div[class*="scroll-to-bottom"]',
                'div[class*="ScrollButton"]',
                '[aria-label="Scroll to bottom"]',
                'button:has(svg[class*="arrow-down"])',
            ]
            for sel in scroll_button_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0:
                        await btn.click(timeout=5000)
                        self.logger.info("   ✅ روی دکمهٔ فلش کلیک شد. منتظر بارگذاری جدیدترین پست‌ها...")
                        clicked = True
                        await human_sleep(3.5, 0.4)
                        break
                except Exception:
                    continue
            if not clicked:
                self.logger.info("   ℹ️ دکمهٔ پرش به پایین پیدا نشد یا کلیک نشد. ادامه با وضعیت فعلی صفحه.")
        else:
            self.logger.info("ℹ️ در حالت start_link، پرش به پایین انجام نمی‌شود (از همان پیام شروع می‌شود).")

        items = []
        seen_ids = set()
        scroll_attempts = 0

        if self.start_link and self.target_msg_id:
            self.logger.info(f"🎯 پیدا کردن پیام هدف با شناسه {self.target_msg_id} و بردن به بالای صفحه...")
            try:
                target_locator = page.locator(f'[data-message-id="{self.target_msg_id}"]').first
                if await target_locator.count() > 0:
                    await target_locator.scroll_into_view_if_needed()
                    await page.evaluate("window.scrollBy(0, -150)")
                    await human_sleep(1, 0.3)
                    self.logger.info("✅ پیام هدف به بالای صفحه منتقل شد.")
                else:
                    self.logger.warning(f"⚠️ پیام هدف با شناسه {self.target_msg_id} پیدا نشد.")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در انتقال پیام هدف به بالای صفحه: {e}")

        while len(items) < self.limit and scroll_attempts < MAX_SCROLL_ATTEMPTS:
            try:
                messages = await page.locator('div[data-message-id]').all()
                if self.start_link:
                    msg_iter = messages
                else:
                    msg_iter = reversed(messages)

                for msg in msg_iter:
                    try:
                        msg_id = await msg.get_attribute('data-message-id')
                        if not msg_id or msg_id in seen_ids:
                            continue

                        await msg.scroll_into_view_if_needed()
                        await msg.wait_for(state="visible", timeout=5000)

                        text = (await msg.inner_text()).strip()[:1000]
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

                        if len(items) >= self.limit:
                            break
                    except Exception:
                        continue
            except Exception as e:
                self.logger.error(f"❌ خطا در استخراج پست‌ها: {e}")

            if len(items) >= self.limit:
                break

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

        if items:
            first_id = items[0]['id']
            try:
                await page.locator(f'[data-message-id="{first_id}"]').scroll_into_view_if_needed()
                await human_sleep(1, 0.3)
            except Exception:
                pass

        return items, context, page

    async def _search_and_enter_channel(self, page) -> bool:
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

        return await self._click_search_result(page, search_term)

    async def _navigate_to_start_link(self, page) -> bool:
        self.logger.info(f"🔗 تلاش برای رفتن به لینک: {self.start_link}")

        try:
            parts = self.start_link.rstrip('/').split('/')
            if parts and parts[-1].isdigit():
                self.target_msg_id = parts[-1]
                self.logger.info(f"🎯 شناسه پیام هدف: {self.target_msg_id}")
            else:
                self.logger.warning("⚠️ نمی‌توان شناسه پیام را از لینک استخراج کرد.")
                self.target_msg_id = None
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در استخراج شناسه پیام: {e}")
            self.target_msg_id = None

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

        await search_input.click()
        await human_sleep(0.3, 0.2)
        await search_input.fill('')
        await human_sleep(0.2, 0.1)
        await search_input.type(self.start_link, delay=random.randint(80, 150))
        self.logger.info(f"🔍 لینک تایپ شد: {self.start_link}")

        await self._take_screenshot(page, "search_link_filled")
        await human_sleep(1.5, 0.3)

        await search_input.press("Enter")
        self.logger.info("⏳ منتظر نتایج جستجو...")

        await human_sleep(5, 0.5)

        await self._take_screenshot(page, "search_results_loaded")

        clicked_result = False
        result_selectors = [
            'div[data-message-id]',
            'div[class*="search-result"] a',
            'div[class*="message"] a',
            'div[role="button"][class*="item"]',
            'div.chatlist-item',
            'a[data-peer-id]',
        ]

        for sel in result_selectors:
            try:
                await page.wait_for_selector(sel, timeout=5000)
                first_result = page.locator(sel).first
                if await first_result.count() > 0:
                    await first_result.scroll_into_view_if_needed()

                    try:
                        await page.evaluate('''(element) => {
                            element.style.outline = '3px solid red';
                            element.style.outlineOffset = '2px';
                            element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        }''', await first_result.element_handle())
                        await human_sleep(1, 0.3)
                        await self._take_screenshot(page, "before_click_highlighted")
                    except Exception as e:
                        self.logger.debug(f"خطا در هایلایت کردن: {e}")

                    await first_result.click(timeout=5000, force=True)
                    self.logger.info(f"✅ روی اولین نتیجه با سلکتور '{sel}' کلیک شد.")
                    clicked_result = True
                    break
            except Exception as e:
                self.logger.debug(f"سلکتور {sel} ناموفق: {e}")
                continue

        if not clicked_result:
            self.logger.info("🔄 تلاش کلیک با JavaScript روی اولین پیام...")
            try:
                await page.evaluate('''() => {
                    const firstMsg = document.querySelector('[data-message-id]');
                    if (firstMsg) {
                        firstMsg.style.outline = '3px solid red';
                        firstMsg.style.outlineOffset = '2px';
                        firstMsg.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        setTimeout(() => {
                            firstMsg.click();
                        }, 500);
                    }
                }''')
                await human_sleep(2, 0.3)
                await self._take_screenshot(page, "after_js_click")
                self.logger.info("✅ کلیک با JavaScript انجام شد.")
                clicked_result = True
            except Exception as e:
                self.logger.error(f"❌ کلیک با JavaScript شکست خورد: {e}")

        if not clicked_result:
            self.logger.error("❌ نتوانستیم روی هیچ نتیجه‌ای کلیک کنیم.")
            await self._take_screenshot(page, "click_result_failed")
            return False

        self.logger.info("⏳ منتظر بارگذاری صفحه پیام...")
        await human_sleep(5, 0.5)

        if await page.locator('div[data-message-id]').count() > 0:
            self.logger.info("✅ صفحه پیام‌ها با موفقیت بارگذاری شد.")
            await self._take_screenshot(page, "messages_page_loaded")
            return True
        else:
            await human_sleep(5, 0.5)
            if await page.locator('div[data-message-id]').count() > 0:
                self.logger.info("✅ صفحه پیام‌ها با موفقیت بارگذاری شد (پس از انتظار مجدد).")
                await self._take_screenshot(page, "messages_page_loaded_retry")
                return True
            else:
                self.logger.error("❌ پس از کلیک، پیام‌ها پیدا نشدند.")
                await self._take_screenshot(page, "no_messages_after_click")
                return False

    async def _check_text_on_page(self, page, term: str) -> bool:
        try:
            return await page.evaluate(f'''(t) => {{
                const bodyText = document.body.innerText || '';
                return bodyText.toLowerCase().includes(t.toLowerCase());
            }}''', term)
        except Exception:
            return False

    async def _click_search_result(self, page, search_term: str) -> bool:
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
