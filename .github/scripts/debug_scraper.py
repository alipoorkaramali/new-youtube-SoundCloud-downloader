#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ با تاخیر بیشتر برای بارگذاری کامل پست‌ها
"""

import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import load_config
from scraper import TelegramChannelScraper
from output_generator import OutputGenerator


class DebugTelegramChannelScraper(TelegramChannelScraper):
    def __init__(self, config, debug_screenshots: bool = True):
        config.debug_mode = True
        super().__init__(config)
        self.debug_screenshots = debug_screenshots
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info("🐞 حالت دیباگ فعال – دانلود رسانه غیرفعال است.")
        self._last_items = []

    async def _download_media(self, items, page, context):
        return {}, 0

    async def _save_debug_screenshot(self, page, name: str, full_page=True):
        if not self.debug_screenshots:
            return
        try:
            await self._screenshot(page, name, full_page=full_page)
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در اسکرین‌شات: {e}")

    async def _setup_browser_with_ci_args(self):
        from playwright.async_api import async_playwright
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(90000)  # افزایش timeout کلی به ۹۰ ثانیه
        return page, context, playwright

    async def _setup_browser(self):
        page, context, self._playwright = await self._setup_browser_with_ci_args()
        return page, context

    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], any, any]:
        self.logger.info("🐞 شروع استخراج با تاخیر بیشتر...")
        page = None
        context = None
        try:
            page, context = await self._setup_browser()

            url = self.start_link if self.start_link else f"https://t.me/s/{self.channel}"
            self.logger.info(f"🌐 رفتن به {url}")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_selector("body", timeout=15000)
            await self._save_debug_screenshot(page, "initial_page")

            try:
                await page.wait_for_selector(".tgme_widget_message", timeout=20000)
            except:
                self.logger.warning("⚠️ پستی یافت نشد، ذخیره‌ی HTML")
                html = await page.content()
                (self.base_dir / "debug_page_content.html").write_text(html, encoding="utf-8")
                await self._save_debug_screenshot(page, "no_posts")
                return [], context, page

            collected_ids = set()
            all_items = []
            no_new_count = 0
            scroll_attempts = 0
            max_scrolls = 300  # افزایش سقف اسکرول

            while len(all_items) < self.limit and scroll_attempts < max_scrolls:
                current_posts = await self._collect_current_posts(page)
                new_posts = [p for p in current_posts if p['id'] not in collected_ids]

                if new_posts:
                    all_items.extend(new_posts)
                    collected_ids.update(p['id'] for p in new_posts)
                    self.logger.info(f"🔍 جمعاً {len(all_items)} پست (جدید: {len(new_posts)})")
                    no_new_count = 0
                else:
                    no_new_count += 1
                    self.logger.debug(f"⚠️ تلاش بی‌نتیجه {no_new_count}")
                    if no_new_count >= 5:  # افزایش به ۵ بار
                        self.logger.info("🚫 پنج بار پست جدید نیامد، انتهای کانال.")
                        break

                if len(all_items) >= self.limit:
                    break

                # ─── اسکرول با تاخیر بیشتر ──────────────────
                await page.keyboard.press("PageDown")
                await asyncio.sleep(1.0)  # افزایش مکث
                await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                await asyncio.sleep(3.0)  # افزایش زمان انتظار اصلی

                # منتظر بارگذاری آخرین پست با timeout بیشتر
                try:
                    await page.wait_for_selector(
                        ".tgme_widget_message:last-child",
                        timeout=10000,  # افزایش به ۱۰ ثانیه
                        state="visible"
                    )
                except:
                    pass

                scroll_attempts += 1

                if scroll_attempts % 5 == 0:
                    await self._save_debug_screenshot(page, f"scroll_{scroll_attempts}")

            final_items = all_items[:self.limit]
            self.logger.info(f"✅ نهایی: {len(final_items)} پست (هدف: {self.limit})")
            await self._save_debug_screenshot(page, "final")
            return final_items, context, page

        except Exception as e:
            self.logger.error(f"❌ خطا: {e}", exc_info=True)
            if page:
                await self._save_debug_screenshot(page, "error")
                try:
                    html = await page.content()
                    (self.base_dir / "debug_error_page.html").write_text(html, encoding="utf-8")
                except:
                    pass
            return [], context, page

    async def _collect_current_posts(self, page):
        try:
            return await page.evaluate('''
                () => {
                    const items = document.querySelectorAll('.tgme_widget_message');
                    const result = [];
                    items.forEach(el => {
                        let id = null;
                        if (el.dataset?.post) id = parseInt(el.dataset.post, 10);
                        if (!id) {
                            const link = el.querySelector('a.tgme_widget_message_date');
                            if (link) {
                                const match = link.href.match(/\\/(\\d+)$/);
                                if (match) id = parseInt(match[1], 10);
                            }
                        }
                        if (!id) id = Math.random().toString(36);
                        result.push({ id, text: el.innerText || '' });
                    });
                    return result;
                }
            ''')
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در جمع‌آوری: {e}")
            return []

    async def run(self):
        await super().run()
        try:
            summary = {
                "channel": self.channel,
                "limit": self.limit,
                "start_link": self.start_link,
                "total_posts": len(self._last_items),
                "debug_mode": True
            }
            (self.base_dir / "debug_summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره خلاصه: {e}")

    async def _run_impl(self):
        items, context, page = await self._fetch_posts_from_telegram()
        self._last_items = items
        if not items:
            self.logger.warning("⚠️ هیچ پستی دریافت نشد.")
            if context:
                await context.close()
            return

        gen = OutputGenerator(self.base_dir, self.channel, items, {}, debug_mode=self.debug_mode)
        gen.run_all()
        if context:
            await context.close()
        self.logger.info("✅ پایان دیباگ.")


async def main():
    print("🐞 Telegram Channel Scraper - حالت دیباگ با تاخیر بیشتر")
    config = load_config("config/config.yaml")
    scraper = DebugTelegramChannelScraper(config, debug_screenshots=True)
    try:
        await scraper.run()
        if not scraper._last_items:
            print("❌ هیچ پستی استخراج نشد.")
            sys.exit(1)
        print(f"✅ موفق. خروجی: {scraper.base_dir}")
    except Exception as e:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
