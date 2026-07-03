#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ برای Telegram Channel Scraper
– تمام مراحل اسکرپینگ (جستجو، ورود، اسکرول، استخراج) را انجام می‌دهد.
– از همان تنظیمات config.yaml استفاده می‌کند (پشتیبانی از start_link).
– رسانه‌ها را دانلود نمی‌کند (فقط لاگ).
– اسکرین‌شات‌های بیشتری برای تحلیل مراحل ذخیره می‌کند.
– خروجی JSON را برای بررسی داده‌های استخراج‌شده ذخیره می‌کند.
– بهبود یافته با صبر هوشمند و حلقه اسکرول مقاوم.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Dict

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
    async def _wait_for_new_posts(self, page, previous_count: int, timeout: int = 15000) -> bool:
        """
        صبر هوشمند تا پست‌های جدید لود شوند.
        - اگر تعداد پست‌ها افزایش پیدا کرد → True
        - اگر بعد از timeout تغییری نکرد → False
        """
        self.logger.info(f"🐞 صبر برای لود پست‌های جدید... (قبلاً {previous_count} پست)")

        # انتخابگر دقیق‌تر برای پیام‌های تلگرام وب
        selector = "div.message, .bubbles-group, [data-msg-id], .history > div"

        try:
            # استفاده از asyncio.wait_for برای سازگاری با نسخه‌های قدیمی‌تر پایتون
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
        while True:
            current_count = await page.locator(selector).count()
            if current_count > previous_count:
                self.logger.info(f"✅ {current_count - previous_count} پست جدید لود شد (مجموع: {current_count})")
                await page.wait_for_timeout(800)  # صبر کوتاه برای رندر نهایی
                return
            await page.wait_for_timeout(600)

    # ═══════════════════ بازنویسی متد استخراج با حلقه اسکرول هوشمند ═══════════════════
    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], any, any]:
        """
        استخراج پست‌ها با حلقه اسکرول هوشمند که از _wait_for_new_posts استفاده می‌کند.
        از متدهای _setup_browser و _navigate والد استفاده می‌کند (بدون فراخوانی super()._fetch_posts...).
        """
        self.logger.info("🐞 شروع استخراج پست‌ها با حلقه اسکرول هوشمند...")

        browser = None
        context = None
        page = None
        items = []

        try:
            # ========== راه‌اندازی مرورگر و صفحه ==========
            browser, context, page = await self._setup_browser()
            if not page:
                raise Exception("صفحه ایجاد نشد")

            # ========== هدایت به کانال ==========
            await self._navigate(page)

            # ========== اسکرین‌شات اولیه ==========
            await self._save_debug_screenshot(page, "initial_load")

            # ========== جمع‌آوری پست‌ها با حلقه اسکرول ==========
            no_new_attempts = 0
            max_no_new_attempts = 4  # بعد از ۴ بار عدم تغییر، متوقف می‌شویم

            while len(items) < self.limit:
                # استخراج تمام پست‌های لود شده (فرض می‌کنیم _extract_items همه را برمی‌گرداند)
                current_items = await self._extract_items(page)
                if current_items:
                    # اگر لیست کامل برگردانده شود، می‌توانیم جایگزین کنیم
                    items = current_items
                    self.logger.info(f"📥 تعداد پست‌های استخراج‌شده: {len(items)}")

                # اگر به حد نصاب رسیدیم، خارج شو
                if len(items) >= self.limit:
                    break

                # اسکرول به پایین
                await page.evaluate("window.scrollBy(0, window.innerHeight * 1.8)")
                await page.wait_for_timeout(700)

                # صبر هوشمند برای لود شدن پست‌های جدید
                if await self._wait_for_new_posts(page, len(items), timeout=14000):
                    no_new_attempts = 0  # ریست شمارنده
                    await self._save_debug_screenshot(page, f"after_load_{len(items)}")
                else:
                    no_new_attempts += 1
                    self.logger.info(f"🔄 تلاش ناموفق {no_new_attempts}/{max_no_new_attempts}")
                    if no_new_attempts >= max_no_new_attempts:
                        self.logger.info("🚫 چند بار تلاش بی‌نتیجه – احتمالاً به انتهای کانال رسیدیم.")
                        break
                    await page.wait_for_timeout(2500)  # صبر بیشتر قبل از تلاش مجدد

            # ========== اسکرین‌شات نهایی ==========
            await self._save_debug_screenshot(page, "final_debug")
            self.logger.info(f"🐞 استخراج نهایی: {len(items)} پست")

            return items, context, page

        except Exception as e:
            self.logger.error(f"❌ خطا در استخراج دیباگ: {e}", exc_info=True)
            if page:
                await self._save_debug_screenshot(page, "error_debug")
            # بستن context در صورت وجود
            if context:
                await context.close()
            return [], context, page

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
        """Override برای ذخیرهٔ آیتم‌ها در متغیر کلاس و استفاده از run_all در OutputGenerator."""
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
                {},  # media_map خالی
                debug_mode=self.debug_mode
            )
            gen.run_all()
            self.logger.info(f"🐞 فایل‌های خروجی دیباگ در: {self.base_dir}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در تولید خروجی دیباگ: {e}", exc_info=True)

        if context:
            await context.close()

        self.logger.info("✅ پایان موفقیت‌آمیز دیباگ.")


async def main():
    print("🐞 ========================================")
    print("🐞 Telegram Channel Scraper - حالت دیباگ")
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
