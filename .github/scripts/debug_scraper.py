#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ برای Telegram Channel Scraper – نسخه اتوماتیک با رفرش و ادامه از آخرین پست
– کاربر می‌تواند تعیین کند که از پست خاص به بالا (قدیمی‌تر) برود یا پایین (جدیدتر).
– در صورت نیاز، صفحه رفرش شده و از آخرین پست استخراج‌شده ادامه می‌یابد.
– تمام مراحل اسکرپینگ (جستجو، ورود، اسکرول، استخراج) را انجام می‌دهد.
– رسانه‌ها را دانلود نمی‌کند (فقط لاگ).
– اسکرین‌شات‌های کامل صفحه برای تحلیل بهتر ذخیره می‌کند.
– **افزوده‌شده: در صورت شکست اسکرول، اسکرین‌شات با فلش جهت اسکرول و وضعیت "updating"**
"""

import asyncio
import json
import sys
import random
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

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
    نسخه‌ی دیباگ اسکرپر با قابلیت انتخاب جهت اسکرول و رفرش خودکار.
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

    # ═══════════════ متد کمکی برای رسم فلش جهت اسکرول روی صفحه ═══════════════
    async def _draw_scroll_arrow(self, page, direction: str):
        """یک فلش در گوشه صفحه رسم می‌کند که جهت اسکرول را نشان می‌دهد."""
        arrow_html = """
        <div id="scroll-arrow" style="
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 99999;
            font-size: 60px;
            color: red;
            background: rgba(0,0,0,0.7);
            padding: 10px 15px;
            border-radius: 50%;
            border: 3px solid yellow;
            box-shadow: 0 0 20px rgba(255,0,0,0.8);
            pointer-events: none;
            transform: rotate(0deg);
        ">
        """
        if direction == 'up':
            arrow_html += "&#8593;"  # فلش بالا
        else:
            arrow_html += "&#8595;"  # فلش پایین
        arrow_html += "</div>"
        await page.evaluate(f"""
            () => {{
                const existing = document.getElementById('scroll-arrow');
                if (existing) existing.remove();
                document.body.insertAdjacentHTML('beforeend', `{arrow_html}`);
                setTimeout(() => {{
                    const el = document.getElementById('scroll-arrow');
                    if (el) el.style.display = 'none';
                }}, 5000);
            }}
        """)

    # ═══════════════ اسکرول هوشمند با پله‌های افزایشی و اسکرین‌شات در صورت شکست ═══════════════
    async def _smart_scroll(self, page, direction: str, step: int = 1200, max_attempts: int = 3) -> bool:
        """
        اسکرول هوشمند با سه پله افزایشی.
        در صورت شکست (عدم تغییر ارتفاع)، یک اسکرین‌شات با فلش جهت اسکرول می‌گیرد.
        همچنین وضعیت "updating" را بررسی می‌کند.
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

            # ─── رسم فلش روی صفحه ──────────────────────────
            await self._draw_scroll_arrow(page, direction)

            # ─── اسکرول ──────────────────────────────────
            await page.evaluate(f"window.scrollBy(0, {amount})")
            await human_sleep(1.2, 0.3)

            # ─── بررسی تغییر ارتفاع ──────────────────────
            new_height = await page.evaluate("document.documentElement.scrollHeight")
            if new_height != old_height:
                self.logger.info(f"✅ ارتفاع صفحه تغییر کرد: {old_height} → {new_height}")
                # پاک کردن فلش
                await page.evaluate("() => { const el = document.getElementById('scroll-arrow'); if(el) el.remove(); }")
                return True

        # ─── شکست اسکرول: گرفتن اسکرین‌شات با فلش ──────
        self.logger.info(f"⚠️ ارتفاع صفحه پس از {max_attempts} اسکرول تغییر نکرد.")
        # بررسی وضعیت "updating"
        is_updating = False
        try:
            updating_el = page.locator("text=Updating").first
            if await updating_el.count() > 0:
                is_updating = True
                self.logger.info("🔄 وضعیت 'Updating' در صفحه مشاهده شد.")
        except Exception:
            pass

        # اسکرین‌شات با فلش (فلش قبلاً رسم شده، اما ممکن است محو شده باشد؛ دوباره رسم می‌کنیم)
        await self._draw_scroll_arrow(page, direction)
        # کمی صبر تا فلش نمایش داده شود
        await asyncio.sleep(0.5)
        # گرفتن اسکرین‌شات
        timestamp = asyncio.get_event_loop().time()
        screenshot_name = f"scroll_failed_{direction}_{int(timestamp)}"
        await self._save_debug_screenshot(page, screenshot_name)
        self.logger.info(f"📸 اسکرین‌شات شکست اسکرول ذخیره شد: {screenshot_name}")

        # پاک کردن فلش
        await page.evaluate("() => { const el = document.getElementById('scroll-arrow'); if(el) el.remove(); }")

        if is_updating:
            self.logger.info("🔍 دلیل شکست: صفحه در حال به‌روزرسانی (Updating) است.")
        else:
            self.logger.info("🔍 دلیل شکست: محتوای جدیدی برای بارگذاری وجود ندارد (احتمالاً به انتها رسیده‌ایم).")

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

    # ═══════════════ ساخت لینک مستقیم به پیام ═══════════════════
    def _build_direct_link(self, channel: str, msg_id: str) -> str:
        """ساخت لینک مستقیم به یک پیام در تلگرام وب."""
        if not msg_id or not msg_id.isdigit():
            clean_channel = channel.lstrip('@')
            return f"https://web.telegram.org/k/#@{clean_channel}"
        clean_channel = channel.lstrip('@')
        return f"https://web.telegram.org/k/#@{clean_channel}/{msg_id}"

    # ═══════════════ یک دور اسکرول جهت‌دار ═══════════════════
    async def _single_scrape_attempt_with_direction(self, page, seen_ids: set) -> Tuple[List[Dict], int]:
        """
        یک دور اسکرول با جهت انتخابی (up/down) تا زمانی که پست جدیدی اضافه نشود.
        برمی‌گرداند: (لیست آیتم‌های جدید, تعداد آیتم‌های جدید)
        """
        self.logger.info(f"🔄 اسکرول جهت‌دار با {self.scroll_direction}...")
        new_items = []
        no_new_attempts = 0
        max_attempts = 6

        while len(seen_ids) < self.limit and no_new_attempts < max_attempts:
            # اسکرول هوشمند (که در صورت شکست اسکرین‌شات می‌گیرد)
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
                no_new_attempts = 0
            else:
                no_new_attempts += 1

            if len(seen_ids) >= self.limit:
                break

        return new_items, len(new_items)

    # ═══════════════ منطق اصلی با رفرش و ادامه از آخرین پست ═══════════════════
    async def _fetch_posts_with_refresh_and_resume(self) -> tuple[List[Dict], Any, Any]:
        """
        استخراج پست‌ها با اسکرول اولیه، سپس در صورت نیاز رفرش و ادامه از آخرین پست.
        """
        self.logger.info("🐞 شروع استخراج با رفرش و ادامه از آخرین پست...")

        # ۱. اجرای والد (ورود به کانال و استخراج اولیه)
        result = await super()._fetch_posts_from_telegram()
        items, context, page = result

        if not page:
            self.logger.error("❌ صفحه دریافت نشد.")
            return items, context, page

        if not items:
            self.logger.warning("⚠️ هیچ پستی از والد دریافت نشد.")
            return items, context, page

        self.logger.info(f"📥 والد {len(items)} پست تحویل داد.")

        if len(items) >= self.limit:
            await self._capture_full_page_screenshot(page, "final")
            return items, context, page

        # ─── تنظیمات حلقه ──────────────────────────────────
        seen_ids = {item.get('id') for item in items if item.get('id')}
        last_known_id = items[-1].get('id') if items else None
        max_refresh_attempts = 3
        refresh_count = 0

        # ─── اسکرول اولیه ──────────────────────────────────
        self.logger.info("🔄 مرحله ۱: اسکرول اولیه...")
        new_items, added = await self._single_scrape_attempt_with_direction(page, seen_ids)
        if new_items:
            items.extend(new_items)
            if new_items:
                last_known_id = new_items[-1].get('id') or last_known_id
            self.logger.info(f"📈 در اسکرول اولیه {added} پست جدید اضافه شد (مجموع: {len(items)})")

        if len(items) >= self.limit:
            await self._capture_full_page_screenshot(page, "final")
            return items, context, page

        # ─── حلقه رفرش و ادامه ────────────────────────────
        while len(items) < self.limit and refresh_count < max_refresh_attempts:
            refresh_count += 1
            self.logger.info(f"🔄 مرحله {refresh_count}: رفرش و ادامه از آخرین پست...")

            # ذخیره آخرین ID برای جستجو
            if not last_known_id:
                self.logger.warning("⚠️ آخرین ID مشخص نیست، از رفرش معمولی استفاده می‌شود.")
                await page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(3)
            else:
                # ── رفرش و جستجوی لینک ──────────────────
                self.logger.info(f"🔍 جستجوی لینک آخرین پست: {last_known_id}")

                # بستن context قبلی و ایجاد دوباره (برای شبیه‌سازی ورود مجدد)
                if context:
                    await context.close()
                    context = None
                    page = None

                # ایجاد context جدید (مانند والد)
                from playwright.async_api import async_playwright
                p = await async_playwright().start()
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=False,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                    viewport={"width": 1366, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

                # رفتن به لینک آخرین پست
                direct_link = self._build_direct_link(self.channel, last_known_id)
                self.logger.info(f"🔗 لینک مستقیم: {direct_link}")
                try:
                    await page.goto(direct_link, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3)
                    # اسکرول به پست مورد نظر
                    await page.evaluate(f"""
                        () => {{
                            const post = document.querySelector('[data-msg-id="{last_known_id}"]');
                            if (post) {{
                                post.scrollIntoView({{ behavior: "smooth", block: "center" }});
                            }}
                        }}
                    """)
                    await asyncio.sleep(2)
                    self.logger.info("✅ به لینک مستقیم رفتیم و اسکرول انجام شد.")
                    await self._save_debug_screenshot(page, f"after_refresh_{refresh_count}")
                except Exception as e:
                    self.logger.warning(f"⚠️ خطا در رفتن به لینک مستقیم: {e}")
                    # Fallback: جستجوی کانال
                    await self._search_and_enter_channel(page)

            # ── اسکرول مجدد با جهت ──────────────────────────
            self.logger.info(f"🔄 اسکرول مجدد با جهت {self.scroll_direction}...")
            new_items_round, added_round = await self._single_scrape_attempt_with_direction(page, seen_ids)
            if new_items_round:
                items.extend(new_items_round)
                if new_items_round:
                    last_known_id = new_items_round[-1].get('id') or last_known_id
                self.logger.info(f"📈 در دور {refresh_count} تعداد {added_round} پست جدید اضافه شد (مجموع: {len(items)})")

            if len(items) >= self.limit:
                break

        # ─── پایان ──────────────────────────────────────────
        await self._capture_full_page_screenshot(page, "final")
        await self._save_debug_screenshot(page, "debug_final")

        self.logger.info(f"🐞 استخراج نهایی: {len(items)} پست")
        return items, context, page

    # ═══════════════ بازنویسی متد استخراج برای استفاده از منطق جدید ═══════════════════
    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], Any, Any]:
        """
        نسخه نهایی با رفرش و جستجوی آخرین پست.
        """
        return await self._fetch_posts_with_refresh_and_resume()

    # ═══════════════ اجرای اصلی با ذخیره‌ی خلاصه JSON ═══════════════════
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
                "debug_mode": True,
                "auto_refresh": True
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
    print("🐞 Telegram Channel Scraper - حالت دیباگ (اتوماتیک با رفرش و تشخیص شکست)")
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
        print(f"   رفرش خودکار: فعال")
        print(f"   اسکرین‌شات در صورت شکست اسکرول: فعال")
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
