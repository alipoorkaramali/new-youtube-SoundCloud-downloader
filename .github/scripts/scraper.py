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
        self.logger.info(f"🔢 حداکثر تلاش اسکرول: {self.max_scroll_attempts}")

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

        # بروزرسانی فایل State (لاگ ماندگار)
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

    # ═══════════════════ استخراج پست‌ها (انسانی + تشخیص لینک هدف) ═══════════════════
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

        # ─── تعیین استراتژی شروع ───
        start_id = None
        include_start = False
        target_url_normalized = None
        target_msg_id_from_url = None

        # اولویت با target_url (لینک کامل)
        if self.target_url:
            parsed = urlparse(self.target_url)
            path_parts = parsed.path.strip('/').split('/')
            if len(path_parts) >= 2 and path_parts[-2] == self.channel:
                target_msg_id_from_url = path_parts[-1]
                target_url_normalized = f"https://t.me/{self.channel}/{target_msg_id_from_url}"
            else:
                self.logger.error(f"❌ لینک وارد شده معتبر نیست یا مربوط به کانال @{self.channel} نمی‌باشد.")
                await context.close()
                return [], None, None
            self.logger.info(f"🎯 جستجوی پست با لینک: {target_url_normalized}")

        if self.start_from and not target_url_normalized:
            start_id = str(self.start_from)
            include_start = True
            self.logger.info(f"🎯 شروع دستی از پست {start_id} (با اسکرول طبیعی)")
        elif not target_url_normalized:
            if self.resume:
                oldest = self._get_oldest_state_id()
                if oldest:
                    start_id = oldest
                    include_start = False
                    self.logger.info(f"🔄 ادامه خودکار از بعد از پست {start_id} (با اسکرول طبیعی)")
                else:
                    self.logger.info("ℹ️ فایل State خالی است. شروع از جدیدترین‌ها.")
            else:
                self.logger.info("🆕 شروع تازه از جدیدترین پست‌ها.")

        # ─── ورود به کانال و بارگذاری کامل ───
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

        # منتظر بارگذاری کامل کانال (حداقل ۱۰ پیام دیده شود)
        await self._wait_for_channel_loaded(page, min_messages=10)

        # رفتن به پایین‌ترین نقطه (جدیدترین‌ها) با صبر بیشتر
        await self._go_to_bottom(page)

        # ─── جمع‌آوری پست‌ها (با تشخیص لینک هدف) ───
        items = []
        seen_ids = set()
        scroll_attempts = 0
        target_found = False

        while len(items) < self.limit and scroll_attempts < self.max_scroll_attempts:
            try:
                messages = await page.locator('div[data-message-id]').all()
                for msg in reversed(messages):
                    try:
                        msg_id = await msg.get_attribute('data-message-id')
                        if not msg_id or msg_id in seen_ids:
                            continue

                        # ساخت لینک پست برای مقایسه
                        post_url = f"https://t.me/{self.channel}/{msg_id}"

                        # اگر به دنبال target_url هستیم و هنوز پیدا نشده
                        if target_url_normalized and not target_found:
                            if post_url == target_url_normalized:
                                target_found = True
                                start_id = msg_id
                                include_start = True
                                self.logger.info(f"✅ پست هدف با لینک {target_url_normalized} پیدا شد (msg_id={msg_id}). شروع جمع‌آوری از این پست.")
                                # خود این پست هم جمع شود
                            else:
                                # هنوز به پست هدف نرسیده‌ایم، اسکرول ادامه دارد
                                continue

                        # اگر start_id مشخص شده (حتی از طریق target_url) فیلتر را اعمال کن
                        if start_id:
                            id_int = int(msg_id)
                            start_int = int(start_id)
                            if include_start:
                                if id_int > start_int:
                                    continue
                            else:
                                if id_int >= start_int:
                                    continue

                        # تضمین visible بودن قبل از استخراج متن
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
                            'url': post_url,
                            'datetime_attr': datetime_attr
                        })
                        seen_ids.add(msg_id)

                        if len(items) >= self.limit:
                            break
                    except Exception:
                        continue

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

            except Exception as e:
                self.logger.error(f"❌ خطا در استخراج پست‌ها: {e}")
                scroll_attempts += 1

        if target_url_normalized and not target_found:
            self.logger.warning(
                f"⚠️ پست با لینک '{target_url_normalized}' بعد از {self.max_scroll_attempts} تلاش اسکرول پیدا نشد."
                " می‌توانید از ورودی 'max_scroll_attempts' برای افزایش تلاش استفاده کنید."
            )

        items = items[:self.limit]
        self.logger.info(f"📊 {len(items)} پست جدیدترین جمع‌آوری شد.")

        await self._save_screenshot(page, "final")
        await self._capture_post_screenshots(page, items)

        if items and not start_id:
            first_id = items[0]['id']
            try:
                await page.locator(f'[data-message-id="{first_id}"]').scroll_into_view_if_needed()
                await human_sleep(1, 0.3)
            except Exception:
                pass

        return items, context, page

    # ═══════════════════ منتظر بارگذاری کامل کانال (جدید) ═══════════════════
    async def _wait_for_channel_loaded(self, page, min_messages: int = 10):
        """منتظر لود شدن واقعی کانال با رفتار انسانی"""
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

    # ═══════════════════ رفتن به پایین (جدید) ═══════════════════
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

    # ═══════════════════ جستجو و ورود به کانال (بدون تغییر) ═══════════════════
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
