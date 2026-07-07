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
from scraper import TelegramChannelScraper, HOME_URL
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

        
    async def _extract_posts_from_page(self, page) -> List[Dict]:
        """استخراج مستقیم پست‌ها با JavaScript (selectors قوی‌تر)."""
        return await page.evaluate("""
            () => {
                const posts = [];
                document.querySelectorAll('[data-message-id]').forEach(el => {
                    const msgId = el.getAttribute('data-message-id');
                    if (!msgId) return;
                    // تلاش برای یافتن متن با چندین selector رایج
                    const textSelectors = [
                        '.text-content', '.message-text', '[dir="auto"]',
                        '.text', '.message', 'div[class*="text"]',
                        'div[class*="body"]', 'div[class*="message"]'
                    ];
                    let text = '';
                    for (const sel of textSelectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.trim().length > 3) {
                            text = el.innerText.trim();
                            break;
                        }
                    }
                    // fallback: کل innerText المنت اگر چیزی پیدا نشد
                    if (!text) text = el.innerText.trim().substring(0, 1000);
                    const dateEl = el.querySelector('time, .date, [class*="date"], [datetime]');
                    const date = dateEl ? (dateEl.getAttribute('datetime') || dateEl.innerText.trim()) : '';
                    posts.push({ id: msgId, text: text, date: date });
                });
                return posts;
            }
        """)
    
    # ═══════════════ بازنویسی متد استخراج با پرش به بالا/پایین و اسکرول جهت‌دار ═══════════════════
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
        """اجرای دیباگ با حلقه‌ی چنددوره‌ای (هماهنگ با والد)."""
        if self.start_link:
            self.logger.info(f"🚀 شروع اسکریپر دیباگ با لینک: {self.start_link} (limit={self.limit})")
        else:
            self.logger.info(f"🚀 شروع اسکریپر دیباگ برای @{self.channel} (limit={self.limit})")

        all_items = []
        global_seen_ids = set()
        rounds = 0
        max_rounds = max(15, (self.limit // 30) + 2)
        self.logger.info(f"🔄 دیباگ تا رسیدن به {self.limit} پست ادامه می‌دهد...")

        context = None
        page = None

        while len(all_items) < self.limit and rounds < max_rounds:
            rounds += 1
            self.logger.info(f"📌 دور {rounds} از {max_rounds}")
            self.logger.info(f"📊 پست‌های جمع‌آوری‌شده تا اینجا: {len(all_items)}/{self.limit}")

            if rounds > 1 and all_items:
                # پیدا کردن قدیمی‌ترین پست با اسکرین‌شات
                oldest_post = None
                sorted_items = sorted(all_items, key=lambda x: int(x.get('id', 0)))
                for item in sorted_items:
                    msg_id = item['id']
                    safe_channel = self._sanitize_filename(self.channel)
                    safe_msg_id = self._sanitize_filename(str(msg_id))
                    screenshot_path = self.screenshots_dir / f"{safe_channel}_post_{safe_msg_id}.png"
                    if screenshot_path.exists():
                        oldest_post = item
                        break
                if oldest_post is None:
                    oldest_post = min(all_items, key=lambda x: int(x.get('id', 0)))
                    self.logger.warning(f"⚠️ هیچ اسکرین‌شاتی برای پست‌های قدیمی پیدا نشد، از oldest بدون اسکرین‌شات استفاده می‌شود: {oldest_post['id']}")
                resume_link = f"https://t.me/{self.channel}/{oldest_post['id']}"
                self.start_link = resume_link
                self.target_msg_id = oldest_post['id']
                self.logger.info(f"🔄 ادامه از پست {self.target_msg_id} (دور {rounds})")

            remaining = self.limit - len(all_items)
            if remaining <= 0:
                break

            if rounds == 1:
                items, context, page = await self._fetch_posts_from_telegram(
                    existing_seen_ids=global_seen_ids,
                    keep_browser_open=True,
                    limit=remaining
                )
            else:
                items, context, page = await self._fetch_posts_from_telegram(
                    existing_seen_ids=global_seen_ids,
                    keep_browser_open=True,
                    existing_context=context,
                    existing_page=page,
                    limit=remaining
                )


            # اگر آیتمی نیامد و در دور resume هستیم
            if not items and rounds > 1 and all_items:
                self.logger.warning("⚠️ دور resume ناموفق – تلاش با شناسه‌های قدیمی‌تر از oldest (والد قبلاً اسکرول قوی کرده)...")
                oldest_id = min(int(it['id']) for it in all_items)
                retry_success = False

                # ۷ شناسهٔ قدیمی‌تر را امتحان کن
                for offset in range(1, 8):
                    candidate_id = oldest_id - offset
                    if candidate_id <= 0:
                        break
                    self.logger.info(f"🔄 حدس شناسهٔ قدیمی‌تر: {candidate_id}")
                    self.start_link = f"https://t.me/{self.channel}/{candidate_id}"
                    self.target_msg_id = str(candidate_id)

                    items, context, page = await self._fetch_posts_from_telegram(
                        existing_seen_ids=global_seen_ids,
                        keep_browser_open=True,
                        existing_context=context,
                        existing_page=page,
                        limit=remaining
                    )
                    if items:
                        retry_success = True
                        self.logger.info(f"✅ شروع از {candidate_id} موفق بود — {len(items)} پست جدید اضافه شد.")
                        break

                if not retry_success:
                    self.logger.warning("⚠️ هیچ‌یک از شناسه‌های حدس‌زده پاسخ ندادند. پایان.")
                    break    
            if not items:
                self.logger.info("ℹ️ پست جدیدی در این دور پیدا نشد. پایان.")
                break

            new_items_count = 0
            for item in items:
                if item['id'] not in global_seen_ids:
                    global_seen_ids.add(item['id'])
                    all_items.append(item)
                    new_items_count += 1
            self.logger.info(f"📈 {new_items_count} پست جدید در این دور اضافه شد")
            self.logger.info(f"📊 مجموع پست‌ها تا اینجا: {len(all_items)}/{self.limit}")

            if len(all_items) >= self.limit or rounds >= max_rounds:
                break

            if hasattr(self, '_is_at_top') and await self._is_at_top(page):
                self.logger.info("📌 به بالای صفحه رسیدیم. شروع دور بعدی...")
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

        if len(all_items) > self.limit:
            all_items = all_items[:self.limit]
            self.logger.info(f"📊 تعداد پست‌ها به {self.limit} محدود شد.")
        self._last_items = all_items

        if not all_items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            if context:
                await context.close()
            return

        self.logger.info(f"📥 {len(all_items)} پست استخراج شد (در {rounds} دور).")

        try:
            append_mode = getattr(self, 'resume', False) and getattr(self, '_resume_loaded', False)
            gen = OutputGenerator(
                self.base_dir,
                self.channel,
                all_items,
                {},
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
