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
from scraper import TelegramChannelScraper
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

        # جهت اسکرول را از config بگیریم
        self.scroll_direction = getattr(config, 'scroll_direction', 'up').lower()
        if self.scroll_direction not in ['up', 'down']:
            self.logger.warning(f"⚠️ مقدار نامعتبر برای scroll_direction: {self.scroll_direction}. استفاده از 'up'.")
            self.scroll_direction = 'up'

        self.logger.info("🐞 حالت دیباگ فعال است – دانلود رسانه انجام نمی‌شود.")
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
        """ذخیره اسکرین‌شات دیباگ (فقط در صورت فعال بودن)."""
        if not self.debug_screenshots or not self.save_screenshots:
            return
        try:
            self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
            await self._screenshot(page, name, full_page=True)
            self.logger.debug(f"🐞 اسکرین‌شات دیباگ ذخیره شد: {name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات دیباگ: {e}")

    async def _capture_full_page_screenshot(self, page, name: str = "full_page"):
        """گرفتن اسکرین‌شات کامل از کل صفحه (فقط در صورت فعال بودن)."""
        if not self.save_screenshots:
            return
        try:
            safe_channel = self._sanitize_filename(self.channel)
            path = self.screenshots_dir / f"{safe_channel}_{name}.png"
            await page.screenshot(path=path, full_page=True)
            self.logger.info(f"📸 اسکرین‌شات کامل صفحه ذخیره شد: {path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در اسکرین‌شات کامل: {e}")

    async def _fetch_posts_from_telegram(self, existing_seen_ids: set = None, keep_browser_open: bool = False,
                                         existing_context: any = None, existing_page: any = None,
                                         limit: int = None) -> tuple[List[Dict], any, any]:
        """
        استخراج پست‌ها با فراخوانی والد و سپس اسکرین‌شات نهایی.
        """
        self.logger.info(f"🐞 شروع استخراج با جهت: {self.scroll_direction} | start_link={bool(self.start_link)}")

        # فراخوانی متد والد (scraper اصلی)
        items, context, page = await super()._fetch_posts_from_telegram(
            existing_seen_ids=existing_seen_ids,
            keep_browser_open=True,  # همیشه باز نگه دار برای دیباگ
            existing_context=existing_context,
            existing_page=existing_page,
            limit=limit
        )

        if not items or not page:
            self.logger.warning("⚠️ والد هیچ پستی تحویل نداد یا صفحه موجود نیست.")
            return items, context, page

        self.logger.info(f"📥 والد {len(items)} پست تحویل داد.")

        # اسکرین‌شات نهایی
        if self.save_screenshots:
            await self._capture_full_page_screenshot(page, "final")
            await self._save_debug_screenshot(page, "debug_final")

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
        """اجرای دیباگ با فراخوانی والد."""
        if self.start_link:
            self.logger.info(f"🚀 شروع اسکریپر دیباگ با لینک: {self.start_link} (limit={self.limit})")
        else:
            self.logger.info(f"🚀 شروع اسکریپر دیباگ برای @{self.channel} (limit={self.limit})")

        # فراخوانی مستقیم متد fetch والد
        items, context, page = await self._fetch_posts_from_telegram(
            existing_seen_ids=set(),
            keep_browser_open=True,
            limit=self.limit
        )

        self._last_items = items or []

        if not items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            if context:
                await context.close()
            return

        self.logger.info(f"📥 {len(items)} پست استخراج شد (حالت دیباگ).")

        # تولید خروجی
        try:
            append_mode = getattr(self, 'resume', False) and getattr(self, '_resume_loaded', False)
            gen = OutputGenerator(
                self.base_dir,
                self.channel,
                items,
                {},  # در دیباگ رسانه‌ای دانلود نمی‌شود
                debug_mode=True,
                append_mode=append_mode
            )
            gen.run_all()
            self.logger.info(f"🐞 فایل‌های خروجی دیباگ در: {self.base_dir}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در تولید خروجی: {e}")

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
