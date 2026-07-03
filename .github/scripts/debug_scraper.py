#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ پیشرفته برای Telegram Channel Scraper
- حل مشکل شمارش دقیق پست‌ها تا limit
- سازگار با محیط CI (بدون نمایشگر)
- لاگ‌های کامل و ذخیره‌ی اسکرین‌شات در صورت خطا
"""

import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import List, Dict

# اضافه کردن مسیر پروژه
sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import load_config
from scraper import TelegramChannelScraper
from output_generator import OutputGenerator


class DebugTelegramChannelScraper(TelegramChannelScraper):
    """
    نسخه‌ی دیباگ با قابلیت‌های زیر:
    - اسکرول هوشمند تا رسیدن به limit یا انتهای کانال
    - جلوگیری از پست‌های تکراری با شناسه یکتا
    - ذخیره‌ی اسکرین‌شات در هر مرحله و در صورت خطا
    - لاگ دقیق تعداد پست‌ها در هر اسکرول
    - سازگاری با محیط‌های headless (CI)
    """

    def __init__(self, config, debug_screenshots: bool = True):
        # فعال‌سازی حالت دیباگ در config
        config.debug_mode = True
        super().__init__(config)
        self.debug_screenshots = debug_screenshots
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info("🐞 حالت دیباگ فعال – دانلود رسانه غیرفعال است.")
        self.logger.info(f"🐞 پوشه اسکرین‌شات: {self.debug_screenshots_dir}")
        self._last_items = []

    async def _download_media(self, items: List[Dict], page, context) -> tuple[dict, int]:
        """در حالت دیباگ، دانلود رسانه انجام نمی‌شود."""
        self.logger.info("🐞 دانلود رسانه در حالت دیباگ غیرفعال است.")
        return {}, 0

    async def _save_debug_screenshot(self, page, name: str, full_page=True):
        """ذخیره‌ی اسکرین‌شات با نام مشخص."""
        if not self.debug_screenshots:
            return
        try:
            await self._screenshot(page, name, full_page=full_page)
            self.logger.debug(f"📸 اسکرین‌شات دیباگ: {name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات: {e}")

    async def _setup_browser_with_ci_args(self):
        """
        راه‌اندازی مرورگر با آرگومان‌های مناسب برای محیط‌های CI
        (بدون sandbox، غیرفعال‌سازی GPU، و ...)
        """
        from playwright.async_api import async_playwright
        self.logger.info("🚀 راه‌اندازی مرورگر با تنظیمات CI...")
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--disable-gpu",
                "--window-size=1920,1080"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(60000)  # 60 ثانیه
        return page, context, playwright

    # اورراید متد _setup_browser برای استفاده از تنظیمات CI
    async def _setup_browser(self):
        page, context, self._playwright = await self._setup_browser_with_ci_args()
        return page, context

    # ─── متد اصلی استخراج با منطق دقیق ──────────────────────

    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], any, any]:
        self.logger.info("🐞 شروع استخراج پست‌ها با حلقه‌ی دقیق تا limit...")
        page = None
        context = None
        playwright = None
        try:
            page, context = await self._setup_browser()
            playwright = self._playwright

            # هدایت به کانال
            await self._navigate_to_channel(page)
            await self._handle_login(page)

            # ذخیره اسکرین‌شات اولیه
            await self._save_debug_screenshot(page, "initial_page")

            # ─── بررسی وجود پست‌ها ──────────────────────────
            # منتظر بارگذاری حداقل یک پست می‌مانیم
            try:
                await page.wait_for_selector(".tgme_widget_message", timeout=15000)
            except Exception:
                self.logger.warning("⚠️ هیچ پستی با سلکتور پیش‌فرض پیدا نشد. تلاش با سلکتور جایگزین...")
                # سلکتور جایگزین: ممکن است ساختار صفحه متفاوت باشد
                try:
                    await page.wait_for_selector(".tgme_widget_message_wrap", timeout=5000)
                except:
                    # اگر هیچ پستی نبود، محتوای صفحه را ذخیره می‌کنیم
                    content = await page.content()
                    debug_html = self.base_dir / "debug_page_content.html"
                    with open(debug_html, "w", encoding="utf-8") as f:
                        f.write(content)
                    self.logger.error(f"❌ صفحه‌ی کانال بارگذاری نشد. محتوای HTML در {debug_html} ذخیره شد.")
                    await self._save_debug_screenshot(page, "no_posts_error")
                    return [], context, page

            collected_ids = set()
            all_items = []
            no_new_count = 0
            scroll_attempts = 0
            max_scrolls = 200

            # ─── حلقه اصلی ──────────────────────────────────
            while len(all_items) < self.limit and scroll_attempts < max_scrolls:
                current_posts = await self._collect_current_posts(page)
                new_posts = [p for p in current_posts if p['id'] not in collected_ids]

                if new_posts:
                    all_items.extend(new_posts)
                    collected_ids.update([p['id'] for p in new_posts])
                    self.logger.info(f"🔍 جمعاً {len(all_items)} پست (جدید: {len(new_posts)})")
                    no_new_count = 0
                else:
                    no_new_count += 1
                    self.logger.debug(f"⚠️ هیچ پست جدیدی در اسکرول شماره {scroll_attempts+1}")

                # شرط خروج: رسیدن به limit یا ۳ بار پشت‌سر هم بدون پست جدید
                if len(all_items) >= self.limit or no_new_count >= 3:
                    break

                # اسکرول به پایین (ترکیبی از PageDown و جاوااسکریپت)
                await self._scroll_page_smart(page)

                # منتظر بارگذاری محتوای جدید
                try:
                    await page.wait_for_selector(".tgme_widget_message:last-child", timeout=5000, state="visible")
                except:
                    pass
                await asyncio.sleep(1.5)

                scroll_attempts += 1

                # اسکرین‌شات هر ۵ مرحله
                if scroll_attempts % 5 == 0:
                    await self._save_debug_screenshot(page, f"scroll_step_{scroll_attempts}")

            # ─── پس از خروج ──────────────────────────────────
            final_items = all_items[:self.limit]
            self.logger.info(f"✅ نهایی: {len(final_items)} پست استخراج شد (هدف: {self.limit})")

            # ذخیره اسکرین‌شات نهایی
            await self._save_debug_screenshot(page, "final_collection")

            return final_items, context, page

        except Exception as e:
            self.logger.error(f"❌ خطا در استخراج: {e}", exc_info=True)
            if page:
                await self._save_debug_screenshot(page, "error_state")
                # ذخیره محتوای صفحه برای تحلیل
                try:
                    content = await page.content()
                    debug_html = self.base_dir / "debug_error_page.html"
                    with open(debug_html, "w", encoding="utf-8") as f:
                        f.write(content)
                    self.logger.info(f"📄 محتوای صفحه‌ی خطا در {debug_html} ذخیره شد.")
                except:
                    pass
            return [], context, page

    # ─── متدهای کمکی ──────────────────────────────────────────

    async def _collect_current_posts(self, page):
        """
        جمع‌آوری پست‌های قابل‌مشاهده با استفاده از سلکتورهای مختلف.
        شناسه‌ی پست از attribute 'data-post' یا استخراج از لینک تاریخ گرفته می‌شود.
        """
        try:
            posts = await page.evaluate('''
                () => {
                    const items = document.querySelectorAll('.tgme_widget_message');
                    if (items.length === 0) {
                        // تلاش با سلکتور جایگزین
                        const altItems = document.querySelectorAll('.tgme_widget_message_wrap .tgme_widget_message');
                        if (altItems.length > 0) items = altItems;
                    }
                    const result = [];
                    items.forEach(el => {
                        let id = null;
                        // ۱. از data-post
                        if (el.dataset && el.dataset.post) {
                            id = parseInt(el.dataset.post, 10);
                        }
                        // ۲. از لینک تاریخ
                        if (!id) {
                            const link = el.querySelector('a.tgme_widget_message_date');
                            if (link) {
                                const href = link.getAttribute('href');
                                const match = href.match(/\\/(\\d+)$/);
                                if (match) id = parseInt(match[1], 10);
                            }
                        }
                        // ۳. fallback: استفاده از timestamp + متن کوتاه (موقتی)
                        if (!id) {
                            const time = el.querySelector('time')?.getAttribute('datetime') || '';
                            const text = el.innerText.slice(0, 30);
                            id = time + text; // non-numeric but unique enough
                        }
                        result.push({
                            id: id,
                            text: el.innerText || '',
                            // می‌توانید فیلدهای دیگر را هم اضافه کنید
                        });
                    });
                    return result;
                }
            ''')
            return posts
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در جمع‌آوری پست‌ها: {e}")
            return []

    async def _scroll_page_smart(self, page):
        """اسکرول ترکیبی برای بارگذاری محتوای جدید."""
        try:
            # روش اول: کلید PageDown
            await page.keyboard.press("PageDown")
            await asyncio.sleep(0.5)
            # روش دوم: اسکرول با جاوااسکریپت
            await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            await asyncio.sleep(0.5)
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در اسکرول: {e}")

    # ─── اورراید run و _run_impl ──────────────────────────────

    async def run(self):
        """اجرای اصلی با ذخیره‌ی خلاصه و مدیریت خطا."""
        try:
            await super().run()
        except Exception as e:
            self.logger.error(f"❌ خطا در اجرای اصلی: {e}", exc_info=True)
            # در صورت خطا، خروجی با کد ۱ نمی‌دهیم تا بتوانیم دیباگ کنیم
        finally:
            # ذخیره خلاصه دیباگ
            try:
                debug_json_path = self.base_dir / "debug_summary.json"
                summary = {
                    "channel": self.channel,
                    "limit": self.limit,
                    "start_link": self.start_link,
                    "total_posts": len(self._last_items),
                    "debug_mode": True
                }
                with open(debug_json_path, 'w', encoding='utf-8') as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)
                self.logger.info(f"🐞 خلاصه دیباگ در {debug_json_path}")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در ذخیره خلاصه: {e}")

    async def _run_impl(self):
        """پیاده‌سازی اصلی با ذخیره‌ی آیتم‌ها."""
        items, context, page = await self._fetch_posts_from_telegram()
        self._last_items = items

        if not items:
            self.logger.warning("⚠️ هیچ پستی دریافت نشد. بررسی لاگ‌ها و اسکرین‌شات‌ها.")
            if context:
                await context.close()
            return

        self.logger.info(f"📥 {len(items)} پست استخراج شد.")

        # تولید خروجی (با media_map خالی)
        try:
            gen = OutputGenerator(
                self.base_dir,
                self.channel,
                items,
                {},  # media_map خالی
                debug_mode=self.debug_mode
            )
            gen.run_all()
            self.logger.info(f"📁 فایل‌های خروجی در: {self.base_dir}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در تولید خروجی: {e}")

        if context:
            await context.close()

        self.logger.info("✅ پایان دیباگ.")


# ─── تابع اصلی ──────────────────────────────────────────────────

async def main():
    """اجرای اسکریپت دیباگ با مدیریت خطاهای سطح بالا."""
    print("🐞 ========================================")
    print("🐞 Telegram Channel Scraper - حالت دیباگ (نسخه‌ی پیشرفته)")
    print("🐞 ========================================")

    # بارگذاری تنظیمات
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

    # ایجاد نمونه‌ی اسکرپر دیباگ
    scraper = DebugTelegramChannelScraper(config, debug_screenshots=True)

    try:
        await scraper.run()
        print("\n🐞 دیباگ با موفقیت کامل شد.")
        print(f"🐞 خروجی‌ها در پوشه: {scraper.base_dir}")
        print(f"🐞 اسکرین‌شات‌های دیباگ در: {scraper.debug_screenshots_dir}")
        # اگر هیچ پستی دریافت نشد، با کد ۱ خارج می‌شویم (برای CI)
        if not scraper._last_items:
            print("❌ هیچ پستی استخراج نشد. لطفاً لاگ‌ها را بررسی کنید.")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ خطا در اجرای دیباگ: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
