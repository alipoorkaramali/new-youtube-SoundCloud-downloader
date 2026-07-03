#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ برای Telegram Channel Scraper – نسخه با قابلیت انتخاب جهت اسکرول
– کاربر می‌تواند تعیین کند که از پست خاص به بالا (قدیمی‌تر) برود یا پایین (جدیدتر).
– تمام مراحل اسکرپینگ (جستجو، ورود، اسکرول، استخراج) را انجام می‌دهد.
– رسانه‌ها را دانلود نمی‌کند (فقط لاگ).
– اسکرین‌شات‌های کامل صفحه برای تحلیل بهتر ذخیره می‌کند.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import load_config
from scraper import TelegramChannelScraper
from output_generator import OutputGenerator


class DebugTelegramChannelScraper(TelegramChannelScraper):
    """
    نسخه‌ی دیباگ اسکرپر با قابلیت انتخاب جهت اسکرول.
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
        if not self.debug_screenshots:
            return
        try:
            self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
            await self._screenshot(page, name, full_page=True)
            self.logger.debug(f"🐞 اسکرین‌شات دیباگ ذخیره شد: {name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات دیباگ: {e}")

    # ═══════════════ صبر هوشمند با بررسی ارتفاع صفحه ═══════════════
    async def _wait_for_height_change(self, page, old_height: int, timeout: int = 20000) -> bool:
        """منتظر می‌ماند تا ارتفاع صفحه افزایش یا کاهش یابد (نشان‌دهنده لود محتوای جدید)."""
        self.logger.info(f"🐞 منتظر تغییر ارتفاع صفحه (از {old_height}px)...")
        try:
            await asyncio.wait_for(
                self._wait_until_height_changes(page, old_height),
                timeout=timeout / 1000
            )
            return True
        except asyncio.TimeoutError:
            self.logger.warning(f"⚠️ timeout: ارتفاع صفحه تغییر نکرد.")
            return False
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در انتظار تغییر ارتفاع: {e}")
            return False

    async def _wait_until_height_changes(self, page, old_height: int):
        """حلقه‌ای که تا تغییر ارتفاع صفحه چک می‌کند (افزایش یا کاهش)."""
        while True:
            new_height = await page.evaluate("document.documentElement.scrollHeight")
            if new_height != old_height:
                self.logger.info(f"✅ ارتفاع از {old_height} به {new_height} تغییر یافت.")
                await asyncio.sleep(1)
                return
            await asyncio.sleep(0.7)

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

    # ═══════════════ اسکرول هوشمند با جهت قابل تنظیم ═══════════════════
    async def _smart_scroll(self, page, seen_ids: set, direction: str = 'up') -> List[Dict]:
        """
        اسکرول به سمت بالا یا پایین با سه پله.
        - direction: 'up' (قدیمی‌تر) یا 'down' (جدیدتر)
        """
        self.logger.info(f"🔄 شروع اسکرول هوشمند به سمت {'بالا (قدیمی‌تر)' if direction == 'up' else 'پایین (جدیدتر)'}...")
        new_items = []

        # مقادیر اسکرول بر اساس جهت
        if direction == 'up':
            scroll_steps = [-3000, -4000, -5000]  # منفی = بالا
        else:  # down
            scroll_steps = [3000, 4000, 5000]     # مثبت = پایین

        for step in scroll_steps:
            if len(seen_ids) >= self.limit:
                break

            self.logger.info(f"   📍 اسکرول {step}px")
            old_height = await page.evaluate("document.documentElement.scrollHeight")

            # اسکرول
            await page.evaluate(f"window.scrollBy(0, {step})")
            await asyncio.sleep(1.5)

            # منتظر تغییر ارتفاع
            if await self._wait_for_height_change(page, old_height, timeout=20000):
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
                    self.logger.info(f"✅ {added} پست جدید در این مرحله اضافه شد.")
                else:
                    self.logger.info(f"⚠️ ارتفاع تغییر کرد اما پست جدیدی پیدا نشد.")
            else:
                self.logger.info(f"⏳ ارتفاع تغییر نکرد، اسکرول بعدی...")

        return new_items

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

    # ═══════════════ بازنویسی متد استخراج با اسکرول جهت‌دار ═══════════════════
    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], any, any]:
        """
        اجرای والد، سپس اسکرول جهت‌دار برای دریافت پست‌های بیشتر.
        """
        self.logger.info(f"🐞 شروع استخراج با اسکرول جهت‌دار ({self.scroll_direction})...")

        # ۱. اجرای والد
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

        seen_ids = {item.get('id') for item in items if item.get('id')}

        # ۲. اسکرول جهت‌دار
        new_items = await self._smart_scroll(page, seen_ids, self.scroll_direction)
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
    print("🐞 Telegram Channel Scraper - حالت دیباگ (با جهت‌یابی)")
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
