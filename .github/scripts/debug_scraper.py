#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ برای Telegram Channel Scraper – نسخه هماهنگ با scraper.py
– کاربر می‌تواند تعیین کند که از پست خاص به بالا (قدیمی‌تر) برود یا پایین (جدیدتر).
– تمام مراحل اسکرپینگ (جستجو، ورود، اسکرول، استخراج) را انجام می‌دهد.
– رسانه‌ها را دانلود نمی‌کند (فقط لاگ).
– اسکرین‌شات‌های کامل صفحه برای تحلیل بهتر ذخیره می‌کند.
– قابلیت ادامه (Resume) از آخرین نقطه استخراج شده با رفتن دقیق به لینک ذخیره‌شده.
– در حالت Resume، فایل HTML قبلی را با پست‌های جدید ادغام کرده و مرتب‌سازی می‌کند.
"""

import asyncio
import json
import sys
import random
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import load_config
from scraper import TelegramChannelScraper
from output_generator import OutputGenerator


# ═══════════════════ Human-like sleep ═══════════════════
async def human_sleep(base: float, jitter: float = 0.4):
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class DebugTelegramChannelScraper(TelegramChannelScraper):
    """
    نسخه‌ی دیباگ اسکرپر با قابلیت انتخاب جهت اسکرول و ادامه از آخرین نقطه.
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

        # ========== RESUME: خواندن وضعیت و تنظیم start_link ==========
        self.resume = getattr(config, 'resume', False)
        self.resume_state_file = self.base_dir / "resume_state.json"
        self._resume_data = None
        self._resume_loaded = False  # برای لاگ‌گذاری بهتر

        if self.resume:
            self.logger.info("🔄 حالت ادامه (Resume) فعال است.")
            if self.resume_state_file.exists():
                try:
                    with open(self.resume_state_file, 'r', encoding='utf-8') as f:
                        self._resume_data = json.load(f)
                    last_link = self._resume_data.get('last_post_link')
                    if last_link:
                        # 🔥 اینجا دقیقاً رفتن به لینک ذخیره‌شده اتفاق می‌افتد
                        self.start_link = last_link
                        self.scroll_direction = 'up'  # اجباراً به سمت بالا (قدیمی‌تر)
                        self._resume_loaded = True
                        self.logger.info(f"🔗 لینک ادامه بارگذاری شد: {last_link}")
                        self.logger.info(f"🧭 جهت اسکرول به‌طور خودکار به 'up' (قدیمی‌تر) تنظیم شد.")
                    else:
                        self.logger.warning("⚠️ فایل وضعیت موجود است اما 'last_post_link' پیدا نشد. ادامه بدون resume.")
                        self.resume = False
                except Exception as e:
                    self.logger.warning(f"⚠️ خطا در خواندن فایل وضعیت: {e}. ادامه بدون resume.")
                    self.resume = False
            else:
                self.logger.warning(f"⚠️ فایل وضعیت '{self.resume_state_file}' یافت نشد. ادامه بدون resume.")
                self.resume = False

        # اگر resume فعال نباشد ولی start_link دستی داشته باشیم، لاگ می‌دهیم
        if self.start_link and not self.resume:
            self.logger.info(f"🔗 لینک شروع دستی: {self.start_link}")

        self.logger.info("🐞 حالت دیباگ فعال است – دانلود رسانه انجام نمی‌شود.")
        self.logger.info(f"🐞 پوشه اسکرین‌شات‌های دیباگ: {self.debug_screenshots_dir}")
        self.logger.info(f"🧭 جهت اسکرول نهایی: {'بالا (قدیمی‌تر)' if self.scroll_direction == 'up' else 'پایین (جدیدتر)'}")
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
        if not self.debug_screenshots:
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

    # ═══════════════ اسکرین‌شات کامل صفحه ═══════════════════
    async def _capture_full_page_screenshot(self, page, name: str = "full_page"):
        """گرفتن اسکرین‌شات کامل از کل صفحه."""
        try:
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)
            safe_channel = self._sanitize_filename(self.channel)
            path = self.screenshots_dir / f"{safe_channel}_{name}.png"
            await page.screenshot(path=path, full_page=True)
            self.logger.info(f"📸 اسکرین‌شات کامل صفحه ذخیره شد: {path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در اسکرین‌شات کامل: {e}")

    # ═══════════════ ادغام با فایل HTML موجود (برای Resume) ═══════════════
    def _merge_with_existing_posts(self, new_items: List[Dict]) -> List[Dict]:
        """
        اگر فایل HTML از قبل وجود داشته باشد، پست‌های آن را خوانده و با پست‌های جدید ادغام می‌کند.
        سپس همه را بر اساس msg_id مرتب می‌کند (جدیدترین = بزرگترین id).
        """
        html_path = self.base_dir / f"{self.channel}_posts.html"
        if not html_path.exists():
            return new_items

        try:
            from bs4 import BeautifulSoup
            with open(html_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
            
            existing_posts = []
            # فرض می‌کنیم هر پست در یک <div class="post"> قرار دارد
            for div in soup.find_all('div', class_='post'):
                msg_id = div.get('data-msg-id')
                if msg_id:
                    text_div = div.find('div', class_='text')
                    date_div = div.find('div', class_='date')
                    existing_posts.append({
                        'id': msg_id,
                        'text': text_div.get_text(strip=True) if text_div else '',
                        'date': date_div.get_text(strip=True) if date_div else ''
                    })
            
            # ترکیب با پست‌های جدید
            all_posts = existing_posts + new_items
            # حذف تکراری‌ها بر اساس id
            seen = set()
            unique_posts = []
            for post in all_posts:
                if post['id'] not in seen:
                    seen.add(post['id'])
                    unique_posts.append(post)
            
            # مرتب‌سازی نزولی بر اساس id (جدیدترین = بزرگترین عدد)
            unique_posts.sort(key=lambda x: int(x['id']), reverse=True)
            self.logger.info(f"🔄 {len(existing_posts)} پست قبلی + {len(new_items)} پست جدید = {len(unique_posts)} پست کل")
            return unique_posts
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در خواندن فایل HTML قبلی: {e}. ادامه با پست‌های جدید.")
            return new_items

    # ═══════════════ بازنویسی متد استخراج با پرش به بالا/پایین و اسکرول جهت‌دار ═══════════════════
    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], any, any]:
        """
        اجرای والد، سپس اگر تعداد پست‌ها کافی نبود، اسکرول جهت‌دار اضافی انجام می‌دهد.
        همچنین در حالت عادی (بدون start_link و بدون resume) به ابتدا یا انتها می‌پرد.
        """
        # ─── لاگ دقیق برای حالت Resume ───
        if self.resume and self._resume_loaded and self.start_link:
            self.logger.info("🔄 ====== حالت ادامه (Resume) ======")
            self.logger.info(f"🔗 رفتن به لینک ذخیره‌شده: {self.start_link}")
            self.logger.info("🧭 اسکرول به سمت بالا (قدیمی‌تر) برای دریافت پست‌های قبل از نقطه‌ی توقف")
            self.logger.info("=" * 50)
        elif self.start_link and not self.resume:
            self.logger.info(f"🔗 رفتن به لینک شروع دستی: {self.start_link}")

        self.logger.info(f"🐞 شروع استخراج با اسکرول جهت‌دار ({self.scroll_direction})...")

        # ۱. اجرای والد (که شامل ورود به کانال و جمع‌آوری اولیه است)
        result = await super()._fetch_posts_from_telegram()
        items, context, page = result

        if not page:
            self.logger.error("❌ صفحه دریافت نشد.")
            return items, context, page

        if not items:
            self.logger.warning("⚠️ والد هیچ پستی نیاورد.")
            return items, context, page

        self.logger.info(f"📥 والد {len(items)} پست تحویل داد.")

        if len(items) >= self.limit:
            await self._capture_full_page_screenshot(page, "final")
            return items, context, page

        # ─── پرش به ابتدا یا انتها در حالت عادی (بدون start_link و resume) ───
        # این کار فقط زمانی انجام می‌شود که والد از حالت عادی استفاده کرده باشد
        # (یعنی start_link نداشته باشیم و resume هم فعال نباشد)
        if not self.start_link and not self.resume:
            if self.scroll_direction == 'up':
                # برای جمع‌آوری قدیمی‌ترها، باید به پایین‌ترین نقطه برویم
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
            else:  # scroll_direction == 'down'
                # برای جمع‌آوری جدیدترها، باید به بالای صفحه برویم (قدیمی‌ترین پست‌ها)
                self.logger.info("⬆️ تلاش برای رفتن به بالای صفحه (قدیمی‌ترین پست‌ها)...")
                await page.evaluate("window.scrollTo(0, 0)")
                await human_sleep(2, 0.3)
                # چند اسکرول اضافی برای اطمینان از رسیدن به ابتدا
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, -2000)")
                    await human_sleep(1, 0.2)
                self.logger.info("   ✅ به بالای صفحه رفتیم.")

        # ─── تنظیم ترتیب پیمایش پست‌ها بر اساس جهت ──────────────────────
        # این بخش توسط خود `scraper.py` مدیریت می‌شود، اما در اینجا نیز برای اطمینان،
        # ما از متد `super()._fetch_posts_from_telegram()` استفاده کرده‌ایم که خودش
        # از `scroller` استفاده می‌کند. بنابراین نیازی به تغییر نیست.

        # ۲. اسکرول جهت‌دار اضافی برای دریافت پست‌های بیشتر
        seen_ids = {item.get('id') for item in items if item.get('id')}
        new_items = []
        no_new_attempts = 0
        max_attempts = 4  # حداکثر ۴ بار اسکرول جهت‌دار

        while len(seen_ids) < self.limit and no_new_attempts < max_attempts:
            # اسکرول هوشمند با جهت
            scrolled = await self._smart_scroll(page, self.scroll_direction, step=1200, max_attempts=3)
            if not scrolled:
                no_new_attempts += 1
                self.logger.info(f"⏳ اسکرول نتیجه‌ای نداشت ({no_new_attempts}/{max_attempts})")
                continue

            # استخراج پست‌های جدید
            current_items = await self._extract_posts_from_page(page)
            added = 0
            for item in current_items:
                item_id = item.get('id')
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    new_items.append(item)
                    added += 1
            if added > 0:
                self.logger.info(f"📈 {added} پست جدید در این مرحله اضافه شد (مجموع: {len(seen_ids)})")
                no_new_attempts = 0  # ریست شمارنده در صورت موفقیت
            else:
                no_new_attempts += 1

            if len(seen_ids) >= self.limit:
                break

        if new_items:
            # اگر جهت down است، پست‌های جدیدتر را در ابتدا قرار بده
            if self.scroll_direction == 'down':
                new_items.reverse()
            items.extend(new_items)
            self.logger.info(f"📈 مجموعاً {len(items)} پست (با {len(new_items)} پست جدید)")

        # ۳. اسکرین‌شات کامل صفحه
        await self._capture_full_page_screenshot(page, "final")
        await self._save_debug_screenshot(page, "debug_final")

        self.logger.info(f"🐞 استخراج نهایی: {len(items)} پست")
        return items, context, page

    async def run(self):
        """اجرای اصلی با ذخیرهٔ خلاصه JSON و ذخیره وضعیت ادامه."""
        await super().run()

        # ========== RESUME: ذخیره وضعیت پس از اتمام ==========
        try:
            if hasattr(self, '_last_items') and self._last_items:
                # پیدا کردن قدیمی‌ترین پست (کوچکترین msg_id)
                oldest_item = min(self._last_items, key=lambda x: int(x.get('id', 0)))
                msg_id = oldest_item.get('id')
                if msg_id:
                    last_post_link = f"https://t.me/{self.channel}/{msg_id}"
                    state = {
                        "last_post_link": last_post_link,
                        "last_msg_id": msg_id,
                        "channel": self.channel,
                        "timestamp": asyncio.get_event_loop().time()
                    }
                    with open(self.resume_state_file, 'w', encoding='utf-8') as f:
                        json.dump(state, f, ensure_ascii=False, indent=2)
                    self.logger.info(f"💾 وضعیت ادامه ذخیره شد: {self.resume_state_file}")
                    self.logger.info(f"🔗 آخرین پست (قدیمی‌ترین) برای ادامه‌ی بعدی: {last_post_link}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره وضعیت ادامه: {e}")

        # ذخیره خلاصه دیباگ (قبلی)
        try:
            debug_json_path = self.base_dir / "debug_summary.json"
            summary = {
                "channel": self.channel,
                "limit": self.limit,
                "start_link": self.start_link,
                "scroll_direction": self.scroll_direction,
                "total_posts": len(self._last_items) if hasattr(self, '_last_items') else 0,
                "debug_mode": True,
                "resume": self.resume,
                "resume_loaded": self._resume_loaded
            }
            with open(debug_json_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            self.logger.info(f"🐞 خلاصه دیباگ ذخیره شد: {debug_json_path}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره خلاصه دیباگ: {e}")

    async def _run_impl(self):
        """Override برای ذخیرهٔ آیتم‌ها و تولید خروجی."""
        if self.start_link:
            self.logger.info(f"🚀 شروع اسکریپر دیباگ با لینک: {self.start_link} (limit={self.limit})")
        else:
            self.logger.info(f"🚀 شروع اسکریپر دیباگ برای @{self.channel} (limit={self.limit})")

        items, context, page = await self._fetch_posts_from_telegram()

        # ========== RESUME: ادغام با پست‌های قبلی از فایل HTML ==========
        if self.resume and self._resume_loaded:
            self.logger.info("🔄 ادغام پست‌های جدید با فایل HTML موجود...")
            items = self._merge_with_existing_posts(items)

        self._last_items = items

        if not items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            if context:
                await context.close()
            return

        self.logger.info(f"📥 {len(items)} پست استخراج شد (حالت دیباگ).")

        try:
            gen = OutputGenerator(
                self.base_dir,
                self.channel,
                items,
                {},
                debug_mode=self.debug_mode
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
        resume = getattr(config, 'resume', False)
        print(f"   حالت ادامه: {'فعال' if resume else 'غیرفعال'}")
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
