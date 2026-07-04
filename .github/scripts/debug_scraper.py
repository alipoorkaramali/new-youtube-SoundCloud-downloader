#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ برای Telegram Channel Scraper – نسخه هماهنگ با scraper.py
– کاربر می‌تواند تعیین کند که از پست خاص به بالا (قدیمی‌تر) برود یا پایین (جدیدتر).
– تمام مراحل اسکرپینگ (جستجو، ورود، اسکرول، استخراج) را انجام می‌دهد.
– رسانه‌ها را دانلود نمی‌کند (فقط لاگ).
– اسکرین‌شات‌های کامل صفحه برای تحلیل بهتر ذخیره می‌کند.
– قابلیت ادامه (Resume) از آخرین نقطه استخراج شده با رفتن دقیق به لینک ذخیره‌شده.
– در حالت Resume، با استفاده از append_mode در OutputGenerator، فایل HTML قبلی با پست‌های جدید ادغام می‌شود.
– اسکرین‌شات‌های قبلی در هر اجرا پاکسازی می‌شوند.
– لاگ‌های جامع برای دیباگ فرآیند ادغام و وضعیت Resume.
– اصلاح اسکرول: اسکرول روی کانتینر اصلی پیام‌ها (نه document) برای بارگذاری پست‌های قدیمی‌تر.
– دیباگ اسکرول: اسکرین‌شات از صفحه قبل از هر اسکرول با فلش جهت‌دار برای تحلیل خطاها.
"""

import asyncio
import json
import sys
import random
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import load_config
from scraper import TelegramChannelScraper
from output_generator import OutputGenerator


# ═══════════════════ Human-like sleep ═══════════════════
async def human_sleep(base: float, jitter: float = 0.4) -> None:
    """
    خواب با تاخیر انسانی (با جیتر تصادفی).

    Args:
        base (float): زمان پایه به ثانیه
        jitter (float): ضریب جیتر (0.4 = ±40%)
    """
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class DebugTelegramChannelScraper(TelegramChannelScraper):
    """
    نسخه‌ی دیباگ اسکرپر با قابلیت انتخاب جهت اسکرول و ادامه از آخرین نقطه.
    هماهنگ با scraper.py – از متد _smart_scroll با پله‌های افزایشی استفاده می‌کند.
    """

    def __init__(self, config, debug_screenshots: bool = True):
        """
        سازنده کلاس دیباگ اسکرپر.

        Args:
            config: آبجکت پیکربندی (از config.yaml)
            debug_screenshots (bool): فعال/غیرفعال‌سازی اسکرین‌شات‌های دیباگ
        """
        config.debug_mode = True
        super().__init__(config)
        self.debug_screenshots = debug_screenshots
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)

        # ─── پوشه مخصوص دیباگ اسکرول ──────────────────────────
        self.scroll_debug_dir = self.base_dir / "scroll_debug"
        self.scroll_debug_dir.mkdir(parents=True, exist_ok=True)

        # ─── جهت اسکرول ──────────────────────────────────────────
        self.scroll_direction = getattr(config, 'scroll_direction', 'up').lower()
        if self.scroll_direction not in ['up', 'down']:
            self.logger.warning(
                f"⚠️ مقدار نامعتبر برای scroll_direction: {self.scroll_direction}. "
                "استفاده از 'up'."
            )
            self.scroll_direction = 'up'

        # ─── Resume: خواندن وضعیت ──────────────────────────────
        self.resume = getattr(config, 'resume', False)
        self.resume_state_file = self.base_dir / "resume_state.json"
        self._resume_data = None
        self._resume_loaded = False
        self._resume_last_link = None

        if self.resume:
            self.logger.info("🔄 حالت ادامه (Resume) فعال است.")
            if self.resume_state_file.exists():
                try:
                    with open(self.resume_state_file, 'r', encoding='utf-8') as f:
                        self._resume_data = json.load(f)

                    last_link = self._resume_data.get('last_post_link')
                    last_msg_id = self._resume_data.get('last_msg_id')

                    if last_link:
                        self.start_link = last_link
                        self._resume_last_link = last_link
                        self.scroll_direction = 'up'  # اجباراً به سمت بالا (قدیمی‌تر)
                        self._resume_loaded = True

                        self.logger.info(f"🔗 لینک ادامه بارگذاری شد: {last_link}")
                        self.logger.info(f"📌 آخرین msg_id: {last_msg_id}")
                        self.logger.info(f"🧭 جهت اسکرول به‌طور خودکار به 'up' (قدیمی‌تر) تنظیم شد.")
                    else:
                        self.logger.warning(
                            "⚠️ فایل وضعیت موجود است اما 'last_post_link' پیدا نشد. "
                            "ادامه بدون resume."
                        )
                        self.resume = False
                except json.JSONDecodeError as e:
                    self.logger.warning(f"⚠️ خطا در دیکد JSON: {e}. ادامه بدون resume.")
                    self.resume = False
                except Exception as e:
                    self.logger.warning(f"⚠️ خطا در خواندن فایل وضعیت: {e}. ادامه بدون resume.")
                    self.resume = False
            else:
                self.logger.warning(
                    f"⚠️ فایل وضعیت '{self.resume_state_file}' یافت نشد. "
                    "ادامه بدون resume."
                )
                self.resume = False

        # ─── لاگ نهایی ──────────────────────────────────────────
        if self.start_link and not self.resume:
            self.logger.info(f"🔗 لینک شروع دستی: {self.start_link}")

        self.logger.info("🐞 حالت دیباگ فعال است – دانلود رسانه انجام نمی‌شود.")
        self.logger.info(f"🐞 پوشه اسکرین‌شات‌های دیباگ: {self.debug_screenshots_dir}")
        self.logger.info(f"🐞 پوشه دیباگ اسکرول: {self.scroll_debug_dir}")
        self.logger.info(
            f"🧭 جهت اسکرول نهایی: "
            f"{'بالا (قدیمی‌تر)' if self.scroll_direction == 'up' else 'پایین (جدیدتر)'}"
        )
        self.logger.info(
            f"📌 وضعیت Resume: فعال={self.resume}, بارگذاری‌شده={self._resume_loaded}"
        )

        self._last_items = []

    # ═══════════════════════════════════════════════════════════════════
    # متدهای اورراید شده از کلاس والد
    # ═══════════════════════════════════════════════════════════════════

    async def _download_media(self, items: List[Dict], page, context) -> Tuple[Dict, int]:
        """
        در حالت دیباگ، دانلود رسانه غیرفعال است.
        """
        self.logger.info("🐞 حالت دیباگ: دانلود رسانه غیرفعال است.")
        media_map = {}
        for item in items:
            msg_id = item.get('id')
            if msg_id:
                self.logger.debug(f"   🖼️ [دیباگ] پست {msg_id}: دانلود رسانه انجام نشد.")
                media_map[msg_id] = []
        return media_map, 0

    async def _save_debug_screenshot(self, page, name: str) -> None:
        """ذخیره اسکرین‌شات دیباگ (تمام صفحه)."""
        if not self.debug_screenshots:
            return
        try:
            self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
            await self._screenshot(page, name, full_page=True)
            self.logger.debug(f"🐞 اسکرین‌شات دیباگ ذخیره شد: {name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات دیباگ: {e}")

    # ═══════════════ دیباگ اسکرول: فلش جهت‌دار و اسکرین‌شات ═══════════════

    async def _take_scroll_debug_screenshot(self, page, direction: str, attempt: int) -> None:
        """
        گرفتن اسکرین‌شات از صفحه با رسم فلش جهت اسکرول.
        این اسکرین‌شات در پوشه scroll_debug ذخیره می‌شود.

        Args:
            page: صفحه مرورگر
            direction (str): 'up' یا 'down'
            attempt (int): شماره تلاش
        """
        if not self.debug_screenshots:
            return

        try:
            # ─── رسم فلش روی صفحه با JavaScript ──────────────────
            arrow_color = "#FF0000" if direction == 'up' else "#00FF00"
            arrow_symbol = "▲" if direction == 'up' else "▼"
            arrow_text = "UP" if direction == 'up' else "DOWN"

            await page.evaluate(f"""
                () => {{
                    // حذف فلش قبلی اگر وجود دارد
                    const oldArrow = document.getElementById('scroll_debug_arrow');
                    if (oldArrow) oldArrow.remove();

                    const arrow = document.createElement('div');
                    arrow.id = 'scroll_debug_arrow';
                    arrow.style.position = 'fixed';
                    arrow.style.left = '50%';
                    arrow.style.top = '50%';
                    arrow.style.transform = 'translate(-50%, -50%)';
                    arrow.style.fontSize = '120px';
                    arrow.style.color = '{arrow_color}';
                    arrow.style.fontWeight = 'bold';
                    arrow.style.textShadow = '0 0 20px rgba(0,0,0,0.8), 0 0 40px rgba(0,0,0,0.5)';
                    arrow.style.zIndex = '999999';
                    arrow.style.pointerEvents = 'none';
                    arrow.style.background = 'rgba(0,0,0,0.3)';
                    arrow.style.padding = '20px 40px';
                    arrow.style.borderRadius = '20px';
                    arrow.style.border = '5px solid {arrow_color}';
                    arrow.innerHTML = '{arrow_symbol} {arrow_text} {arrow_symbol}';
                    document.body.appendChild(arrow);
                }}
            """)

            # ─── تاخیر برای اطمینان از نمایش فلش ──────────────
            await human_sleep(0.5, 0.1)

            # ─── گرفتن اسکرین‌شات ──────────────────────────────
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
            safe_channel = self._sanitize_filename(self.channel)
            filename = f"{safe_channel}_scroll_{direction}_attempt_{attempt}_{timestamp}.png"
            path = self.scroll_debug_dir / filename
            await page.screenshot(path=path, full_page=True)
            self.logger.info(f"📸 اسکرین‌شات دیباگ اسکرول ذخیره شد: {path.name} (جهت: {direction}, تلاش: {attempt})")

            # ─── حذف فلش ──────────────────────────────────────────
            await page.evaluate("""
                () => {
                    const arrow = document.getElementById('scroll_debug_arrow');
                    if (arrow) arrow.remove();
                }
            """)

        except Exception as e:
            self.logger.warning(f"⚠️ خطا در گرفتن اسکرین‌شات دیباگ اسکرول: {e}")

    # ═══════════════ اسکرول هوشمند روی کانتینر اصلی ═══════════════

    async def _smart_scroll(
        self,
        page,
        direction: str,
        step: int = 2000,
        max_attempts: int = 6
    ) -> bool:
        """
        اسکرول هوشمند روی کانتینر اصلی پیام‌ها (نه document).
        در صورت فعال بودن دیباگ، قبل از هر اسکرول از صفحه اسکرین‌شات می‌گیرد.

        Args:
            page: صفحه مرورگر
            direction (str): 'up' یا 'down'
            step (int): مقدار پایه اسکرول
            max_attempts (int): تعداد پله‌ها

        Returns:
            bool: True اگر ارتفاع تغییر کرد، False اگر نه
        """
        # سلکتورهای احتمالی کانتینر پیام‌ها در تلگرام وب
        container_selectors = [
            'div.messages-container',
            'div.chat-messages',
            'div[class*="message-list"]',
            'div[class*="chat-container"]',
            'div[class*="scroll"]'
        ]
        selectors_json = json.dumps(container_selectors)

        # ─── یافتن کانتینر و ارتفاع اولیه ──────────────────────
        result = await page.evaluate(f"""
            (() => {{
                const selectors = {selectors_json};
                let el = document.documentElement;
                let foundSelector = 'document';
                for (const sel of selectors) {{
                    const found = document.querySelector(sel);
                    if (found) {{ el = found; foundSelector = sel; break; }}
                }}
                return {{
                    scrollHeight: el.scrollHeight,
                    foundSelector: foundSelector,
                    hasScrollBy: typeof el.scrollBy === 'function'
                }};
            }})()
        """)

        old_height = result['scrollHeight']
        found_selector = result.get('foundSelector', 'unknown')
        has_scroll_by = result.get('hasScrollBy', False)

        self.logger.debug(f"🔍 کانتینر پیدا شده: {found_selector}, scrollBy موجود: {has_scroll_by}, ارتفاع: {old_height}")

        scroll_multipliers = [1, 2, 3.5, 5]
        attempts = min(max_attempts, len(scroll_multipliers))

        for i in range(attempts):
            multiplier = scroll_multipliers[i]
            amount = int(step * multiplier)
            if direction == 'up':
                amount = -amount

            # ─── اسکرین‌شات دیباگ قبل از اسکرول ──────────────────
            await self._take_scroll_debug_screenshot(page, direction, i + 1)

            self.logger.debug(f"   اسکرول {amount}px (پله {i+1}/{attempts}) روی کانتینر: {found_selector}")

            # ─── اسکرول و گرفتن ارتفاع جدید ──────────────────────
            new_height = await page.evaluate(f"""
                (() => {{
                    const selectors = {selectors_json};
                    let el = document.documentElement;
                    for (const sel of selectors) {{
                        const found = document.querySelector(sel);
                        if (found) {{ el = found; break; }}
                    }}
                    if (el && typeof el.scrollBy === 'function') {{
                        el.scrollBy(0, {amount});
                    }} else {{
                        // Fallback: اسکرول روی window
                        window.scrollBy(0, {amount});
                    }}
                    return el.scrollHeight;
                }})()
            """)

            await human_sleep(1.5, 0.3)

            if new_height != old_height:
                self.logger.info(f"✅ ارتفاع کانتینر تغییر کرد: {old_height} → {new_height}")
                return True

            self.logger.debug(f"   ارتفاع کانتینر تغییری نکرد (تلاش {i+1}/{attempts})")

        self.logger.info(f"⚠️ ارتفاع کانتینر پس از {attempts} اسکرول تغییر نکرد.")
        return False

    # ═══════════════ استخراج پست‌ها با JavaScript ═══════════════════

    async def _extract_posts_from_page(self, page) -> List[Dict]:
        """
        استخراج پست‌ها از صفحه با JavaScript.
        """
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

    async def _capture_full_page_screenshot(self, page, name: str = "full_page") -> None:
        """
        گرفتن اسکرین‌شات کامل از کل صفحه.
        """
        try:
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)
            safe_channel = self._sanitize_filename(self.channel)
            path = self.screenshots_dir / f"{safe_channel}_{name}.png"
            await page.screenshot(path=path, full_page=True)
            self.logger.info(f"📸 اسکرین‌شات کامل صفحه ذخیره شد: {path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در اسکرین‌شات کامل: {e}")

    # ═══════════════ بازنویسی متد استخراج ═══════════════════

    async def _fetch_posts_from_telegram(self) -> Tuple[List[Dict], Any, Any]:
        """
        اجرای والد، سپس اگر تعداد پست‌ها کافی نبود، اسکرول جهت‌دار اضافی انجام می‌دهد.
        همچنین در حالت عادی (بدون start_link و بدون resume) به ابتدا یا انتها می‌پرد.
        """
        # ─── لاگ دقیق برای حالت Resume ──────────────────────────
        if self.resume and self._resume_loaded and self.start_link:
            self.logger.info("🔄 ====== حالت ادامه (Resume) ======")
            self.logger.info(f"🔗 رفتن به لینک ذخیره‌شده: {self.start_link}")
            self.logger.info("🧭 اسکرول به سمت بالا (قدیمی‌تر) برای دریافت پست‌های قبل از نقطه‌ی توقف")
            self.logger.info("=" * 50)
        elif self.start_link and not self.resume:
            self.logger.info(f"🔗 رفتن به لینک شروع دستی: {self.start_link}")

        self.logger.info(f"🐞 شروع استخراج با اسکرول جهت‌دار ({self.scroll_direction})...")

        # ─── اجرای والد ──────────────────────────────────────────
        result = await super()._fetch_posts_from_telegram()
        items, context, page = result

        if not page:
            self.logger.error("❌ صفحه دریافت نشد.")
            return items, context, page

        if not items:
            self.logger.warning("⚠️ والد هیچ پستی نیاورد.")
            return items, context, page

        self.logger.info(f"📥 والد {len(items)} پست تحویل داد.")

        # اگر به تعداد کافی پست داریم، ادامه نده
        if len(items) >= self.limit:
            await self._capture_full_page_screenshot(page, "final")
            return items, context, page

        # ─── پرش به ابتدا یا انتها (فقط در حالت عادی) ──────────
        if not self.start_link and not self.resume:
            if self.scroll_direction == 'up':
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
                            break
                    except Exception:
                        continue
                if not clicked:
                    self.logger.info("   ℹ️ دکمه پرش به پایین پیدا نشد. ادامه با وضعیت فعلی.")
            else:  # scroll_direction == 'down'
                self.logger.info("⬆️ تلاش برای رفتن به بالای صفحه (قدیمی‌ترین پست‌ها)...")
                await page.evaluate("window.scrollTo(0, 0)")
                await human_sleep(2, 0.3)
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, -2000)")
                    await human_sleep(1, 0.2)
                self.logger.info("   ✅ به بالای صفحه رفتیم.")

        # ─── اسکرول جهت‌دار برای دریافت پست‌های بیشتر ──────────
        seen_ids = {item.get('id') for item in items if item.get('id')}
        new_items = []
        no_new_attempts = 0
        max_attempts = 6

        while len(seen_ids) < self.limit and no_new_attempts < max_attempts:
            scrolled = await self._smart_scroll(page, self.scroll_direction, step=2500, max_attempts=4)
            if not scrolled:
                no_new_attempts += 1
                self.logger.info(f"⏳ اسکرول نتیجه‌ای نداشت ({no_new_attempts}/{max_attempts})")
                continue

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

        if new_items:
            if self.scroll_direction == 'down':
                new_items.reverse()
            items.extend(new_items)
            self.logger.info(f"📈 مجموعاً {len(items)} پست (با {len(new_items)} پست جدید)")

        # ─── اسکرین‌شات نهایی ────────────────────────────────────
        await self._capture_full_page_screenshot(page, "final")
        await self._save_debug_screenshot(page, "debug_final")

        self.logger.info(f"🐞 استخراج نهایی: {len(items)} پست")
        return items, context, page

    # ═══════════════ متد run ─────────────────────────────────────────

    async def run(self) -> None:
        """
        اجرای اصلی با ذخیرهٔ خلاصه JSON و ذخیره وضعیت ادامه.
        """
        await super().run()

        # ─── ذخیره وضعیت ادامه ──────────────────────────────────
        try:
            if hasattr(self, '_last_items') and self._last_items:
                oldest_item = min(self._last_items, key=lambda x: int(x.get('id', 0)))
                msg_id = oldest_item.get('id')
                if msg_id:
                    last_post_link = f"https://t.me/{self.channel}/{msg_id}"
                    state = {
                        "last_post_link": last_post_link,
                        "last_msg_id": msg_id,
                        "channel": self.channel,
                        "timestamp": asyncio.get_event_loop().time(),
                        "total_posts": len(self._last_items)
                    }
                    with open(self.resume_state_file, 'w', encoding='utf-8') as f:
                        json.dump(state, f, ensure_ascii=False, indent=2)
                    self.logger.info(f"💾 وضعیت ادامه ذخیره شد: {self.resume_state_file}")
                    self.logger.info(f"🔗 آخرین پست (قدیمی‌ترین) برای ادامه‌ی بعدی: {last_post_link}")
                    self.logger.info(f"📊 تعداد کل پست‌های جمع‌آوری‌شده تا الان: {len(self._last_items)}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره وضعیت ادامه: {e}")

        # ─── ذخیره خلاصه دیباگ ──────────────────────────────────
        try:
            debug_json_path = self.base_dir / "debug_summary.json"
            summary = {
                "channel": self.channel,
                "limit": self.limit,
                "start_link": self.start_link,
                "scroll_direction": self.scroll_direction,
                "total_posts": len(self._last_items) if hasattr(self, '_last_items') else 0,
                "debug_mode": True,
                "resume": self.resume,
                "resume_loaded": self._resume_loaded,
                "resume_last_link": self._resume_last_link
            }
            with open(debug_json_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            self.logger.info(f"🐞 خلاصه دیباگ ذخیره شد: {debug_json_path}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره خلاصه دیباگ: {e}")

    # ═══════════════ متد اصلی اجرا با پاکسازی اسکرین‌شات‌ها ═══════════════

    async def _run_impl(self) -> None:
        """
        Override برای ذخیرهٔ آیتم‌ها و تولید خروجی.
        شامل پاکسازی اسکرین‌شات‌های قبلی و مدیریت append_mode.
        """
        # ─── پاکسازی اسکرین‌شات‌های قبلی ──────────────────────
        if self.debug_screenshots:
            self.logger.info("🧹 پاکسازی اسکرین‌شات‌های قبلی...")
            try:
                if self.debug_screenshots_dir.exists():
                    shutil.rmtree(self.debug_screenshots_dir)
                    self.logger.info(f"   ✅ پوشه {self.debug_screenshots_dir.name} پاک شد")

                if hasattr(self, 'screenshots_dir') and self.screenshots_dir.exists():
                    shutil.rmtree(self.screenshots_dir)
                    self.logger.info(f"   ✅ پوشه {self.screenshots_dir.name} پاک شد")

                # پوشه scroll_debug را پاک نمی‌کنیم تا اسکرین‌شات‌های قبلی باقی بمانند
                # اما برای شروع تمیز، می‌توانیم پاک کنیم (اختیاری)
                # if self.scroll_debug_dir.exists():
                #     shutil.rmtree(self.scroll_debug_dir)
                #     self.logger.info(f"   ✅ پوشه {self.scroll_debug_dir.name} پاک شد")

                self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
                if hasattr(self, 'screenshots_dir'):
                    self.screenshots_dir.mkdir(parents=True, exist_ok=True)
                self.scroll_debug_dir.mkdir(parents=True, exist_ok=True)

            except Exception as e:
                self.logger.warning(f"⚠️ خطا در پاکسازی اسکرین‌شات‌های قبلی: {e}")

        # ─── لاگ شروع ────────────────────────────────────────────
        if self.start_link:
            self.logger.info(f"🚀 شروع اسکریپر دیباگ با لینک: {self.start_link} (limit={self.limit})")
        else:
            self.logger.info(f"🚀 شروع اسکریپر دیباگ برای @{self.channel} (limit={self.limit})")

        # ─── استخراج پست‌ها ─────────────────────────────────────
        items, context, page = await self._fetch_posts_from_telegram()

        # ─── تعیین append_mode ──────────────────────────────────
        append_mode = self.resume and self._resume_loaded
        self.logger.info(
            f"📌 وضعیت append_mode: {append_mode} "
            f"(resume={self.resume}, _resume_loaded={self._resume_loaded})"
        )

        self._last_items = items

        if not items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            if context:
                await context.close()
            return

        self.logger.info(f"📥 {len(items)} پست استخراج شد (حالت دیباگ).")

        # ─── تولید خروجی ─────────────────────────────────────────
        try:
            gen = OutputGenerator(
                self.base_dir,
                self.channel,
                items,
                {},
                debug_mode=self.debug_mode,
                append_mode=append_mode
            )
            gen.run_all()
            self.logger.info(f"🐞 فایل‌های خروجی دیباگ در: {self.base_dir}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در تولید خروجی: {e}", exc_info=True)

        # ─── بستن context ──────────────────────────────────────
        if context:
            await context.close()

        self.logger.info("✅ پایان موفقیت‌آمیز دیباگ.")


# ═══════════════════ نقطه ورود ──────────────────────────────────────

async def main() -> None:
    """
    تابع اصلی اجرای اسکریپت دیباگ.
    """
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
        resume = getattr(config, 'resume', False)
        print(f"   حالت ادامه: {'فعال' if resume else 'غیرفعال'}")
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
        print(f"🐞 اسکرین‌شات‌های دیباگ اسکرول در: {scraper.scroll_debug_dir}")
    except Exception as e:
        print(f"\n❌ خطا در اجرای دیباگ: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
