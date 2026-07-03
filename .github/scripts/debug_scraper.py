#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ برای Telegram Channel Scraper – نسخه نهایی با رفرش صفحه و ادامه از آخرین پست
– تمام مراحل اسکرپینگ (جستجو، ورود، اسکرول، استخراج) را انجام می‌دهد.
– از همان تنظیمات config.yaml استفاده می‌کند (پشتیبانی از start_link).
– رسانه‌ها را دانلود نمی‌کند (فقط لاگ).
– اسکرین‌شات‌های بیشتری برای تحلیل مراحل ذخیره می‌کند.
– خروجی JSON را برای بررسی داده‌های استخراج‌شده ذخیره می‌کند.
– **نسخه نهایی با قابلیت رفرش صفحه و ادامه از آخرین پست (بدون نیاز به _setup_browser)**
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import load_config
from scraper import TelegramChannelScraper
from output_generator import OutputGenerator


class DebugTelegramChannelScraper(TelegramChannelScraper):
    """
    نسخهٔ دیباگ اسکرپر – با قابلیت رفرش صفحه و ادامه از آخرین پست.
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
    async def _wait_for_new_posts(self, page, previous_count: int, timeout: int = 30000) -> bool:
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
        max_checks = 45
        for i in range(max_checks):
            current_count = await page.locator(selector).count()
            if current_count > previous_count:
                self.logger.info(f"✅ {current_count - previous_count} پست جدید لود شد (مجموع: {current_count})")
                await page.wait_for_timeout(1200)
                return
            await page.wait_for_timeout(700)
        self.logger.warning("⏳ حداکثر چک‌ها انجام شد بدون لود جدید")
        raise asyncio.TimeoutError("No new posts after max checks")

    # ═══════════════════ استخراج کامل پست‌ها با JavaScript ═══════════════════
    async def _extract_posts_from_page(self, page) -> List[Dict]:
        """استخراج کامل پست‌ها از صفحه با استفاده از JavaScript."""
        return await page.evaluate("""
            () => {
                const posts = [];
                const selectors = 'div.message, .bubbles-group > div, [data-msg-id]';
                document.querySelectorAll(selectors).forEach(el => {
                    const msgId = el.getAttribute('data-msg-id') || el.id;
                    if (!msgId) return;
                    
                    const textEl = el.querySelector('.text, .message-text, [data-text]');
                    const text = textEl ? textEl.innerText.trim() : '';
                    
                    const dateEl = el.querySelector('.date, .time, [data-date]');
                    const date = dateEl ? dateEl.innerText.trim() : '';
                    
                    const senderEl = el.querySelector('.sender-name, [data-sender]');
                    const sender = senderEl ? senderEl.innerText.trim() : '';
                    
                    posts.push({
                        id: msgId,
                        text: text,
                        date: date,
                        sender: sender,
                        raw_html: el.outerHTML.substring(0, 500)
                    });
                });
                return posts;
            }
        """)

    # ═══════════════════ یک دور استخراج با تلاش‌های بیشتر ═══════════════════
    async def _single_scrape_attempt(
        self,
        page,
        seen_ids: set,
        max_attempts: int = 10
    ) -> Tuple[List[Dict], int]:
        """یک دور کامل استخراج با اسکرول هوشمند و تلاش‌های بیشتر."""
        self.logger.info(f"🔄 شروع یک دور استخراج (با {max_attempts} تلاش)...")
        new_items = []
        no_new_attempts = 0

        while len(seen_ids) < self.limit and no_new_attempts < max_attempts:
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

            # اسکرول با فواصل بیشتر
            await page.evaluate("window.scrollBy(0, window.innerHeight * 2.5)")
            await page.wait_for_timeout(2000)
            await self._wait_for_new_posts(page, len(seen_ids), timeout=30000)

        self.logger.info(f"🏁 پایان دور: {len(new_items)} پست جدید")
        return new_items, len(new_items)

    # ═══════════════════ متد استخراج با رفرش صفحه و ادامه از آخرین پست ═══════════════════
    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], any, any]:
        """
        استراتژی: والد + یک دور اسکرول، سپس در صورت نیاز رفرش صفحه و ادامه از آخرین پست.
        """
        self.logger.info("🐞 شروع استخراج با رفرش صفحه و ادامه از آخرین پست...")

        # ۱. اجرای والد
        parent_result = await super()._fetch_posts_from_telegram()
        if not parent_result:
            self.logger.error("❌ والد هیچ پستی برنگرداند.")
            return [], None, None

        items, context, page = parent_result
        self.logger.info(f"📥 والد {len(items)} پست تحویل داد.")

        if not page:
            self.logger.error("❌ صفحه دریافت نشد.")
            return items, context, page

        if len(items) >= self.limit:
            self.logger.info(f"✅ تعداد کافی پست از قبل وجود دارد.")
            return items, context, page

        seen_ids = {item.get('id') for item in items if item.get('id')}
        last_known_id = items[-1].get('id') if items else None

        await self._save_debug_screenshot(page, "initial_load")

        # ۲. دور اول اسکرول
        new_items, added = await self._single_scrape_attempt(page, seen_ids, max_attempts=10)
        if new_items:
            items.extend(new_items)
            last_known_id = new_items[-1].get('id') or last_known_id

        if len(items) >= self.limit:
            await self._save_debug_screenshot(page, "final_debug")
            return items, context, page

        # ۳. رفرش صفحه و ادامه از آخرین پست
        self.logger.info("🔄 رفرش صفحه و ادامه از آخرین پست...")
        try:
            # رفرش صفحه با صبر بیشتر
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)  # ۵ ثانیه صبر برای بارگذاری کامل

            # اسکرول به آخرین پست شناخته‌شده
            if last_known_id:
                self.logger.info(f"🔍 اسکرول به پست با شناسه {last_known_id}")
                await page.evaluate(f"""
                    () => {{
                        const post = document.querySelector('[data-msg-id="{last_known_id}"]');
                        if (post) {{
                            post.scrollIntoView({{ behavior: "smooth", block: "center" }});
                        }}
                    }}
                """)
                await page.wait_for_timeout(3000)
                self.logger.info("✅ اسکرول به آخرین پست انجام شد")
                await self._save_debug_screenshot(page, "after_scroll_to_last")
            else:
                self.logger.warning("⚠️ هیچ شناسه‌ای برای اسکرول وجود ندارد.")

            # ۴. دور دوم اسکرول بعد از رفرش (با ۱۰ تلاش)
            self.logger.info("🔄 شروع دور دوم استخراج بعد از رفرش...")
            new_items_2, added_2 = await self._single_scrape_attempt(page, seen_ids, max_attempts=10)
            if new_items_2:
                items.extend(new_items_2)
                self.logger.info(f"📈 در دور دوم {added_2} پست جدید اضافه شد (مجموع: {len(items)})")

        except Exception as e:
            self.logger.error(f"❌ خطا در رفرش صفحه: {e}", exc_info=True)

        await self._save_debug_screenshot(page, "final_debug")
        self.logger.info(f"🐞 استخراج نهایی: {len(items)} پست")
        return items, context, page

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
    print("🐞 Telegram Channel Scraper - حالت دیباگ (رفرش + ادامه)")
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
