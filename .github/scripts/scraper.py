#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import random
import re
import json
from pathlib import Path
from typing import List, Dict

from config_loader import Config
from playwright_downloader import PlaywrightDownloader
from output_generator import OutputGenerator

# ═══════════════════ Constants ═══════════════════
MAX_SCROLL_ATTEMPTS = 8
SCROLL_UP = -1200
HOME_URL = "https://web.telegram.org/a/"
OVERALL_TIMEOUT = 35 * 60  # fallback
RESUME_FILE = "resume_state.json"

# ═══════════════════ Human-like sleep ═══════════════════
async def human_sleep(base: float, jitter: float = 0.4):
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

        self.debug_screenshots_dir = self.base_dir / "debug_screenshots"
        self.debug_mode = getattr(config, 'debug_mode', False)

        # ═══════════════ Resume State ═══════════════════
        self.resume_file = self.base_dir / RESUME_FILE
        self.resume_data = self._load_resume_state()

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
        self.logger.info(f"🐞 حالت دیباگ: {'فعال' if self.debug_mode else 'غیرفعال'}")

    # ═══════════════════ Resume State Methods ═══════════════════
    def _load_resume_state(self) -> dict:
        if self.resume_file.exists():
            try:
                with open(self.resume_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.logger.info(f"📂 وضعیت قبلی بارگذاری شد: آخرین msg_id={data.get('last_msg_id')}, تعداد={data.get('count', 0)}")
                return data
            except Exception:
                return {}
        return {}

    def _save_resume_state(self, last_msg_id: str, count: int):
        try:
            with open(self.resume_file, 'w', encoding='utf-8') as f:
                json.dump({'last_msg_id': last_msg_id, 'count': count}, f)
        except Exception as e:
            self.logger.warning(f"⚠️ ذخیره وضعیت resume ناموفق: {e}")

    def _clear_resume_state(self):
        if self.resume_file.exists():
            self.resume_file.unlink()

    # ═══════════════════ متد اصلی با Timeout انعطاف‌پذیر ═══════════════════
    async def run(self):
        timeout = getattr(self.config, 'timeout_seconds', OVERALL_TIMEOUT)
        try:
            await asyncio.wait_for(self._run_impl(), timeout=timeout)
        except asyncio.TimeoutError:
            self.logger.error(f"⏰ اسکریپت به دلیل محدودیت زمانی {timeout} ثانیه متوقف شد.")
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

        gen = OutputGenerator(
            self.base_dir,
            self.channel,
            items,
            media_map,
            debug_mode=self.debug_mode
        )
        gen.run_all()

        if context:
            await context.close()

        self._clear_resume_state()
        self.logger.info("✅ پایان موفقیت‌آمیز.")

    # ═══════════════════ متد کمکی: پاک‌سازی نام فایل ═══════════════════
    @staticmethod
    def _sanitize_filename(name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    # ═══════════════════ متد واحد برای اسکرین‌شات ═══════════════════
    async def _screenshot(self, page, name: str, full_page: bool = True, element=None):
        try:
            if element is not None:
                if hasattr(element, 'element_handle'):
                    element = await element.element_handle()
                if element:
                    safe_name = self._sanitize_filename(name)
                    path = self.debug_screenshots_dir / f"debug_{self.channel}_{safe_name}.png"
                    await element.screenshot(path=path)
                    self.logger.debug(f"📸 اسکرین‌شات المنت ذخیره شد: {path.name}")
            else:
                safe_name = self._sanitize_filename(name)
                if full_page:
                    path = self.screenshots_dir / f"{safe_name}.png"
                else:
                    path = self.debug_screenshots_dir / f"debug_{self.channel}_{safe_name}.png"
                await page.screenshot(path=path, full_page=full_page)
                self.logger.debug(f"📸 اسکرین‌شات صفحه ذخیره شد: {path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات {name}: {e}")

    async def _save_screenshot(self, page, name: str):
        await self._screenshot(page, name, full_page=True)

    async def _take_screenshot(self, page, name: str):
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
        await self._screenshot(page, name, full_page=True)

    # ═══════════════════ رسم صلیب روی المنت ═══════════════════
    async def _draw_debug_cross(self, page, element_handle):
        try:
            if not element_handle:
                return
            await element_handle.scroll_into_view_if_needed()
            await page.evaluate('''(el) => {
                const rect = el.getBoundingClientRect();
                const cross = document.createElement('div');
                cross.style.position = 'fixed';
                cross.style.left = (rect.left + rect.width/2 - 15) + 'px';
                cross.style.top = (rect.top + rect.height/2 - 15) + 'px';
                cross.style.width = '30px';
                cross.style.height = '30px';
                cross.style.pointerEvents = 'none';
                cross.style.zIndex = '99999';
                cross.style.border = '3px solid red';
                cross.style.background = 'rgba(255,0,0,0.2)';
                cross.innerHTML = '✕';
                cross.style.fontSize = '24px';
                cross.style.color = 'red';
                cross.style.textAlign = 'center';
                cross.style.lineHeight = '30px';
                document.body.appendChild(cross);
                setTimeout(() => cross.remove(), 3000);
            }''', element_handle)
        except Exception as e:
            self.logger.debug(f"خطا در رسم صلیب: {e}")

    # ═══════════════════ استخراج پست‌ها با Resume و استخراج هوشمند متن ═══════════════════
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

        # پرش به پایین فقط در حالت عادی و بدون resume
        if not self.start_link and not self.resume_data.get('last_msg_id'):
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
                        self.logger.info("   ✅ روی دکمه فلش کلیک شد. منتظر بارگذاری جدیدترین پست‌ها...")
                        clicked = True
                        await human_sleep(3.5, 0.4)
                        break
                except Exception:
                    continue
            if not clicked:
                self.logger.info("   ℹ️ دکمه پرش به پایین پیدا نشد. ادامه با وضعیت فعلی.")
        elif self.start_link:
            self.logger.info("ℹ️ در حالت start_link، پرش به پایین انجام نمی‌شود.")
        else:
            self.logger.info(f"ℹ️ حالت Resume: از msg_id={self.resume_data.get('last_msg_id')} ادامه می‌دهیم.")

        # جمع‌آوری پست‌ها
        items = []
        seen_ids = set()
        scroll_attempts = 0

        resume_last_id = self.resume_data.get('last_msg_id') if not self.start_link else None
        start_collecting = False
        extra_scroll_count = 0
        max_extra_scrolls = 4
        collected_count = 0

        # اگر resume داریم، ابتدا به پیام مورد نظر برویم
        if resume_last_id:
            self.logger.info(f"🔄 تلاش برای یافتن پیام resume: {resume_last_id}")
            try:
                target_locator = page.locator(f'[data-message-id="{resume_last_id}"]').first
                if await target_locator.count() > 0:
                    await target_locator.scroll_into_view_if_needed()
                    await page.evaluate("window.scrollBy(0, -150)")
                    await human_sleep(1, 0.3)
                    self.logger.info("✅ پیام resume پیدا شد. جمع‌آوری از این نقطه به بالا شروع می‌شود.")
                    start_collecting = True
                    seen_ids.add(resume_last_id)
                else:
                    self.logger.warning("⚠️ پیام resume پیدا نشد. از جدیدترین پست‌ها شروع می‌کنیم.")
                    start_collecting = True
                    resume_last_id = None
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در یافتن پیام resume: {e}")
                start_collecting = True
                resume_last_id = None

        if self.start_link and self.target_msg_id:
            self.logger.info(f"🎯 پیدا کردن پیام هدف {self.target_msg_id}...")
            try:
                target_locator = page.locator(f'[data-message-id="{self.target_msg_id}"]').first
                if await target_locator.count() > 0:
                    await target_locator.scroll_into_view_if_needed()
                    await page.evaluate("window.scrollBy(0, -150)")
                    await human_sleep(1, 0.3)
                    self.logger.info("✅ پیام هدف به بالای صفحه منتقل شد.")
                else:
                    self.logger.warning(f"⚠️ پیام هدف {self.target_msg_id} پیدا نشد.")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در انتقال پیام هدف: {e}")

        while len(items) < self.limit and scroll_attempts < MAX_SCROLL_ATTEMPTS:
            try:
                messages = await page.locator('div[data-message-id]').all()
                
                if self.start_link or resume_last_id:
                    msg_iter = messages
                else:
                    msg_iter = reversed(messages)

                for msg in msg_iter:
                    try:
                        msg_id = await msg.get_attribute('data-message-id')
                        if not msg_id or msg_id in seen_ids:
                            continue

                        if self.start_link and not start_collecting:
                            if msg_id == self.target_msg_id:
                                start_collecting = True
                                self.logger.info(f"🎯 به پیام هدف رسیدیم (ID: {msg_id})، شروع جمع‌آوری...")
                                seen_ids.add(msg_id)
                            else:
                                continue
                        elif resume_last_id and not start_collecting:
                            pass

                        if not start_collecting:
                            continue

                        # ═══════════════ استخراج هوشمند متن پست (نسخه نهایی بهینه‌شده) ═══════════════
                        text = ""
                        try:
                            # روش ۱: selectorهای خاص (اولویت)
                            content_selectors = [
                                'div.message-content',
                                'div.text-content',
                                'div[class*="message-text"]',
                                'div[class*="text"]',
                                'div[class*="body"]'
                            ]
                            for sel in content_selectors:
                                content = msg.locator(sel).first
                                if await content.count() > 0:
                                    text = (await content.inner_text()).strip()[:1000]
                                    if text and len(text) > 3:  # حداقل طول منطقی
                                        break

                            # روش ۲: fallback به inner_text کل پیام
                            if not text or len(text) < 5:
                                text = (await msg.inner_text()).strip()[:1000]

                            # روش ۳: JavaScript textContent (قوی‌ترین fallback)
                            if not text or len(text) < 5:
                                text = (await msg.evaluate("el => el.textContent || ''")).strip()[:1000]

                            # تمیز کردن نهایی متن (فاصله‌های اضافی)
                            text = re.sub(r'\s+', ' ', text).strip()[:1000]

                        except Exception as e:
                            self.logger.debug(f"خطا در استخراج متن پست {msg_id}: {e}")
                            text = ""

                        # استخراج تاریخ
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
                        collected_count += 1

                        if start_collecting and collected_count % 3 == 0:
                            self._save_resume_state(msg_id, collected_count)

                        if len(items) >= self.limit:
                            break
                    except Exception as e:
                        self.logger.debug(f"خطا در پردازش پیام: {e}")
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

            if not start_collecting:
                extra_scroll_count += 1
                if extra_scroll_count <= max_extra_scrolls:
                    self.logger.info(f"🔄 هنوز به نقطه شروع نرسیدیم، اسکرول اضافی شماره {extra_scroll_count}...")
                    if extra_scroll_count >= 3:
                        await page.evaluate(f"window.scrollBy(0, {SCROLL_UP * 2})")
                        self.logger.warning(f"⚠️ اسکرول قوی‌تر انجام شد (تلاش {extra_scroll_count})")
                    else:
                        await page.evaluate(f"window.scrollBy(0, {SCROLL_UP // 2})")
                    await human_sleep(1.5, 0.3)
                else:
                    self.logger.warning(f"⚠️ پس از {max_extra_scrolls} اسکرول اضافی، نقطه شروع پیدا نشد. ادامه با پست‌های موجود...")
                    start_collecting = True
                    resume_last_id = None

            if len(items) % 5 == 0 and len(items) > 0:
                await human_sleep(1.5, 0.3)

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

    # ═══════════════════ جستجو و ورود به کانال ═══════════════════
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
        await page.keyboard.press("Enter")
        self.logger.info("⏳ منتظر نتایج...")

        search_term = self.channel_name if self.channel_name else self.channel
        found = False

        self.logger.info("🕐 مرحله اول انتظار (۱۰ ثانیه)...")
        await human_sleep(10, 0.5)
        if await self._check_text_on_page(page, search_term):
            found = True
            self.logger.info(f"   ✅ عبارت '{search_term}' در مرحله اول یافت شد.")

        if not found:
            self.logger.info("🕑 مرحله دوم انتظار (۱۵ ثانیه)...")
            await human_sleep(15, 0.5)
            if await self._check_text_on_page(page, search_term):
                found = True
                self.logger.info(f"   ✅ عبارت '{search_term}' در مرحله دوم یافت شد.")

        if not found:
            self.logger.info("🕒 مرحله سوم انتظار (۲۰ ثانیه)...")
            await human_sleep(20, 0.5)
            if await self._check_text_on_page(page, search_term):
                found = True
                self.logger.info(f"   ✅ عبارت '{search_term}' در مرحله سوم یافت شد.")

        if not found:
            self.logger.info("📑 کلیک روی تب Channels (در صورت وجود)...")
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

        self.logger.info("✅ نتایج جستجو ظاهر شدند.")
        await self._take_screenshot(page, f"search_results_{self.channel}")
        await human_sleep(2, 0.3)
        await self._take_screenshot(page, "before_click_final")

        return await self._click_search_result(page, search_term)

    # ═══════════════════ متد جستجو با لینک ═══════════════════
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

        async def perform_search_and_click():
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
            await page.keyboard.press("Enter")
            self.logger.info("⏳ منتظر نتایج جستجو...")
            await human_sleep(5, 0.5)
            await self._take_screenshot(page, "search_results_loaded")

            clicked = False
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
                        handle = await first_result.element_handle()
                        if handle:
                            await self._draw_debug_cross(page, handle)
                        await first_result.click(timeout=5000, force=True)
                        self.logger.info(f"✅ روی اولین نتیجه با سلکتور '{sel}' کلیک شد.")
                        clicked = True
                        break
                except Exception as e:
                    self.logger.debug(f"سلکتور {sel} ناموفق: {e}")
                    continue

            if not clicked:
                self.logger.info("🔄 تلاش کلیک با JavaScript روی اولین پیام...")
                try:
                    await page.evaluate('''() => {
                        const firstMsg = document.querySelector('[data-message-id]');
                        if (firstMsg) {
                            firstMsg.style.outline = '3px solid red';
                            firstMsg.style.outlineOffset = '2px';
                            firstMsg.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            setTimeout(() => { firstMsg.click(); }, 500);
                        }
                    }''')
                    await human_sleep(2, 0.3)
                    await self._take_screenshot(page, "after_js_click")
                    self.logger.info("✅ کلیک با JavaScript انجام شد.")
                    clicked = True
                except Exception as e:
                    self.logger.error(f"❌ کلیک با JavaScript شکست خورد: {e}")

            if not clicked:
                self.logger.error("❌ نتوانستیم روی هیچ نتیجه‌ای کلیک کنیم.")
                await self._take_screenshot(page, "click_result_failed")
                return False

            for attempt in range(3):
                try:
                    await page.wait_for_selector('div[data-message-id]', timeout=15000)
                    self.logger.info("✅ صفحه پیام‌ها با موفقیت بارگذاری شد.")
                    await self._take_screenshot(page, "messages_page_loaded")
                    return True
                except Exception as e:
                    self.logger.warning(f"⚠️ تلاش {attempt+1} برای بارگذاری پیام‌ها ناموفق: {e}")
                    if attempt < 2:
                        await human_sleep(3, 0.5)
            self.logger.error("❌ پس از کلیک، پیام‌ها پیدا نشدند.")
            await self._take_screenshot(page, "no_messages_after_click")
            return False

        for retry in range(2):
            if retry > 0:
                self.logger.info(f"🔄 تلاش مجدد ({retry+1})... بازگشت به صفحه قبل و دوباره جستجو")
                await page.go_back()
                await human_sleep(2, 0.3)
            success = await perform_search_and_click()
            if success:
                return True
            else:
                self.logger.warning(f"❌ تلاش {retry+1} ناموفق بود.")
        return False

    # ═══════════════════ متد کمکی: بررسی وجود عبارت ═══════════════════
    async def _check_text_on_page(self, page, term: str) -> bool:
        try:
            return await page.evaluate(f'''(t) => {{
                const bodyText = document.body.innerText || '';
                return bodyText.toLowerCase().includes(t.toLowerCase());
            }}''', term)
        except Exception:
            return False

    # ═══════════════════ کلیک روی نتیجه جستجو ═══════════════════
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
                await human_sleep(0.5, 0.2)

                safe_channel = self._sanitize_filename(self.channel)
                safe_msg_id = self._sanitize_filename(str(msg_id))
                path = self.screenshots_dir / f"{safe_channel}_post_{safe_msg_id}.png"
                await locator.screenshot(path=path)
                self.logger.debug(f"📸 اسکرین‌شات ذخیره شد: {path.name}")

                if (idx + 1) % 10 == 0:
                    self.logger.info(f"   {idx+1}/{len(items)} اسکرین‌شات گرفته شد.")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در اسکرین‌شات پست {msg_id}: {e}")
                continue

        self.logger.info(f"✅ اسکرین‌شات‌ها تمام شد. مجموع: {len(items)}")

    # ═══════════════════ دانلود رسانه‌ها با quiet_base ═══════════════════
    async def _download_media(self, items: List[Dict], page, context) -> tuple[dict, int]:
        post_ids = [str(item['id']) for item in items]
        media_map = {}

        downloaded = 0
        if post_ids:
            try:
                downloader = PlaywrightDownloader(
                    self.profile_dir,
                    self.media_dir,
                    self.max_media_bytes,
                    self.delay_between_posts,
                    debug_screenshots_dir=self.debug_screenshots_dir,
                    quiet_base=getattr(self.config, 'download_quiet_seconds', 1.0)
                )
                await downloader.download_all(page, context, post_ids, media_map)
            except Exception as e:
                self.logger.error(f"❌ خطا در فرآیند دانلود: {e}")
            finally:
                for files in media_map.values():
                    downloaded += len(files)

        return media_map, downloaded
