#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ برای Telegram Channel Scraper – نسخه نهایی اصلاح‌شده
– تمام مراحل اسکرپینگ (جستجو، ورود، اسکرول، استخراج) را انجام می‌دهد.
– از همان تنظیمات config.yaml استفاده می‌کند (پشتیبانی از start_link).
– رسانه‌ها را دانلود نمی‌کند (فقط لاگ).
– اسکرین‌شات‌های بیشتری برای تحلیل مراحل ذخیره می‌کند.
– خروجی JSON را برای بررسی داده‌های استخراج‌شده ذخیره می‌کند.
– **نسخه نهایی با قابلیت Resume با لینک مستقیم به آخرین پست + استخراج کامل داده‌ها**
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import load_config
from scraper import TelegramChannelScraper
from output_generator import OutputGenerator


class DebugTelegramChannelScraper(TelegramChannelScraper):
    """
    نسخهٔ دیباگ اسکرپر – تمام مراحل اسکرپینگ را انجام می‌دهد اما رسانه‌ها را دانلود نمی‌کند.
    همچنین اسکرین‌شات‌های بیشتری برای تحلیل مراحل ذخیره می‌کند.
    """

    def __init__(self, config, debug_screenshots: bool = True):
        config.debug_mode = True
        super().__init__(config)
        self.debug_screenshots = debug_screenshots
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info("🐞 حالت دیباگ فعال است – دانلود رسانه انجام نمی‌شود.")
        self.logger.info(f"🐞 پوشه اسکرین‌شات‌های دیباگ: {self.debug_screenshots_dir}")
        self._last_items = []

    async def _download_media(self, items: List[Dict], page, context) -> tuple[dict, int]:
        """در حالت دیباگ، دانلود رسانه غیرفعال است."""
        self.logger.info("🐞 حالت دیباگ: دانلود رسانه غیرفعال است.")
        media_map = {}
        for item in items:
            msg_id = item['id']
            self.logger.info(f"   🖼️ [دیباگ] پست {msg_id}: دانلود رسانه انجام نشد (حالت دیباگ).")
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

    # ═══════════════════ صبر هوشمند برای لود پست‌های جدید ═══════════════════
    async def _wait_for_new_posts(self, page, previous_count: int, timeout: int = 28000) -> bool:
        """صبر هوشمند تا پست‌های جدید لود شوند."""
        self.logger.info(f"🐞 صبر برای لود پست‌های جدید... (قبلاً {previous_count} پست)")
        selector = "div.message, .bubbles-group, [data-msg-id], .history > div"

        try:
            await asyncio.wait_for(
                self._wait_until_count_increases(page, selector, previous_count),
                timeout=timeout / 1000
            )
            return True
        except asyncio.TimeoutError:
            self.logger.warning(f"⚠️ timeout بعد از {timeout}ms — پست جدیدی لود نشد")
            return False
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در wait_for_new_posts: {e}")
            return False

    async def _wait_until_count_increases(self, page, selector, previous_count):
        """حلقه‌ای که تا افزایش تعداد پست‌ها صبر می‌کند."""
        max_checks = 40
        for i in range(max_checks):
            current_count = await page.locator(selector).count()
            if current_count > previous_count:
                self.logger.info(f"✅ {current_count - previous_count} پست جدید لود شد (مجموع: {current_count})")
                await page.wait_for_timeout(1000)
                return
            await page.wait_for_timeout(700)
        self.logger.warning("⏳ حداکثر چک‌ها انجام شد بدون لود جدید")
        raise asyncio.TimeoutError("No new posts after max checks")

    # ═══════════════════ استخراج کامل پست‌ها با JavaScript ═══════════════════
    async def _extract_posts_from_page(self, page) -> List[Dict]:
        """
        استخراج کامل پست‌ها از صفحه با استفاده از JavaScript.
        برمی‌گرداند: لیستی از دیکشنری‌های شامل id, text, date, sender و ...
        """
        return await page.evaluate("""
            () => {
                const posts = [];
                const selectors = 'div.message, .bubbles-group > div, [data-msg-id]';
                document.querySelectorAll(selectors).forEach(el => {
                    const msgId = el.getAttribute('data-msg-id') || el.id;
                    if (!msgId) return;
                    
                    // پیدا کردن متن پیام
                    const textEl = el.querySelector('.text, .message-text, [data-text]');
                    const text = textEl ? textEl.innerText.trim() : '';
                    
                    // پیدا کردن تاریخ/زمان
                    const dateEl = el.querySelector('.date, .time, [data-date]');
                    const date = dateEl ? dateEl.innerText.trim() : '';
                    
                    // پیدا کردن فرستنده (برای گروه‌ها)
                    const senderEl = el.querySelector('.sender-name, [data-sender]');
                    const sender = senderEl ? senderEl.innerText.trim() : '';
                    
                    posts.push({
                        id: msgId,
                        text: text,
                        date: date,
                        sender: sender,
                        raw_html: el.outerHTML.substring(0, 500)  // برای دیباگ
                    });
                });
                return posts;
            }
        """)

    # ═══════════════════ یک دور استخراج (Single Scrape Attempt) ═══════════════════
    async def _single_scrape_attempt(
        self,
        page,
        seen_ids: set,
        max_attempts: int = 6
    ) -> Tuple[List[Dict], int]:
        """
        یک دور کامل استخراج با اسکرول هوشمند.
        برمی‌گرداند: (لیست آیتم‌های جدید, تعداد آیتم‌های جدید)
        """
        self.logger.info("🔄 شروع یک دور استخراج...")
        new_items = []
        no_new_attempts = 0

        while len(seen_ids) < self.limit and no_new_attempts < max_attempts:
            # استخراج پست‌های فعلی
            current_items = await self._extract_posts_from_page(page)
            added_this_round = 0

            for item in current_items:
                item_id = item.get('id')
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    new_items.append(item)
                    added_this_round += 1

            if added_this_round > 0:
                self.logger.info(f"📈 {added_this_round} پست جدید (مجموع: {len(seen_ids)})")
                no_new_attempts = 0
            else:
                no_new_attempts += 1
                self.logger.info(f"⏳ پست جدیدی اضافه نشد ({no_new_attempts}/{max_attempts})")

            if len(seen_ids) >= self.limit or no_new_attempts >= max_attempts:
                break

            # اسکرول و صبر
            await page.evaluate("window.scrollBy(0, window.innerHeight * 2.5)")
            await page.wait_for_timeout(1800)
            await self._wait_for_new_posts(page, len(seen_ids), timeout=28000)

        self.logger.info(f"🏁 پایان دور: {len(new_items)} پست جدید")
        return new_items, len(new_items)

    # ═══════════════════ ساخت لینک مستقیم به یک پیام (نسخه قوی‌تر) ═══════════════════
    def _build_direct_link(self, channel: str, msg_id: str) -> str:
        """
        ساخت لینک مستقیم به یک پیام در تلگرام وب.
        - اگر msg_id عددی باشد، لینک با شناسه پیام ساخته می‌شود.
        - در غیر این صورت، فقط به کانال هدایت می‌شود.
        """
        if not msg_id or not msg_id.isdigit():
            # اگر msg_id معتبر نبود، فقط به کانال برو
            clean_channel = channel.lstrip('@')
            return f"https://web.telegram.org/k/#@{clean_channel}"

        clean_channel = channel.lstrip('@')
        return f"https://web.telegram.org/k/#@{clean_channel}/{msg_id}"

    # ═══════════════════ بازنویسی متد استخراج با حلقه Resume ═══════════════════
    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], any, any]:
        """
        استراتژی: والد + حلقه Resume با لینک مستقیم به آخرین پست.
        """
        self.logger.info("🐞 شروع استخراج با حلقه Resume...")

        all_items = []
        seen_ids = set()
        last_known_id = None
        max_retries = 2          # برای تست اولیه
        retry_count = 0
        context = None
        page = None

        try:
            # ۱. اجرای والد
            parent_result = await super()._fetch_posts_from_telegram()
            if parent_result:
                items, context, page = parent_result
                self.logger.info(f"📥 والد {len(items)} پست تحویل داد.")

                for item in items:
                    item_id = item.get('id')
                    if item_id:
                        seen_ids.add(item_id)
                        all_items.append(item)
                        last_known_id = item_id

            if not page:
                self.logger.error("❌ صفحه دریافت نشد.")
                return [], None, None

            if len(all_items) >= self.limit:
                await self._save_debug_screenshot(page, "final_from_parent")
                return all_items, context, page

            await self._save_debug_screenshot(page, "initial_load")

            # ۲. حلقه Resume
            while len(all_items) < self.limit and retry_count < max_retries:
                self.logger.info(f"🔄 دور {retry_count+1} (مجموع: {len(all_items)} پست)")

                new_items, added = await self._single_scrape_attempt(page, seen_ids)

                if new_items:
                    all_items.extend(new_items)
                    if new_items:
                        last_known_id = new_items[-1].get('id') or last_known_id

                if len(all_items) >= self.limit:
                    break

                retry_count += 1
                if retry_count >= max_retries:
                    break

                # ====== ریستارت و استفاده از لینک مستقیم ======
                self.logger.info("🔄 ریستارت صفحه و رفتن به آخرین پست...")

                # بستن context قبلی
                if context:
                    await context.close()
                    await asyncio.sleep(2)  # کمی صبر برای آزاد شدن منابع
                    context = None
                    page = None

                # ایجاد مرورگر جدید با متد والد
                browser, new_context, new_page = await self._setup_browser()
                if not new_page:
                    self.logger.error("❌ ایجاد صفحه جدید ناموفق.")
                    break
                context = new_context
                page = new_page

                # رفتن به لینک مستقیم آخرین پست
                if last_known_id:
                    direct_link = self._build_direct_link(self.channel, last_known_id)
                    self.logger.info(f"🔗 لینک مستقیم: {direct_link}")
                    try:
                        await page.goto(direct_link, wait_until="domcontentloaded")
                        await page.wait_for_timeout(4000)  # صبر برای بارگذاری کامل
                    except Exception as e:
                        self.logger.warning(f"⚠️ خطا در رفتن به لینک مستقیم: {e}")
                        # Fallback: به کانال برو
                        await self._navigate(page)
                else:
                    await self._navigate(page)

                await self._save_debug_screenshot(page, f"resume_{retry_count}")

            await self._save_debug_screenshot(page, "final_debug")
            self.logger.info(f"🐞 استخراج نهایی: {len(all_items)} پست")
            return all_items, context, page

        except Exception as e:
            self.logger.error(f"❌ خطا: {e}", exc_info=True)
            if page:
                await self._save_debug_screenshot(page, "error_debug")
            return all_items, context, page

    async def run(self):
        """اجرای اصلی با ذخیرهٔ خروجی JSON اضافی برای دیباگ."""
        await super().run()

        try:
            debug_json_path = self.base_dir / "debug_summary.json"
            summary = {
                "channel": self.channel,
                "limit": self.limit,
                "start_link": self.start_link,
                "total_posts": len(self._last_items) if hasattr(self, '_last_items') else 0,
                "debug_mode": True
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
    print("🐞 Telegram Channel Scraper - حالت دیباگ (Resume)")
    print("🐞 ========================================")

    config_path = "config/config.yaml"
    try:
        config = load_config(config_path)
        print(f"✅ تنظیمات از {config_path} بارگذاری شد.")
        print(f"   کانال: {config.channel}")
        print(f"   limit: {config.limit}")
        if config.start_link:
            print(f"   start_link: {config.start_link}")
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
