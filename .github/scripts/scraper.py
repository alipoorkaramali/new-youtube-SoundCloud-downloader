#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ماژول اصلی اسکرپر تلگرام
------------------------
این ماژول وظیفه استخراج پست‌ها از کانال‌های تلگرام با استفاده از Playwright را بر عهده دارد.
ویژگی‌ها:
- پشتیبانی از شروع با لینک مستقیم به یک پست
- پشتیبانی از حالت Resume (ادامه از آخرین نقطه)
- استخراج هوشمند متن با روش‌های مقاوم در برابر تغییرات ساختار
- ذخیره اسکرین‌شات از پست‌ها
- هماهنگ با debug_scraper.py برای حالت دیباگ
"""

import asyncio
import logging
import random
import re
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

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
    """
    خواب با تاخیر انسانی (با جیتر تصادفی).

    Args:
        base (float): زمان پایه به ثانیه
        jitter (float): ضریب جیتر (0.4 = ±40%)
    """
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class TelegramChannelScraper:
    """
    کلاس اصلی اسکرپر تلگرام.
    """

    def __init__(self, config: Config):
        """
        سازنده کلاس اسکرپر.

        Args:
            config (Config): آبجکت پیکربندی از config.yaml
        """
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
        self.save_screenshots = getattr(config, 'save_screenshots', True)
        
        # ─── تعداد تلاش‌های اسکرول بر اساس وضعیت save_screenshots ───
        if not self.save_screenshots:
            self.max_scroll_attempts = 12
        else:
            self.max_scroll_attempts = MAX_SCROLL_ATTEMPTS

        # ═══════════════ راه‌اندازی لاگر (قبل از هر چیز دیگر) ═══════════════
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

        # ═══════════════ ذخیره جهت اسکرول (بعد از لاگر) ═══════════════
        self.scroll_direction = getattr(config, 'scroll_direction', 'up').lower()
        if self.scroll_direction not in ['up', 'down']:
            self.logger.warning(f"⚠️ مقدار نامعتبر برای scroll_direction: {self.scroll_direction}. استفاده از 'up'.")
            self.scroll_direction = 'up'
        # ═══════════════ لاگ مقدار auto_resume (برای دیباگ) ═══════════════
        #self.logger.info(f"🔁 auto_resume مقدار دریافت شده از config: {self.auto_resume}")

        # ═══════════════ Resume State (بعد از لاگر) ═══════════════
        self.resume_file = self.base_dir / RESUME_FILE
        self.resume = getattr(config, 'resume', False)
        self._resume_data = None
        self._resume_loaded = False
        self._resume_last_link = None

        # بارگذاری وضعیت resume اگر فعال باشد
        if self.resume:
            self._resume_data = self._load_resume_state()
            if self._resume_data:
                last_link = self._resume_data.get('last_post_link')
                last_msg_id = self._resume_data.get('last_msg_id')
                if last_link:
                    self._resume_last_link = last_link
                    self._resume_loaded = True
                    self.logger.info(f"🔄 Resume فعال: last_msg_id={last_msg_id}, total_posts={self._resume_data.get('total_posts', 0)}")
                    self.logger.info(f"🔗 لینک آخرین پست: {last_link}")

                    # ═══════════════ تبدیل Resume به start_link ═══════════════
                    # مقدار start_link را با لینک آخرین پست بازنویسی می‌کنیم
                    self.start_link = last_link
                    self.logger.info(f"🔄 Resume به عنوان start_link تنظیم شد: {self.start_link}")

                    # استخراج target_msg_id برای استفاده در _navigate_to_start_link
                    try:
                        parts = self.start_link.rstrip('/').split('/')
                        if parts and parts[-1].isdigit():
                            self.target_msg_id = parts[-1]
                            self.logger.info(f"🎯 شناسه پیام هدف از resume: {self.target_msg_id}")
                    except Exception as e:
                        self.logger.debug(f"خطا در استخراج target_msg_id از resume: {e}")
                else:
                    self.logger.warning("⚠️ فایل resume موجود است اما 'last_post_link' پیدا نشد.")
                    self.resume = False
            else:
                self.logger.warning("⚠️ فایل resume یافت نشد. اجرا بدون resume.")
                self.resume = False

        self.logger.info(f"📁 دایرکتوری خروجی: {self.base_dir}")
        self.logger.info(f"🐞 حالت دیباگ: {'فعال' if self.debug_mode else 'غیرفعال'}")
        self.logger.info(f"📌 Resume: {'فعال (بارگذاری‌شده)' if self._resume_loaded else 'غیرفعال'}")
        self.logger.info(f"🧭 جهت اسکرول: {self.scroll_direction}")

    # ═══════════════════ Resume State Methods ═══════════════════

    def _load_resume_state(self) -> dict:
        """بارگذاری وضعیت resume از فایل JSON."""
        if self.resume_file.exists():
            try:
                with open(self.resume_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.logger.info(f"📂 وضعیت resume بارگذاری شد: {data.get('last_msg_id')}, total={data.get('total_posts', 0)}")
                return data
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در بارگذاری resume: {e}")
                return {}
        return {}

    def _save_resume_state(self, last_msg_id: str, total_posts: int):
        """ذخیره وضعیت resume در فایل JSON (هماهنگ با debug_scraper)."""
        try:
            last_post_link = f"https://t.me/{self.channel}/{last_msg_id}"
            state = {
                "last_post_link": last_post_link,
                "last_msg_id": last_msg_id,
                "channel": self.channel,
                "total_posts": total_posts,
                "timestamp": asyncio.get_event_loop().time()
            }
            with open(self.resume_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            self.logger.debug(f"💾 Resume state saved: {last_msg_id}, total={total_posts}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره resume: {e}")

    def _clear_resume_state(self):
        """حذف فایل resume (در صورت پایان کامل)."""
        if self.resume_file.exists():
            try:
                self.resume_file.unlink()
                self.logger.debug("🗑️ فایل resume حذف شد.")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در حذف resume: {e}")

    # ═══════════════════ متد اصلی با Timeout انعطاف‌پذیر ═══════════════════

    async def run(self):
        """اجرای اصلی اسکرپر با زمان‌بندی timeout."""
        timeout = getattr(self.config, 'timeout_seconds', OVERALL_TIMEOUT)
        try:
            await asyncio.wait_for(self._run_impl(), timeout=timeout)
        except asyncio.TimeoutError:
            self.logger.error(f"⏰ اسکریپت به دلیل محدودیت زمانی {timeout} ثانیه متوقف شد.")
        except Exception as e:
            self.logger.critical(f"❌ خطای مرگبار در اجرای اصلی: {e}", exc_info=True)

    async def _run_impl(self):
        """پیاده‌سازی اصلی اسکرپر با پشتیبانی از ادامه خودکار تا رسیدن به limit."""
        if self.start_link:
            self.logger.info(f"🚀 شروع اسکریپر با لینک: {self.start_link} (limit={self.limit})")
        else:
            self.logger.info(f"🚀 شروع اسکریپر مستقل برای @{self.channel} (limit={self.limit})")

        all_items = []
        global_seen_ids = set()
        rounds = 0
        # محاسبه تعداد دورهای مورد نیاز بر اساس limit
        max_rounds = max(15, (self.limit // 30) + 2)  # حداقل ۱۵ دور
        self.logger.info(f"🔄 اسکرپر تا رسیدن به {self.limit} پست ادامه می‌دهد...")

        # ─── متغیرهای جمع‌آوری دانلودها در طول دورها ───
        all_media_map = {}
        downloaded_total = 0

        context = None
        page = None

        while len(all_items) < self.limit and rounds < max_rounds:
            rounds += 1
            self.logger.info(f"📌 دور {rounds} از {max_rounds}")
            self.logger.info(f"📊 پست‌های جمع‌آوری‌شده تا اینجا: {len(all_items)}/{self.limit}")

            # اگر دور اول نیست، resume_point را تنظیم کن
            if rounds > 1 and all_items:
                # پیدا کردن قدیمی‌ترین پستی که اسکرین‌شات آن موجود است
                oldest_post = None
                sorted_items = sorted(all_items, key=lambda x: int(x.get('id', 0)))
                for item in sorted_items:
                    msg_id = item['id']
                    safe_channel = self._sanitize_filename(self.channel)
                    safe_msg_id = self._sanitize_filename(str(msg_id))
                    screenshot_path = self.screenshots_dir / f"{safe_channel}_post_{safe_msg_id}.png"
                    if screenshot_path.exists():
                        oldest_post = item
                        break

                if oldest_post is None:
                    # فال‌بک: از قدیمی‌ترین پست استفاده کن
                    oldest_post = min(all_items, key=lambda x: int(x.get('id', 0)))
                    self.logger.warning(f"⚠️ هیچ اسکرین‌شاتی برای پست‌های قدیمی پیدا نشد، از oldest بدون اسکرین‌شات استفاده می‌شود: {oldest_post['id']}")

                resume_link = f"https://t.me/{self.channel}/{oldest_post['id']}"
                self.start_link = resume_link
                self.target_msg_id = oldest_post['id']
                self._resume_loaded = True
                if self._resume_data is None:
                    self._resume_data = {}
                self._resume_data['last_msg_id'] = self.target_msg_id
                self.logger.info(f"🔄 ادامه از پست {self.target_msg_id} (دور {rounds})")

            # محاسبه تعداد پست‌های باقی‌مانده تا limit
            remaining = self.limit - len(all_items)
            if remaining <= 0:
                break

            # اجرای یک دور اسکرپ (مرورگر همیشه باز نگه داشته می‌شود تا دانلود انجام شود)
            if rounds == 1:
                items, context, page = await self._fetch_posts_from_telegram(
                    existing_seen_ids=global_seen_ids,
                    keep_browser_open=True,
                    limit=remaining
                )
            else:
                items, context, page = await self._fetch_posts_from_telegram(
                    existing_seen_ids=global_seen_ids,
                    keep_browser_open=True,
                    existing_context=context,
                    existing_page=page,
                    limit=remaining
                )
            if not items:
                self.logger.info("ℹ️ پست جدیدی در این دور پیدا نشد. پایان.")
                break

            # ─── دانلود پست‌های همین دور ──────────────────────────
            if items:
                self.logger.info(f"📥 دانلود پست‌های دور {rounds} ({len(items)} پست)...")
                media_map_round, downloaded_round = await self._download_media(
                    items, page, context
                )
                # اضافه کردن به نقشه‌ی کلی
                for post_id, files in media_map_round.items():
                    if post_id in all_media_map:
                        all_media_map[post_id].extend(files)
                    else:
                        all_media_map[post_id] = files
                downloaded_total += downloaded_round
                self.logger.info(f"✅ دور {rounds}: {downloaded_round} فایل دانلود شد")

            # اضافه کردن پست‌های جدید به مجموعه‌ی کلی
            new_items_count = 0
            for item in items:
                if item['id'] not in global_seen_ids:
                    global_seen_ids.add(item['id'])
                    all_items.append(item)
                    new_items_count += 1

            self.logger.info(f"📈 {new_items_count} پست جدید در این دور اضافه شد")
            self.logger.info(f"📊 مجموع پست‌ها تا اینجا: {len(all_items)}/{self.limit}")

            # اگر به limit رسیدیم یا دور آخر است، پردازش نهایی را انجام بده
            if len(all_items) >= self.limit or rounds >= max_rounds:
                break

            # اگر به انتهای کانال رسیدیم و هنوز به limit نرسیدیم، ادامه بده
            if hasattr(self, '_is_at_top') and await self._is_at_top(page):
                self.logger.info("📌 به بالای صفحه رسیدیم. شروع دور بعدی...")
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                continue

        # ─── محدود کردن به تعداد مورد نظر ──────────────────────
        if len(all_items) > self.limit:
            final_ids = {item['id'] for item in all_items[:self.limit]}
            all_items = all_items[:self.limit]
            if all_media_map:
                all_media_map = {post_id: files for post_id, files in all_media_map.items() 
                                 if post_id in final_ids}
            self.logger.info(f"📊 تعداد پست‌ها به {self.limit} محدود شد و media_map فیلتر شد.")

        # ─── پردازش نهایی ──────────────────────────────────
        if not all_items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            if context:
                await context.close()
            return

        self.logger.info(f"📥 {len(all_items)} پست استخراج شد (در {rounds} دور).")
        self.logger.info(f"🖼️ مجموع {downloaded_total} فایل رسانه در {rounds} دور دانلود شد.")
        self.logger.info(f"📊 media_map برای {len(all_media_map)} پست پر شد.")

        media_map = all_media_map

        # ذخیره وضعیت نهایی (قدیمی‌ترین پستی که اسکرین‌شات موفق دارد)
        if all_items:
            oldest_item = None
            sorted_items = sorted(all_items, key=lambda x: int(x.get('id', 0)))
            for item in sorted_items:
                msg_id = item['id']
                safe_channel = self._sanitize_filename(self.channel)
                safe_msg_id = self._sanitize_filename(str(msg_id))
                screenshot_path = self.screenshots_dir / f"{safe_channel}_post_{safe_msg_id}.png"
                if screenshot_path.exists():
                    oldest_item = item
                    break
            if oldest_item is None:
                oldest_item = min(all_items, key=lambda x: int(x.get('id', 0)))
                self.logger.warning(f"⚠️ هیچ اسکرین‌شاتی برای پست‌های قدیمی پیدا نشد، از oldest بدون اسکرین‌شات استفاده می‌شود: {oldest_item['id']}")
            self._save_resume_state(oldest_item['id'], len(all_items))

        append_mode = self.resume and self._resume_loaded

        gen = OutputGenerator(
            self.base_dir,
            self.channel,
            all_items,
            media_map,
            debug_mode=self.debug_mode,
            append_mode=append_mode
        )
        gen.run_all()

        if context:
            await context.close()

        if not self.resume:
            self._clear_resume_state()

        self.logger.info("✅ پایان موفقیت‌آمیز.")        
    # ═══════════════════ متد کمکی: پاک‌سازی نام فایل ═══════════════════

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """پاک‌سازی نام فایل با حذف کاراکترهای غیرمجاز."""
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    # ═══════════════════ متد واحد برای اسکرین‌شات ═══════════════════

    async def _screenshot(self, page, name: str, full_page: bool = True, element=None):
        """گرفتن اسکرین‌شات از صفحه یا المنت."""
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
        """ذخیره اسکرین‌شات کامل صفحه (فقط در صورت فعال بودن)."""
        if not self.save_screenshots:
            self.logger.debug(f"⏭️ اسکرین‌شات {name} غیرفعال است.")
            return
        await self._screenshot(page, name, full_page=True)

    async def _take_screenshot(self, page, name: str):
        """ذخیره اسکرین‌شات دیباگ کامل صفحه (فقط در صورت فعال بودن)."""
        if not self.save_screenshots:
            return
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
        await self._screenshot(page, name, full_page=True)

    # ═══════════════════ رسم صلیب روی المنت ═══════════════════

    async def _draw_debug_cross(self, page, element_handle):
        """رسم صلیب قرمز روی المنت برای دیباگ."""
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
            self.logger.debug(f"خطا در رسم صلیب: {e}")   # ← این خط را اضافه کن
    # ═══════════════════ اسکرول هوشمند (از نسخه ۵) ═══════════════════
    async def _smart_scroll(self, page, direction: str, step: int = 1200, max_attempts: int = 3) -> bool:
        """
        اسکرول هوشمند با افزایش تدریجی قدرت.
        - direction: 'up' یا 'down'
        - step: مقدار پایه (مثبت)
        - max_attempts: تعداد پله‌ها
        برمی‌گرداند: True اگر ارتفاع تغییر کرد، False اگر نه
        """
        old_height = await page.evaluate("document.documentElement.scrollHeight")
        scroll_multipliers = [1, 1.8, 2.8]  # پله‌های افزایشی

        for i in range(min(max_attempts, len(scroll_multipliers))):
            multiplier = scroll_multipliers[i]
            amount = int(step * multiplier)
            if direction == 'up':
                amount = -amount

            self.logger.debug(f"   اسکرول {amount}px (پله {i+1})")
            await page.evaluate(f"window.scrollBy(0, {amount})")
            await human_sleep(1.2, 0.3)

            new_height = await page.evaluate("document.documentElement.scrollHeight")
            if new_height != old_height:
                self.logger.info(f"✅ ارتفاع صفحه تغییر کرد: {old_height} → {new_height}")
                return True

        self.logger.info(f"⚠️ ارتفاع صفحه پس از {max_attempts} اسکرول تغییر نکرد.")
        return False
    # ═══════════════════ اسکرین‌شات خطا برای دیباگ ═══════════════════
    async def _capture_error_screenshot(self, page, error_type: str, description: str = ""):
        """
        گرفتن اسکرین‌شات از صفحه در هنگام بروز خطا برای دیباگ (فقط در صورت فعال بودن).
        """
        if not self.save_screenshots:
            return
        try:
            error_dir = self.debug_screenshots_dir / "error_screenshots"
            error_dir.mkdir(parents=True, exist_ok=True)
 
            # ایجاد نام فایل با timestamp و نوع خطا
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_channel = self._sanitize_filename(self.channel)
            safe_error = self._sanitize_filename(error_type)
            filename = f"{safe_channel}_{safe_error}_{timestamp}.png"

            # در صورت وجود توضیح، به نام فایل اضافه کن
            if description:
                safe_desc = self._sanitize_filename(description)[:50]  # محدود کردن طول
                filename = f"{safe_channel}_{safe_error}_{safe_desc}_{timestamp}.png"

            path = error_dir / filename
            await page.screenshot(path=path, full_page=True)
            self.logger.info(f"📸 اسکرین‌شات خطا ذخیره شد: {path.name}")
            self.logger.info(f"   نوع خطا: {error_type} | توضیح: {description}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات خطا: {e}")
    # ═══════════════════ بررسی بالای صفحه (کمکی) ═══════════════════
    async def _is_at_top(self, page) -> bool:
        """بررسی میکند که آیا صفحه به بالاترین نقطه رسیده است (با ۱۰۰px تحمل)."""
        return await page.evaluate("""
            () => {
                const scrollTop = document.documentElement.scrollTop;
                return scrollTop <= 100;
            }
        """)
    async def _is_at_bottom(self, page) -> bool:
        """بررسی انتهای صفحه با ۱۰۰px تحمل."""
        return await page.evaluate("""
            () => {
                const scrollTop = document.documentElement.scrollTop;
                const clientHeight = document.documentElement.clientHeight;
                const scrollHeight = document.documentElement.scrollHeight;
                return scrollTop + clientHeight >= scrollHeight - 100;
            }
        """)
    # ═══════════════════ استخراج پست‌ها (نسخه نهایی با پشتیبانی Resume) ═══════════════════

    async def _fetch_posts_from_telegram(self, existing_seen_ids: set = None, keep_browser_open: bool = False, existing_context: Any = None, existing_page: Any = None, limit: int = None) -> Tuple[List[Dict], Any, Any]:
        """
        استخراج پست‌ها از کانال تلگرام با پشتیبانی از Resume و start_link.

        Args:
            existing_seen_ids (set): مجموعه‌ی شناسه‌های پست‌های قبلی (برای جلوگیری از تکرار)
            keep_browser_open (bool): اگر True باشد، مرورگر بعد از پایان بسته نمی‌شود
            existing_context (Any): context موجود از دور قبل (اختیاری)
            existing_page (Any): page موجود از دور قبل (اختیاری)
            limit (int): تعداد پست‌های مورد نظر در این دور (اگر None باشد، از self.limit استفاده می‌کند)
        """
        from playwright.async_api import async_playwright

        # ─── اگر context و page از قبل وجود دارند، از آن‌ها استفاده کن ──
        if existing_context is not None and existing_page is not None:
            context = existing_context
            page = existing_page
            p = None  # برای اینکه در انتها بسته نشود
            self.logger.info("♻️ استفاده مجدد از context و page موجود")
        else:
            # ─── راه‌اندازی مرورگر ──────────────────────────────────
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
            if existing_context is None:
                await context.close()
            return [], None, None

        # ─── ورود به کانال یا لینک ──────────────────────────────
        if self.start_link:
            entered = await self._navigate_to_start_link(page)
        else:
            entered = await self._search_and_enter_channel(page)

        if not entered:
            if existing_context is None:
                await context.close()
            return [], None, None
        if self.save_screenshots:
            await self._save_screenshot(page, "initial")

        # ─── پرش به پایین (فقط در حالت عادی و بدون resume) ────
        # هماهنگی با debug_scraper: اگر debug_mode فعال و scroll_direction == 'up' باشد، پرش انجام نمی‌شود
        if not self.start_link and not self._resume_loaded:
            # از self.debug_mode و self.scroll_direction استفاده می‌کنیم
            if not self.debug_mode or self.scroll_direction == 'down':
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
            else:
                self.logger.info(f"🔄 حالت Debug با جهت '{self.scroll_direction}' → پرش به پایین غیرفعال شد.")
        elif self.start_link:
            self.logger.info("ℹ️ در حالت start_link، پرش به پایین انجام نمی‌شود.")
        else:
            self.logger.info(f"ℹ️ حالت Resume: از msg_id={self._resume_data.get('last_msg_id')} ادامه می‌دهیم.")

        # ─── جمع‌آوری پست‌ها ──────────────────────────────────
        items = []
        # اگر مجموعه‌ی شناسه‌های قبلی ارسال شده، از آن استفاده کن
        if existing_seen_ids is not None:
            seen_ids = existing_seen_ids.copy()
        else:
            seen_ids = set()
        scroll_attempts = 0

        # تعیین نقطه شروع برای Resume
        if self._resume_loaded and self._resume_data is not None:
            resume_last_id = self._resume_data.get('last_msg_id')
        else:
            resume_last_id = None
        collected_count = 0

        # ─── تعیین وضعیت start_collecting ──────────────────────
        # اگر start_link یا resume داریم، باید به دنبال نقطه شروع بگردیم
        has_specific_start = bool(self.start_link or self._resume_loaded)

        if has_specific_start:
            start_collecting = False  # نیاز به پیدا کردن نقطه شروع
            extra_scroll_count = 0
            max_extra_scrolls = 4
        else:
            start_collecting = True   # از ابتدا جمع‌آوری می‌کنیم
            extra_scroll_count = 0    # نیازی به اسکرول اضافی نیست

        # ─── اگر Resume داریم، به پیام مورد نظر برویم ──────────
        # ─── Resume به start_link تبدیل شده است، نیازی به جستجوی جداگانه نیست ──
        # اگر resume_last_id وجود دارد، فقط برای لاگ نگه داشته می‌شود، اما عملیات اضافی انجام نمی‌شود.
        if resume_last_id:
            self.logger.info(f"🔄 Resume از پیام {resume_last_id} ادامه می‌یابد (از طریق start_link).")
            # هیچ عملیات دیگری انجام نمی‌شود – منطق start_link کار را انجام می‌دهد.

        # ─── اگر start_link داریم، پیام هدف را پیدا کن ──────────
        if self.start_link and self.target_msg_id:
            self.logger.info(f"🎯 پیدا کردن پیام هدف {self.target_msg_id}...")
            target_found = False
            try:
                # ⏳ صبر برای اسکرول خودکار تلگرام به پیام هدف
                await human_sleep(4, 0.5)
                
                target_locator = page.locator(f'[data-message-id="{self.target_msg_id}"]').first
                if await target_locator.count() > 0:
            
                    await target_locator.scroll_into_view_if_needed()
                    await page.evaluate("window.scrollBy(0, -150)")
                    await human_sleep(1, 0.3)
                    self.logger.info("✅ پیام هدف به بالای صفحه منتقل شد.")
                    target_found = True
                    # بلافاصله start_collecting را فعال کن تا اسکرول اضافی انجام نشود
                    start_collecting = True
                    seen_ids.add(self.target_msg_id)
                    self.logger.info(f"🎯 شروع جمع‌آوری از پیام هدف {self.target_msg_id}")
                    
                    # ─── اسکرول اولیه برای بارگذاری پست‌های قدیمی‌تر ───
                    self.logger.info("⬆️ بارگذاری پست‌های قدیمی‌تر با اسکرول به بالا...")
                    for scroll_step in range(3):
                        await page.evaluate(f"window.scrollBy(0, {SCROLL_UP})")
                        await human_sleep(1.5, 0.3)
                        self.logger.debug(f"   اسکرول {scroll_step+1}/3 انجام شد")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در انتقال پیام هدف: {e}")
                # در صورت بروز Exception، اسکرین‌شات خطا بگیر
                await self._capture_error_screenshot(
                    page,
                    "target_scroll_exception",
                    f"{str(e)[:100]}"
                )

            # اگر target پیدا نشد، پیمایش هوشمند با گام‌های کوچک و تشخیص تاریخ
            if not target_found:
                self.logger.warning("⚠️ پیام هدف پیدا نشد. پیمایش آرام به بالا برای یافتن اولین پست دارای تاریخ...")
                found_any_post = False
                max_slow_steps = 20
                for step in range(max_slow_steps):
                    await page.evaluate("window.scrollBy(0, -600)")
                    await asyncio.sleep(0.4)
                    messages = await page.locator('div[data-message-id]').all()
                    for msg in messages:
                        msg_id = await msg.get_attribute('data-message-id')
                        if not msg_id or msg_id in seen_ids:
                            continue
                        # بررسی وجود تاریخ (اولویت) و در صورت نبود، وجود کپشن کافی
                        date_el = msg.locator('time, .date, [class*="date"], [datetime]').first
                        has_date = await date_el.count() > 0
                        has_caption = False
                        if not has_date:
                            try:
                                text_content = (await msg.inner_text()).strip()
                                has_caption = len(text_content) > 10   # حداقل ۱۰ کاراکتر
                            except:
                                pass
                        if has_date or has_caption:
                            self.logger.info(f"🔍 اولین پست معتبر پیدا شد: {msg_id} (تاریخ: {has_date}, کپشن: {has_caption}) — شروع جمع‌آوری")
                            self.target_msg_id = msg_id
                            target_found = True
                            start_collecting = True
                            seen_ids.add(msg_id)
                            await msg.scroll_into_view_if_needed()
                            await page.evaluate("window.scrollBy(0, -150)")
                            await human_sleep(1, 0.3)
                            self.logger.info("⬆️ بارگذاری پست‌های قدیمی‌تر با اسکرول به بالا...")
                            for scroll_step in range(3):
                                await page.evaluate(f"window.scrollBy(0, {SCROLL_UP})")
                                await human_sleep(1.5, 0.3)
                            found_any_post = True
                            break
                    if found_any_post:
                        break
                if not target_found:
                    self.logger.warning("⚠️ هیچ پست دارای تاریخی پیدا نشد. بازگشت نتیجهٔ خالی برای retry.")
                    # 📸 اسکرین‌شات اضطراری
                    try:
                        safe_name = self._sanitize_filename(f"target_{self.target_msg_id}_not_found")
                        path = self.debug_screenshots_dir / f"{safe_name}.png"
                        await page.screenshot(path=path, full_page=True)
                        self.logger.info(f"📸 اسکرین‌شات صفحه ذخیره شد: {path.name}")
                    except Exception as e:
                        self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات: {e}")
                    return [], context, page
        # ─── حلقه اصلی استخراج ──────────────────────────────────
        target_limit = limit if limit is not None else self.limit
        while len(items) < target_limit and scroll_attempts < self.max_scroll_attempts:
            try:
                # اطمینان از بارگذاری حداقل یک پست جدید
                try:
                    await page.wait_for_selector(
                        'div[data-message-id]', 
                        state='attached', 
                        timeout=2000  # ۲ ثانیه صبر کن
                    )
                except Exception:
                    self.logger.debug("⏳ هیچ پست جدیدی در این مرحله بارگذاری نشد.")
                
                messages = await page.locator('div[data-message-id]').all()
                self.logger.debug(f"🔍 تعداد پیام‌های موجود: {len(messages)}")

                # انتخاب ترتیب بر اساس جهت اسکرول
                if self.scroll_direction == 'up':
                    # اسکرول به بالا: از جدید به قدیم (معکوس)
                    msg_iter = reversed(messages)
                else:
                    # اسکرول به پایین: از قدیم به جدید (عادی)
                    msg_iter = messages
                # در حالت resume، پست‌های جدیدتر قبل از نقطه شروع رد می‌شوند

                for msg in msg_iter:
                    try:
                        msg_id = await msg.get_attribute('data-message-id')
                        if not msg_id or msg_id in seen_ids:
                            continue

                        # در حالت start_link، فقط بعد از رسیدن به پیام هدف شروع کن
                        if self.start_link and not start_collecting:
                            if msg_id == self.target_msg_id:
                                start_collecting = True
                                self.logger.info(f"🎯 به پیام هدف رسیدیم (ID: {msg_id})، شروع جمع‌آوری...")
                                seen_ids.add(msg_id)
                                continue  # خود پیام هدف را جمع نمی‌کنیم (قبلاً اسکرپ شده)
                            else:
                                continue

                        # اگر هنوز شروع نکرده‌ایم، ادامه نده
                        if not start_collecting:
                            continue

                        # ═══════════════ فقط پست‌های قدیمی‌تر از نقطه شروع را جمع کن ═══════════════
                        # در حالت start_link، فقط پست‌هایی با ID کوچکتر از target_msg_id را قبول کن
                        if self.start_link and int(msg_id) >= int(self.target_msg_id):
                            self.logger.debug(f"⏭️ پست {msg_id} جدیدتر یا مساوی هدف است، رد می‌شود.")
                            continue

                        # ═══════════════ استخراج هوشمند متن پست ═══════════════
                        text = ""
                        try:
                            # روش ۱: selectorهای خاص برای محتوای اصلی
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
                                    if text and len(text) > 3:
                                        break

                            # روش ۲: استفاده از inner_text کل پیام
                            if not text or len(text) < 5:
                                try:
                                    text = (await msg.inner_text()).strip()[:1000]
                                except Exception as e:
                                    self.logger.debug(f"   inner_text fallback failed for {msg_id}: {e}")

                            # روش ۳: JavaScript textContent
                            if not text or len(text) < 5:
                                try:
                                    text = (await msg.evaluate("el => el.textContent || ''")).strip()[:1000]
                                except Exception as e:
                                    self.logger.debug(f"   textContent fallback failed for {msg_id}: {e}")

                            # روش ۴: (اضطراری) استفاده از page.evaluate
                            if not text or len(text) < 5:
                                try:
                                    text = (await page.evaluate(f"""
                                        () => {{
                                            const el = document.querySelector('[data-message-id="{msg_id}"]');
                                            return el ? el.innerText || el.textContent || '' : '';
                                        }}
                                    """)).strip()[:1000]
                                except Exception as e:
                                    self.logger.debug(f"   emergency evaluate failed for {msg_id}: {e}")

                            # تمیز کردن نهایی
                            if text:
                                text = re.sub(r'\s+', ' ', text).strip()[:1000]

                            if not text or len(text) < 2:
                                self.logger.debug(f"⚠️ متن پست {msg_id} خالی یا بسیار کوتاه است.")

                        except Exception as e:
                            self.logger.warning(f"❌ خطا در استخراج متن پست {msg_id}: {e}")
                            text = ""

                        # استخراج تاریخ
                        date_el = msg.locator('time, .message-date, .date, span[class*="date"]').first
                        date = ""
                        try:
                            if await date_el.count() > 0:
                                date = await date_el.inner_text() or await date_el.get_attribute('datetime') or ""
                        except Exception:
                            pass

                        items.append({
                            'id': msg_id,
                            'text': text,
                            'date': date,
                            'url': f"https://t.me/{self.channel}/{msg_id}"
                        })
                        seen_ids.add(msg_id)
                        collected_count += 1

                        # ذخیره وضعیت هر ۳ پست (برای ادامه در صورت شکست)
                        if collected_count % 3 == 0:
                            self._save_resume_state(msg_id, collected_count)

                        if len(items) >= target_limit:
                            break

                    except Exception as e:
                        self.logger.debug(f"خطا در پردازش پیام: {e}")
                        continue

            except Exception as e:
                self.logger.error(f"❌ خطا در استخراج پست‌ها: {e}")

            if len(items) >= target_limit:
                break

            # ─── اسکرول هوشمند ──────────────────────────────────
            # همیشه از جهت ذخیره‌شده در self.scroll_direction استفاده می‌کنیم
            scrolled = await self._smart_scroll(page, self.scroll_direction, step=1200, max_attempts=3)
            
            if scrolled:
                scroll_attempts = 0
                self.logger.debug(f"✅ اسکرول هوشمند موفق بود (جهت: {self.scroll_direction})")
            else:
                scroll_attempts += 1
                self.logger.debug(f"⚠️ اسکرول هوشمند ناموفق. تلاش {scroll_attempts}/{self.max_scroll_attempts}")
                # خروج فوری اگر به حاشیه صفحه رسیده باشیم
                if self.scroll_direction == 'up' and await self._is_at_top(page):
                    self.logger.info("📌 به بالای صفحه رسیدیم. اسکرول متوقف می‌شود.")
                    scroll_attempts = self.max_scroll_attempts
                elif self.scroll_direction == 'down' and await self._is_at_bottom(page):
                    self.logger.info("📌 به پایین صفحه رسیدیم. اسکرول متوقف می‌شود.")
                    scroll_attempts = self.max_scroll_attempts
            # ─── اگر start_collecting فعال نشده و در حالت خاص هستیم، اسکرول اضافی ──
            if not start_collecting and has_specific_start:
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
            # در غیر این صورت (حالت عادی) هیچ اسکرول اضافی انجام نمی‌شود

            # ─── تاخیر برای جلوگیری از بارگذاری بیش از حد ──────
            if len(items) % 5 == 0 and len(items) > 0:
                await human_sleep(1.5, 0.3)

        # ─── محدود کردن به تعداد مورد نظر ──────────────────────
        items = items[:target_limit]
        self.logger.info(f"📊 {len(items)} پست جمع‌آوری شد.")

        # ─── اسکرین‌شات نهایی ──────────────────────────────────
        if self.save_screenshots:
            await self._save_screenshot(page, "final")
            await self._capture_post_screenshots(page, items)
        else:
            self.logger.info("⏭️ اسکرین‌شات‌ها غیرفعال هستند.")

        # ─── اسکرول به اولین پست ──────────────────────────────
        if items:
            first_id = items[0]['id']
            try:
                await page.locator(f'[data-message-id="{first_id}"]').scroll_into_view_if_needed()
                await human_sleep(1, 0.3)
            except Exception:
                pass

        # اگر keep_browser_open فعال باشد یا از context موجود استفاده شده باشد، مرورگر را نبند
        if (keep_browser_open or existing_context is not None) and context:
            # مرورگر را باز نگه دار
            pass
        else:
            if context:
                await context.close()

        return items, context, page
    # ═══════════════════ جستجو و ورود به کانال ═══════════════════

    async def _search_and_enter_channel(self, page) -> bool:
        """
        جستجوی کانال و ورود به آن.

        Args:
            page: صفحه مرورگر

        Returns:
            bool: موفقیت‌آمیز بودن عملیات
        """
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
        if self.save_screenshots:
            await self._take_screenshot(page, "search_input_filled")
        await human_sleep(1.5, 0.3)
        await page.keyboard.press("Enter")
        self.logger.info("⏳ منتظر نتایج...")

        search_term = self.channel_name if self.channel_name else self.channel
        found = False

        # انتظار با چند مرحله
        for wait_time, stage in [(10, "اول"), (15, "دوم"), (20, "سوم")]:
            self.logger.info(f"🕐 مرحله {stage} انتظار ({wait_time} ثانیه)...")
            await human_sleep(wait_time, 0.5)
            if await self._check_text_on_page(page, search_term):
                found = True
                self.logger.info(f"   ✅ عبارت '{search_term}' در مرحله {stage} یافت شد.")
                break

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
            if self.save_screenshots:
                await self._take_screenshot(page, "search_failed")
            return False

        self.logger.info("✅ نتایج جستجو ظاهر شدند.")
        if self.save_screenshots:
            await self._take_screenshot(page, f"search_results_{self.channel}")
        await human_sleep(2, 0.3)
        if self.save_screenshots:
            await self._take_screenshot(page, "before_click_final")

        return await self._click_search_result(page, search_term)

    # ═══════════════════ متد جستجو با لینک ═══════════════════

    async def _navigate_to_start_link(self, page) -> bool:
        """
        رفتن به لینک مستقیم یک پست.

        Args:
            page: صفحه مرورگر

        Returns:
            bool: موفقیت‌آمیز بودن عملیات
        """
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
            if self.save_screenshots:
                await self._take_screenshot(page, "search_link_filled")
            await page.keyboard.press("Enter")
            self.logger.info("⏳ منتظر نتایج جستجو...")
            await human_sleep(5, 0.5)
            if self.save_screenshots:
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
                    if self.save_screenshots:
                        await self._take_screenshot(page, "after_js_click")
                    self.logger.info("✅ کلیک با JavaScript انجام شد.")
                    clicked = True
                except Exception as e:
                    self.logger.error(f"❌ کلیک با JavaScript شکست خورد: {e}")

            if not clicked:
                self.logger.error("❌ نتوانستیم روی هیچ نتیجه‌ای کلیک کنیم.")
                if self.save_screenshots:
                    await self._take_screenshot(page, "click_result_failed")
                return False
            for attempt in range(3):
                try:
                    await page.wait_for_selector('div[data-message-id]', timeout=15000)
                    self.logger.info("✅ صفحه پیام‌ها با موفقیت بارگذاری شد.")
                    if self.save_screenshots:
                        await self._take_screenshot(page, "messages_page_loaded")
                    return True
                except Exception as e:
                    self.logger.warning(f"⚠️ تلاش {attempt+1} برای بارگذاری پیام‌ها ناموفق: {e}")
                    if attempt < 2:
                        await human_sleep(3, 0.5)

            self.logger.error("❌ پس از کلیک، پیام‌ها پیدا نشدند.")
            if self.save_screenshots:
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
        """بررسی وجود یک عبارت در صفحه."""
        try:
            return await page.evaluate(f'''(t) => {{
                const bodyText = document.body.innerText || '';
                return bodyText.toLowerCase().includes(t.toLowerCase());
            }}''', term)
        except Exception:
            return False

    # ═══════════════════ کلیک روی نتیجه جستجو ═══════════════════

    async def _click_search_result(self, page, search_term: str) -> bool:
        """کلیک روی نتیجه جستجو برای ورود به کانال."""
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
        if self.save_screenshots:
            await self._take_screenshot(page, "click_failed")
        return False

    # ═══════════════════ اسکرین‌شات از تکتک پست‌ها ═══════════════════

    async def _capture_post_screenshots(self, page, items: List[Dict]):
        """گرفتن اسکرین‌شات از هر پست به‌صورت جداگانه (فقط در صورت فعال بودن)."""
        if not self.save_screenshots:
            self.logger.info("⏭️ ذخیره اسکرین‌شات پست‌ها غیرفعال است.")
            return
        self.logger.info(f"📸 گرفتن اسکرین‌شات از {len(items)} پست...")
   
        for idx, item in enumerate(items):
            msg_id = item['id']
            try:
                locator = page.locator(f'[data-message-id="{msg_id}"]').first
                if await locator.count() == 0:
                    self.logger.warning(f"⚠️ المان پست {msg_id} پیدا نشد، رد می‌شود.")
                    # اسکرین‌شات خطا برای بررسی وضعیت صفحه
                    await self._capture_error_screenshot(
                        page,
                        "post_not_found",
                        f"post_id={msg_id} not found in DOM"
                    )
                    continue

                safe_channel = self._sanitize_filename(self.channel)
                safe_msg_id = self._sanitize_filename(str(msg_id))
                path = self.screenshots_dir / f"{safe_channel}_post_{safe_msg_id}.png"
                
                if path.exists():
                    self.logger.debug(f"⏭️ اسکرین‌شات پست {msg_id} قبلاً وجود دارد، رد می‌شود.")
                    continue
                
                # اسکرول به المنت و گرفتن اسکرین‌شات با مدیریت خطا
                try:
                    await locator.scroll_into_view_if_needed()
                    await human_sleep(0.5, 0.2)
                    await locator.screenshot(path=path, timeout=30000)
                except Exception as e:
                    self.logger.warning(f"⚠️ خطا در اسکرین‌شات پست {msg_id}: {str(e)[:100]}")
                    # اسکرین‌شات خطا برای بررسی وضعیت صفحه
                    await self._capture_error_screenshot(
                        page,
                        "screenshot_failed",
                        f"post_id={msg_id} - {str(e)[:50]}"
                    )
                    continue
                self.logger.debug(f"📸 اسکرین‌شات ذخیره شد: {path.name}")

                if (idx + 1) % 10 == 0:
                    self.logger.info(f"   {idx+1}/{len(items)} اسکرین‌شات گرفته شد.")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در اسکرین‌شات پست {msg_id}: {e}")
                continue

        self.logger.info(f"✅ اسکرین‌شات‌ها تمام شد. مجموع: {len(items)}")

    # ═══════════════════ دانلود رسانه‌ها ═══════════════════

    async def _download_media(self, items: List[Dict], page, context) -> Tuple[Dict, int]:
        """
        دانلود رسانه‌های مرتبط با پست‌ها.

        Args:
            items (List[Dict]): لیست پست‌ها
            page: صفحه مرورگر
            context: زمینه مرورگر

        Returns:
            Tuple[Dict, int]: (نقشه رسانه‌ها, تعداد دانلودها)
        """
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
