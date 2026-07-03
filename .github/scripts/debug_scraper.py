#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ برای Telegram Channel Scraper – نسخه کامل با پشتیبانی از:
- اسکرول جهت‌دار (بالا/پایین) برای دریافت پست‌های قدیمی‌تر یا جدیدتر
- رعایت کامل لیمیت (تا رسیدن به تعداد درخواستی یا پایان محتوا)
- انتظار برای بارگذاری کامل (نشانگر "updating..." یا "به‌روزرسانی...")
- ذخیره اسکرین‌شات‌های کامل و دیباگ
- غیرفعال کردن دانلود رسانه (حالت دیباگ)
- مدیریت خطاها و تطابق کامل با کلاس والد (TelegramChannelScraper)
"""

import asyncio
import json
import sys
import random
from pathlib import Path
from typing import List, Dict, Any, Optional

# اضافه کردن مسیر پروژه برای دسترسی به ماژول‌های دیگر
sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import load_config
from scraper import TelegramChannelScraper
from output_generator import OutputGenerator


# ═══════════════════ توابع کمکی ═══════════════════
async def human_sleep(base: float, jitter: float = 0.4):
    """خواب انسانی با جیتر تصادفی."""
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


# ═══════════════════ کلاس دیباگ اسکرپر ═══════════════════
class DebugTelegramChannelScraper(TelegramChannelScraper):
    """
    نسخه‌ی دیباگ اسکرپر با قابلیت:
    - اسکرول جهت‌دار (up/down)
    - انتظار برای بارگذاری کامل (updating...)
    - ذخیره اسکرین‌شات‌های کامل و دیباگ
    - غیرفعال کردن دانلود رسانه
    """

    def __init__(self, config, debug_screenshots: bool = True):
        # فعال کردن حالت دیباگ در والد
        config.debug_mode = True
        super().__init__(config)

        # ─── تنظیمات دیباگ ──────────────────────────────
        self.debug_screenshots = debug_screenshots

        # اطمینان از وجود base_dir (اگر والد آن را نداشته باشد)
        if not hasattr(self, 'base_dir'):
            self.base_dir = Path(config.output_dir) if hasattr(config, 'output_dir') else Path.cwd() / "output"
            self.base_dir.mkdir(parents=True, exist_ok=True)

        # پوشه اسکرین‌شات‌های دیباگ
        self.debug_screenshots_dir = self.base_dir / "debug_screenshots"
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)

        # پوشه اسکرین‌شات‌های معمولی (اگر والد نداشته باشد)
        if not hasattr(self, 'screenshots_dir'):
            self.screenshots_dir = self.base_dir / "screenshots"
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # ─── جهت اسکرول ──────────────────────────────────
        self.scroll_direction = getattr(config, 'scroll_direction', 'up').lower()
        if self.scroll_direction not in ['up', 'down']:
            self.logger.warning(
                f"⚠️ مقدار نامعتبر برای scroll_direction: {self.scroll_direction}. استفاده از 'up'."
            )
            self.scroll_direction = 'up'

        # ─── لاگ اولیه ────────────────────────────────────
        self.logger.info("🐞 حالت دیباگ فعال است – دانلود رسانه انجام نمی‌شود.")
        self.logger.info(f"🐞 پوشه اسکرین‌شات‌های دیباگ: {self.debug_screenshots_dir}")
        self.logger.info(
            f"🧭 جهت اسکرول: {'بالا (قدیمی‌تر)' if self.scroll_direction == 'up' else 'پایین (جدیدتر)'}"
        )

        # متغیر برای نگهداری آخرین پست‌ها (جهت خلاصه)
        self._last_items = []

    # ═══════════════ غیرفعال کردن دانلود رسانه ═══════════════
    async def _download_media(self, items: List[Dict], page, context) -> tuple[dict, int]:
        """در حالت دیباگ، دانلود رسانه غیرفعال است."""
        self.logger.info("🐞 حالت دیباگ: دانلود رسانه غیرفعال است.")
        media_map = {}
        for item in items:
            msg_id = item.get('id')
            if msg_id:
                self.logger.info(f"   🖼️ [دیباگ] پست {msg_id}: دانلود رسانه انجام نشد.")
                media_map[msg_id] = []
        return media_map, 0

    # ═══════════════ متد اسکرین‌شات (در صورت نبود در والد) ═══════════════
    async def _screenshot(self, page, name: str, full_page: bool = False):
        """ذخیره اسکرین‌شات در پوشه دیباگ (در صورت نداشتن والد)."""
        try:
            # اگر والد متد _screenshot دارد، از آن استفاده می‌کنیم
            if hasattr(super(), '_screenshot'):
                return await super()._screenshot(page, name, full_page)
            # در غیر این صورت خودمان ذخیره می‌کنیم
            safe_name = self._sanitize_filename(name)
            path = self.debug_screenshots_dir / f"{safe_name}.png"
            await page.screenshot(path=path, full_page=full_page)
            self.logger.debug(f"🐞 اسکرین‌شات ذخیره شد: {path}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات: {e}")

    async def _save_debug_screenshot(self, page, name: str):
        """ذخیره اسکرین‌شات دیباگ (فقط در صورت فعال بودن)."""
        if not self.debug_screenshots:
            return
        try:
            await self._screenshot(page, name, full_page=True)
            self.logger.debug(f"🐞 اسکرین‌شات دیباگ ذخیره شد: {name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات دیباگ: {e}")

    async def _capture_full_page_screenshot(self, page, name: str = "full_page"):
        """گرفتن اسکرین‌شات کامل از کل صفحه (با نام خاص)."""
        try:
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)
            safe_channel = self._sanitize_filename(self.channel)
            path = self.screenshots_dir / f"{safe_channel}_{name}.png"
            await page.screenshot(path=path, full_page=True)
            self.logger.info(f"📸 اسکرین‌شات کامل صفحه ذخیره شد: {path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در اسکرین‌شات کامل: {e}")

    # ═══════════════ انتظار برای بارگذاری کامل (updating...) ═══════════════
    async def _wait_for_update_complete(self, page, timeout: int = 60):
        """
        منتظر می‌ماند تا عبارت 'updating...' یا 'به‌روزرسانی...' از صفحه ناپدید شود.
        اگر عبارت وجود نداشته باشد، بلافاصله ادامه می‌دهد.
        """
        self.logger.info("⏳ بررسی وضعیت بارگذاری (جستجوی 'updating...')...")
        try:
            # منتظر می‌مانیم تا المان حاوی این متن، مخفی یا حذف شود (state='hidden')
            await page.wait_for_selector(
                "xpath=//*[contains(text(), 'updating...') or contains(text(), 'به‌روزرسانی...')]",
                state="hidden",
                timeout=timeout * 1000  # تبدیل به میلی‌ثانیه
            )
            self.logger.info("✅ عبارت بارگذاری ناپدید شد. ادامه می‌دهیم.")
        except Exception as e:
            # اگر تایم‌اوت شد یا خطایی رخ داد (مثلاً المان پیدا نشد)، ادامه می‌دهیم
            self.logger.warning(
                f"⚠️ انتظار برای 'updating...' با خطا/تایم‌اوت مواجه شد: {e}. ادامه می‌دهیم..."
            )

    # ═══════════════ اسکرول هوشمند با پله‌های افزایشی ═══════════════
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

    # ═══════════════ استخراج پست‌ها با JavaScript ═══════════════
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

    # ═══════════════ بازنویسی متد استخراج با پرش به بالا/پایین و اسکرول جهت‌دار ═══════════════
    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], Any, Optional[Any]]:
        """
        اجرای والد، سپس اگر تعداد پست‌ها کافی نبود، اسکرول جهت‌دار اضافی انجام می‌دهد.
        همچنین در حالت عادی (بدون start_link و بدون resume) به ابتدا یا انتها می‌پرد.
        """
        self.logger.info(f"🐞 شروع استخراج با اسکرول جهت‌دار ({self.scroll_direction})...")

        # ۱. اجرای والد (که شامل ورود به کانال و جمع‌آوری اولیه است)
        result = await super()._fetch_posts_from_telegram()
        items, context, page = result

        if not page:
            self.logger.error("❌ صفحه دریافت نشد.")
            return items, context, page

        # ✅ انتظار برای پایان بارگذاری اولیه (updating...)
        await self._wait_for_update_complete(page)
        await self._save_debug_screenshot(page, "after_initial_load")

        if not items:
            self.logger.warning("⚠️ والد هیچ پستی نیاورد.")
            return items, context, page

        self.logger.info(f"📥 والد {len(items)} پست تحویل داد.")

        # اگر به اندازه کافی پست داریم، بدون اسکرول اضافی برگردان
        if len(items) >= self.limit:
            await self._capture_full_page_screenshot(page, "final")
            return items, context, page

        # ─── پرش به ابتدا یا انتها در حالت عادی (بدون start_link و resume) ───
        resume_data = getattr(self, 'resume_data', {})
        if not self.start_link and not resume_data.get('last_msg_id'):
            if self.scroll_direction == 'up':
                # برای جمع‌آوری قدیمی‌ترها، باید به پایین‌ترین نقطه برویم (جدیدترین پست‌ها)
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
                            # پس از کلیک، دوباره منتظر updating...
                            await self._wait_for_update_complete(page, timeout=30)
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
                    await self._wait_for_update_complete(page, timeout=15)
                self.logger.info("   ✅ به بالای صفحه رفتیم.")

        # ─── اسکرول جهت‌دار اضافی برای دریافت پست‌های بیشتر ──────────────────
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

            # ✅ قبل از استخراج، صبر می‌کنیم تا بارگذاری کامل شود
            await self._wait_for_update_complete(page, timeout=30)

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

        # ─── ترکیب پست‌ها ────────────────────────────────────────────
        if new_items:
            # اگر جهت down است، پست‌های جدیدتر را در ابتدا قرار بده
            if self.scroll_direction == 'down':
                new_items.reverse()
            items.extend(new_items)
            self.logger.info(f"📈 مجموعاً {len(items)} پست (با {len(new_items)} پست جدید)")

        # ─── اسکرین‌شات نهایی ─────────────────────────────────────────
        await self._capture_full_page_screenshot(page, "final")
        await self._save_debug_screenshot(page, "debug_final")

        self.logger.info(f"🐞 استخراج نهایی: {len(items)} پست")
        return items, context, page

    # ═══════════════ اجرای اصلی و ذخیره خلاصه ═══════════════
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


# ═══════════════════ تابع اصلی ═══════════════════
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