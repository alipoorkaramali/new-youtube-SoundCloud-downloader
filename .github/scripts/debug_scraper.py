#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ برای Telegram Channel Scraper – نسخه هماهنگ با scraper.py
– کاربر می‌تواند تعیین کند که از پست خاص به بالا (قدیمی‌تر) برود یا پایین (جدیدتر).
– تمام مراحل اسکرپینگ (جستجو، ورود، اسکرول، استخراج) را انجام می‌دهد.
– رسانه‌ها را دانلود نمی‌کند (فقط لاگ).
– اسکرین‌شات‌های کامل صفحه برای تحلیل بهتر ذخیره می‌کند.
"""

import asyncio
import json
import sys
import random
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import load_config
from scraper import TelegramChannelScraper, HOME_URL  # ← اضافه شد
from output_generator import OutputGenerator


# ═══════════════════ Human-like sleep ═══════════════════
async def human_sleep(base: float, jitter: float = 0.4):
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class DebugTelegramChannelScraper(TelegramChannelScraper):
    """
    نسخه‌ی دیباگ اسکرپر با قابلیت انتخاب جهت اسکرول.
    هماهنگ با scraper.py – از متد _smart_scroll با پله‌های افزایشی استفاده می‌کند.
    """

    def __init__(self, config, debug_screenshots: bool = True):
        config.debug_mode = True
        super().__init__(config)
        self.debug_screenshots = debug_screenshots
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)

        # پارامتر جدید: جهت اسکرول (up/down)
        self.scroll_direction = getattr(config, 'scroll_direction', 'up').lower()
        if self.scroll_direction not in ['up', 'down']:
            self.logger.warning(f"⚠️ مقدار نامعتبر برای scroll_direction: {self.scroll_direction}. استفاده از 'up'.")
            self.scroll_direction = 'up'

        # ═══════════════ غیرفعال کردن auto_resume در حالت دیباگ ═══════════════
        # در حالت دیباگ، فقط یک دور اجرا می‌شود و auto_resume نادیده گرفته می‌شود
        #self.auto_resume = False

        # ═══════════════ مقداردهی resume_data (رفع AttributeError) ═══════════════
        if not hasattr(self, 'resume_data') or self.resume_data is None:
            self.resume_data = {}
        if 'last_msg_id' not in self.resume_data:
            self.resume_data['last_msg_id'] = None

        # ═══════════════ تبدیل Resume به start_link ═══════════════
        # اگر resume فعال است و فایل معتبری بارگذاری شده، از last_post_link به عنوان start_link استفاده کن
        if self.resume and self._resume_loaded and self._resume_data and 'last_post_link' in self._resume_data:
            self.start_link = self._resume_data['last_post_link']
            self.logger.info(f"🔄 Resume با لینک: {self.start_link} (همانند start_link)")
            # استخراج target_msg_id برای استفاده در _navigate_to_start_link
            try:
                parts = self.start_link.rstrip('/').split('/')
                if parts and parts[-1].isdigit():
                    self.target_msg_id = parts[-1]
                    self.logger.info(f"🎯 شناسه پیام هدف از resume: {self.target_msg_id}")
            except Exception as e:
                self.logger.debug(f"خطا در استخراج target_msg_id از resume: {e}")
        else:
            # اگر resume فعال نبود یا فایل معتبر نبود، start_link را همان مقدار config نگه دار
            pass

        # ═══════════════ لاگ وضعیت save_screenshots (اختیاری) ═══════════════
        self.logger.info(f"🖼️ ذخیره اسکرین‌شات: {'فعال' if self.save_screenshots else 'غیرفعال'}")

        self.logger.info("🐞 حالت دیباگ فعال است – دانلود رسانه انجام نمی‌شود.")
        self.logger.info(f"🐞 پوشه اسکرین‌شات‌های دیباگ: {self.debug_screenshots_dir}")
        self.logger.info(f"🧭 جهت اسکرول: {'بالا (قدیمی‌تر)' if self.scroll_direction == 'up' else 'پایین (جدیدتر)'}")
        self._last_items = []

    async def _download_media(self, items: List[Dict], page, context) -> tuple[dict, int]:
        """در حالت دیباگ، دانلود رسانه غیرفعال است."""
        self.logger.info("🐞 حالت دیباگ: دانلود رسانه غیرفعال است.")
        media_map = {}
        for item in items:
            msg_id = item['id']
            self.logger.info(f"   🖼️ [دیباگ] پست {msg_id}: دانلود رسانه انجام نشد.")
            media_map[msg_id] = []
        return media_map, 0

    async def _save_debug_screenshot(self, page, name: str):
        if not self.debug_screenshots or not self.save_screenshots:
            return
        try:
            self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
            await self._screenshot(page, name, full_page=True)
            self.logger.debug(f"🐞 اسکرین‌شات دیباگ ذخیره شد: {name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات دیباگ: {e}")

    # ═══════════════ اسکرول هوشمند با پله‌های افزایشی (هماهنگ با scraper.py) ═══════════════
    async def _smart_scroll(self, page, direction: str, step: int = 1200, max_attempts: int = 3) -> bool:
        """
        اسکرول هوشمند با سه پله افزایشی.
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
                amount = -amount  # منفی = بالا
            # برای down، amount مثبت می‌ماند

            self.logger.debug(f"   اسکرول {amount}px (پله {i+1})")
            await page.evaluate(f"window.scrollBy(0, {amount})")
            await human_sleep(1.2, 0.3)

            new_height = await page.evaluate("document.documentElement.scrollHeight")
            if new_height != old_height:
                self.logger.info(f"✅ ارتفاع صفحه تغییر کرد: {old_height} → {new_height}")
                return True

        self.logger.info(f"⚠️ ارتفاع صفحه پس از {max_attempts} اسکرول تغییر نکرد.")
        return False

    # ═══════════════ استخراج پست‌ها با JavaScript ═══════════════════
    async def _extract_posts_from_page(self, page) -> List[Dict]:
        """استخراج پست‌ها از صفحه با JavaScript."""
        return await page.evaluate("""
            () => {
                const posts = [];
                document.querySelectorAll('[data-message-id]').forEach(el => {
                    const msgId = el.getAttribute('data-message-id');
                    if (!msgId) return;
                    const textEl = el.querySelector('.text, .message-text, [data-text]');
                    const text = textEl ? textEl.innerText.trim() : '';
                    const dateEl = el.querySelector('.date, .time, [data-date]');
                    const date = dateEl ? dateEl.innerText.trim() : '';
                    posts.push({ id: msgId, text: text, date: date });
                });
                return posts;
            }
        """)

    # ═══════════════ بررسی انتهای صفحه (کمکی) ═══════════════════
    async def _is_at_bottom(self, page) -> bool:
        """بررسی میکند که آیا صفحه به انتها رسیده است (با ۱۰۰px تحمل)."""
        return await page.evaluate("""
            () => {
                const scrollTop = document.documentElement.scrollTop;
                const clientHeight = document.documentElement.clientHeight;
                const scrollHeight = document.documentElement.scrollHeight;
                return scrollTop + clientHeight >= scrollHeight - 100;
            }
        """)
    # ═══════════════ بررسی بالای صفحه (کمکی) ═══════════════════
    async def _is_at_top(self, page) -> bool:
        """بررسی میکند که آیا صفحه به بالاترین نقطه رسیده است (با ۱۰۰px تحمل)."""
        return await page.evaluate("""
            () => {
                const scrollTop = document.documentElement.scrollTop;
                return scrollTop <= 100;
            }
        """)
    # ═══════════════ اسکرین‌شات کامل صفحه ═══════════════════
    async def _capture_full_page_screenshot(self, page, name: str = "full_page"):
        """گرفتن اسکرین‌شات کامل از کل صفحه (فقط در صورت فعال بودن)."""
        if not self.save_screenshots:
            return
        try:
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1.5)
            safe_channel = self._sanitize_filename(self.channel)
            path = self.screenshots_dir / f"{safe_channel}_{name}.png"
            await page.screenshot(path=path, full_page=True)
            self.logger.info(f"📸 اسکرین‌شات کامل صفحه ذخیره شد: {path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در اسکرین‌شات کامل: {e}")

    async def _fetch_posts_from_telegram(self, existing_seen_ids: set = None, keep_browser_open: bool = False, existing_context: any = None, existing_page: any = None) -> tuple[List[Dict], any, any]:
        self.logger.info(f"🐞 شروع استخراج با جهت: {self.scroll_direction} | start_link={bool(self.start_link)}")

        # ۱. اجرای منطق اصلی والد (با keep_browser_open=True تا مرورگر بسته نشود)
        # والد خودش بستن مرورگر را بر اساس keep_browser_open مدیریت می‌کند
        items, context, page = await super()._fetch_posts_from_telegram(
            existing_seen_ids=existing_seen_ids,
            keep_browser_open=True,  # همیشه باز نگه دار تا دیباگ بتواند اسکرول اضافی انجام دهد
            existing_context=existing_context,  # ← اضافه شد
            existing_page=existing_page         # ← اضافه شد
        )
        if not page:
            self.logger.error("❌ صفحه دریافت نشد.")
            return items, context, page

        if not items:
            self.logger.warning("⚠️ والد هیچ پستی تحویل نداد.")
            return items, context, page

        self.logger.info(f"📥 والد {len(items)} پست تحویل داد.")

        # اگر به حد کافی رسیده‌ایم، نیازی به اسکرول اضافی نیست
        if len(items) >= self.limit:
            self.logger.info("✅ به حد limit رسیدیم. نیازی به اسکرول اضافی نیست.")
            if self.save_screenshots:
                await self._capture_full_page_screenshot(page, "final")
            return items, context, page

        # ─── تشخیص حالت ─────────────────────────────
        is_normal_start = not self.start_link and not self.resume_data.get('last_msg_id')
        # بررسی موقعیت صفحه
        at_bottom = await self._is_at_bottom(page)

        # در حالت عادی + direction=down یا در انتها بودن + direction=down → غیرفعال
        if (is_normal_start or at_bottom) and self.scroll_direction == 'down':
            self.logger.info("ℹ️ در انتهای کانال هستیم و direction=down است. اسکرول اضافی لغو شد.")
            if self.save_screenshots:
                await self._capture_full_page_screenshot(page, "final")
            return items, context, page
            
        # تعیین تعداد تلاش
        is_specific_start = bool(self.start_link or self.resume_data.get('last_msg_id'))
        max_attempts = 2 if is_specific_start else 3

        # ─── بررسی وضعیت صفحه قبل از اسکرول ──────────────
        at_top = await self._is_at_top(page)
        at_bottom = await self._is_at_bottom(page)

        # اگر در جهت up هستیم و در بالای صفحه قرار داریم، اسکرول اضافی لازم نیست
        if self.scroll_direction == 'up' and at_top:
            self.logger.info("ℹ️ در بالاترین نقطه هستیم و جهت up است. اسکرول اضافی لغو شد.")
            if self.save_screenshots:
                await self._capture_full_page_screenshot(page, "final")
            return items, context, page

        # اگر در جهت down هستیم و در پایین صفحه قرار داریم، اسکرول اضافی لازم نیست
        if self.scroll_direction == 'down' and at_bottom:
            self.logger.info("ℹ️ در پایین‌ترین نقطه هستیم و جهت down است. اسکرول اضافی لغو شد.")
            if self.save_screenshots:
                await self._capture_full_page_screenshot(page, "final")
            return items, context, page

        self.logger.info(f"🔁 اسکرول اضافی فعال — حداکثر {max_attempts} تلاش")

        # ─── اسکرول اضافی ─────────────────────────────
        # برای جلوگیری از تکرار، از مجموعه‌ی شناسه‌های موجود استفاده می‌کنیم
        seen_ids = {item.get('id') for item in items if item.get('id')}
        no_new_attempts = 0
        new_items = []

        # ─── ایجاد پوشه برای اسکرین‌شات‌های اسکرول اضافی ──
        extra_scroll_dir = self.debug_screenshots_dir / "extra_scroll"
        extra_scroll_dir.mkdir(parents=True, exist_ok=True)
        attempt_counter = 0

        while len(seen_ids) < self.limit and no_new_attempts < max_attempts:
            attempt_counter += 1

            # ─── اسکرین‌شات قبل از اسکرول ──────────────
            try:
                screenshot_name = f"extra_scroll_{self.scroll_direction}_attempt_{attempt_counter}"
                path = extra_scroll_dir / f"{screenshot_name}.png"
                await page.screenshot(path=path, full_page=True)
                self.logger.info(f"📸 اسکرین‌شات اسکرول اضافی ذخیره شد: {path.name}")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در اسکرین‌شات اسکرول اضافی: {e}")

            scrolled = await self._smart_scroll(page, self.scroll_direction, step=1200, max_attempts=3)

            if not scrolled:
                no_new_attempts += 1
                self.logger.debug(f"   بدون تغییر ارتفاع ({no_new_attempts}/{max_attempts})")
                
                # ─── پس از اسکرول ناموفق، دوباره موقعیت را بررسی کن ──
                if self.scroll_direction == 'up':
                    if await self._is_at_top(page):
                        self.logger.info("ℹ️ به بالای صفحه رسیدیم. اسکرول اضافی متوقف می‌شود.")
                        break
                elif self.scroll_direction == 'down':
                    if await self._is_at_bottom(page):
                        self.logger.info("ℹ️ به پایین صفحه رسیدیم. اسکرول اضافی متوقف می‌شود.")
                        break
                
                await human_sleep(0.8, 0.2)
                continue

            current_items = await self._extract_posts_from_page(page)
            added = 0
            for item in current_items:
                iid = item.get('id')
                if iid and iid not in seen_ids:
                    seen_ids.add(iid)
                    new_items.append(item)
                    added += 1

            if added > 0:
                no_new_attempts = 0
                self.logger.info(f"📈 {added} پست جدید اضافه شد (مجموع: {len(seen_ids)})")
            else:
                no_new_attempts += 1

        # اضافه کردن پست‌های جدید
        if new_items:
            # اگر جهت down است، پست‌های جدید (که جدیدتر هستند) را در ابتدا قرار بده
            if self.scroll_direction == 'down':
                new_items.reverse()
            items.extend(new_items)
            self.logger.info(f"📊 مجموع نهایی: {len(items)} پست")

        # ─── به‌روزرسانی resume_data برای ادامه‌ی هوشمند ───
        if items:
            if self.scroll_direction == 'up':
                self.resume_data['last_msg_id'] = items[-1].get('id')
            else:
                self.resume_data['last_msg_id'] = items[0].get('id')
            self.logger.debug(f"📌 last_msg_id به‌روزرسانی شد: {self.resume_data['last_msg_id']}")

        if self.save_screenshots:
            await self._capture_full_page_screenshot(page, "final")
            await self._save_debug_screenshot(page, "debug_final")
        else:
            self.logger.info("⏭️ اسکرین‌شات‌های دیباگ غیرفعال هستند.")

        # لاگ نهایی
        self.logger.info(f"🐞 استخراج تمام شد — {len(items)} پست (جهت: {self.scroll_direction})")

        return items, context, page
        
    async def run(self):
        """اجرای اصلی با ذخیرهٔ خلاصه JSON."""
        await super().run()

        try:
            debug_json_path = self.base_dir / "debug_summary.json"
            summary = {
                "channel": self.channel,
                "limit": self.limit,
                "start_link": self.start_link,
                "scroll_direction": self.scroll_direction,
                "total_posts": len(self._last_items) if hasattr(self, '_last_items') else 0,
                "debug_mode": True
            }
            with open(debug_json_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            self.logger.info(f"🐞 خلاصه دیباگ ذخیره شد: {debug_json_path}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره خلاصه دیباگ: {e}")

    async def _run_impl(self):
        """Override برای ذخیرهٔ آیتم‌ها و تولید خروجی با ادامه خودکار تا رسیدن به limit."""
        if self.start_link:
            self.logger.info(f"🚀 شروع اسکریپر دیباگ با لینک: {self.start_link} (limit={self.limit})")
        else:
            self.logger.info(f"🚀 شروع اسکریپر دیباگ برای @{self.channel} (limit={self.limit})")

        all_items = []
        global_seen_ids = set()
        rounds = 0
        # محاسبه تعداد دورهای مورد نیاز بر اساس limit
        # هر دور تقریباً ۳۰-۵۰ پست جمع می‌کند، بنابراین limit/30 + 2 دور امن است
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

            # اگر دور اول نیست و all_items خالی نیست، resume_point را تنظیم کن
            if rounds > 1 and all_items:
                # پیدا کردن قدیمی‌ترین پستی که اسکرین‌شات آن موجود است
                oldest_post = None
                sorted_items = sorted(all_items, key=lambda x: int(x.get('id', 0)))  # مرتب‌سازی صعودی
                for item in sorted_items:
                    msg_id = item['id']
                    safe_channel = self._sanitize_filename(self.channel)
                    safe_msg_id = self._sanitize_filename(str(msg_id))
                    screenshot_path = self.screenshots_dir / f"{safe_channel}_post_{safe_msg_id}.png"
                    if screenshot_path.exists():
                        oldest_post = item
                        break
                
                if oldest_post is None:
                    # اگر هیچ اسکرین‌شاتی وجود نداشت، از قدیمی‌ترین پست استفاده کن (فال‌بک)
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

            # اجرای یک دور اسکرپ (مرورگر همیشه باز نگه داشته می‌شود تا دانلود انجام شود)
            if rounds == 1:
                items, context, page = await self._fetch_posts_from_telegram(
                    existing_seen_ids=global_seen_ids,
                    keep_browser_open=True  # همیشه True
                )
            else:
                # در دورهای بعدی، از context و page موجود استفاده کن
                items, context, page = await self._fetch_posts_from_telegram(
                    existing_seen_ids=global_seen_ids,
                    keep_browser_open=True,  # همیشه True
                    existing_context=context,
                    existing_page=page
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

            if len(all_items) >= self.limit or rounds >= max_rounds:
                break

            # اگر به بالای صفحه رسیدیم و هنوز به limit نرسیدیم، ادامه بده
            if hasattr(self, '_is_at_top') and await self._is_at_top(page):
                self.logger.info("📌 به بالای صفحه رسیدیم. شروع دور بعدی...")
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                continue

        # ─── محدود کردن به تعداد مورد نظر ──────────────────────
        if len(all_items) > self.limit:
            all_items = all_items[:self.limit]
            self.logger.info(f"📊 تعداد پست‌ها به {self.limit} محدود شد.")

        # ─── پردازش نهایی ──────────────────────────────────
        self._last_items = all_items

        if not all_items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            if context:
                await context.close()
            return

        self.logger.info(f"📥 {len(all_items)} پست استخراج شد (در {rounds} دور).")

        # ─── دانلودهای کل انجام شده در طول دورها ──────────────
        self.logger.info(f"🖼️ مجموع {downloaded_total} فایل رسانه در {rounds} دور دانلود شد.")
        self.logger.info(f"📊 media_map برای {len(all_media_map)} پست پر شد.")
        
        # برای سازگاری با OutputGenerator، از all_media_map استفاده می‌کنیم
        media_map = all_media_map

        # در دیباگ، رسانه‌ها دانلود نمی‌شوند (اما ساختار یکسان است)
        try:
            append_mode = self.resume and self._resume_loaded
            gen = OutputGenerator(
                self.base_dir,
                self.channel,
                all_items,
                media_map,  # ← از all_media_map استفاده می‌شود
                debug_mode=self.debug_mode,
                append_mode=append_mode
            )
            gen.run_all()
            self.logger.info(f"🐞 فایل‌های خروجی دیباگ در: {self.base_dir}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در تولید خروجی: {e}", exc_info=True)

        if context:
            await context.close()

        self.logger.info("✅ پایان موفقیت‌آمیز دیباگ.")
async def main():
    print("🐞 ========================================")
    print("🐞 Telegram Channel Scraper - حالت دیباگ (هماهنگ با scraper.py)")
    print("🐞 ========================================")

    config_path = "config/config.yaml"
    try:
        config = load_config(config_path)
        print(f"✅ تنظیمات از {config_path} بارگذاری شد.")
        print(f"   کانال: {config.channel}")
        print(f"   limit: {config.limit}")
        if config.start_link:
            print(f"   start_link: {config.start_link}")
        scroll_dir = getattr(config, 'scroll_direction', 'up')
        print(f"   جهت اسکرول: {'بالا (قدیمی‌تر)' if scroll_dir == 'up' else 'پایین (جدیدتر)'}")
    except FileNotFoundError:
        print(f"❌ فایل {config_path} یافت نشد.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ خطا در بارگذاری کانفیگ: {e}")
        sys.exit(1)

    scraper = DebugTelegramChannelScraper(config, debug_screenshots=True)

    try:
        await scraper.run()
        print("\n🐞 دیباگ با موفقیت کامل شد.")
        print(f"🐞 خروجی‌ها در پوشه: {scraper.base_dir}")
        print(f"🐞 اسکرین‌شات‌های دیباگ در: {scraper.debug_screenshots_dir}")
        print(f"🐞 اسکرین‌شات‌های پست‌ها در: {scraper.screenshots_dir}")
    except Exception as e:
        print(f"\n❌ خطا در اجرای دیباگ: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
