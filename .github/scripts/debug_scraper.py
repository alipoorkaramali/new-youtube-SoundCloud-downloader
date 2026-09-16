#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت دیباگ برای Telegram Channel Scraper – نسخه هماهنگ با scraper.py
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


async def human_sleep(base: float, jitter: float = 0.4):
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class DebugTelegramChannelScraper(TelegramChannelScraper):
    def __init__(self, config, debug_screenshots: bool = True):
        config.debug_mode = True
        super().__init__(config)
        self.debug_screenshots = debug_screenshots
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._reply_posts = []
        self.scroll_direction = getattr(config, 'scroll_direction', 'up').lower()
        if self.scroll_direction not in ['up', 'down']:
            self.logger.warning(f"⚠️ scroll_direction نامعتبر: {self.scroll_direction}. استفاده از 'up'.")
            self.scroll_direction = 'up'
        self.logger.info(f"🐞 debug screenshots: {self.debug_screenshots_dir}")
        self.logger.info("🐞 حالت دیباگ – بدون دانلود رسانه")
        self.logger.info(f"🧭 جهت اسکرول: {'بالا (قدیمی‌تر/قبلی‌ها)' if self.scroll_direction == 'up' else 'پایین (جدیدتر)'}")
        self._last_items = []

    async def _download_media(self, items: List[Dict], page, context) -> tuple[dict, int]:
        self.logger.info("🐞 دیباگ: دانلود رسانه غیرفعال")
        return {item['id']: [] for item in items}, 0

    async def _save_debug_screenshot(self, page, name: str):
        if not self.debug_screenshots or not self.save_screenshots:
            return
        try:
            self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
            await self._screenshot(page, name, full_page=True)
        except Exception as e:
            self.logger.warning(f"⚠️ اسکرین‌شات دیباگ: {e}")

    async def _capture_full_page_screenshot(self, page, name: str = "full_page"):
        if not self.save_screenshots:
            return
        try:
            safe_channel = self._sanitize_filename(self.channel)
            path = self.screenshots_dir / f"{safe_channel}_{name}.png"
            await page.screenshot(path=path, full_page=True)
        except Exception as e:
            self.logger.warning(f"⚠️ اسکرین‌شات کامل: {e}")

    async def _fetch_posts_from_telegram(self, existing_seen_ids: set = None, keep_browser_open: bool = False,
                                         existing_context: any = None, existing_page: any = None,
                                         limit: int = None) -> tuple[List[Dict], any, any]:
        self.logger.info(f"🐞 استخراج جهت={self.scroll_direction} start_link={bool(self.start_link)}")
        items, context, page = await super()._fetch_posts_from_telegram(
            existing_seen_ids=existing_seen_ids,
            keep_browser_open=True,
            existing_context=existing_context,
            existing_page=existing_page,
            limit=limit
        )
        if not items or not page:
            self.logger.warning("⚠️ والد پستی تحویل نداد")
            return items, context, page
        self.logger.info(f"📥 {len(items)} پست | start_link={self.start_link} | scroll={self.scroll_direction}")
        if self.save_screenshots:
            await self._capture_full_page_screenshot(page, "final")
            await self._save_debug_screenshot(page, "debug_final")
        return items, context, page

    async def run(self):
        await super().run()
        try:
            summary = {
                "channel": self.channel,
                "limit": self.limit,
                "start_link": self.start_link,
                "scroll_direction": self.scroll_direction,
                "total_posts": len(self._last_items) if hasattr(self, '_last_items') else 0,
                "debug_mode": True
            }
            with open(self.base_dir / "debug_summary.json", 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"⚠️ خلاصه دیباگ: {e}")

    async def _run_impl(self):
        if self.start_link:
            self.logger.info(f"🚀 دیباگ با لینک: {self.start_link} (limit={self.limit})")
        else:
            self.logger.info(f"🚀 دیباگ @{self.channel} (limit={self.limit})")

        all_items = []
        global_seen_ids = set()
        rounds = 0
        max_rounds = max(15, (self.limit // 30) + 2)
        self.logger.info(f"🔄 تا {self.limit} پست (هر دور از آخرین مرز → قبلی/بعدی)")
        start_time = asyncio.get_event_loop().time()
        current_timeout = self.timeout_seconds
        context = None
        page = None

        while len(all_items) < self.limit and rounds < max_rounds:
            rounds += 1
            self.logger.info(f"📌 دور {rounds}/{max_rounds} | جمع‌شده {len(all_items)}/{self.limit}")

            # هر دور بعد از اول: از مرز مسیر ادامه (up=قدیمی‌ترین→قبلی‌ها)
            if rounds > 1 and all_items:
                def _id(x):
                    try:
                        return int(x.get('id', 0))
                    except Exception:
                        return 0
                if self.scroll_direction == 'down':
                    frontier = max(all_items, key=_id)
                    tag = 'newest'
                else:
                    frontier = min(all_items, key=_id)
                    tag = 'oldest'
                self.start_link = f"https://t.me/{self.channel}/{frontier['id']}"
                self.target_msg_id = frontier['id']
                self.logger.info(
                    f"🔄 دور {rounds}: از {tag}={self.target_msg_id} با scroll={self.scroll_direction}"
                )

            remaining = self.limit - len(all_items)
            if remaining <= 0:
                break

            if rounds == 1:
                items, context, page = await self._fetch_posts_from_telegram(
                    existing_seen_ids=global_seen_ids, keep_browser_open=True, limit=remaining
                )
            else:
                items, context, page = await self._fetch_posts_from_telegram(
                    existing_seen_ids=global_seen_ids, keep_browser_open=True,
                    existing_context=context, existing_page=page, limit=remaining
                )

            if not items and rounds > 1 and all_items:
                self.logger.warning("⚠️ resume ناموفق – حدس id قدیمی‌تر")
                failed_id = int(self.target_msg_id) if self.target_msg_id else None
                retry_success = False
                for offset in range(1, 11):
                    guess_id = failed_id - offset
                    if guess_id <= 0:
                        break
                    self.start_link = f"https://t.me/{self.channel}/{guess_id}"
                    self.target_msg_id = str(guess_id)
                    items, context, page = await self._fetch_posts_from_telegram(
                        existing_seen_ids=global_seen_ids, keep_browser_open=True,
                        existing_context=context, existing_page=page, limit=remaining
                    )
                    if items:
                        retry_success = True
                        break
                if not retry_success:
                    break

            if not items:
                self.logger.info("ℹ️ پست جدید در این دور نبود. پایان.")
                break

            filtered_items = []
            for item in items:
                msg_id = item['id']
                try:
                    msg_locator = page.locator(f'[data-message-id="{msg_id}"]').first
                    is_reply = await msg_locator.locator('.EmbeddedMessage').count() > 0
                    if is_reply:
                        self._reply_posts.append({
                            'id': msg_id, 'text': item.get('text', ''),
                            'date': item.get('date', ''),
                            'url': f"https://t.me/{self.channel}/{msg_id}"
                        })
                    else:
                        filtered_items.append(item)
                except Exception:
                    filtered_items.append(item)
            items = filtered_items

            new_items_count = 0
            for item in items:
                if item['id'] not in global_seen_ids:
                    global_seen_ids.add(item['id'])
                    all_items.append(item)
                    new_items_count += 1

            self.logger.info(f"📈 +{new_items_count} | مجموع {len(all_items)}/{self.limit}")

            if current_timeout > 0:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= current_timeout:
                    if self.auto_extend_timeout and new_items_count > 0:
                        current_timeout += 600
                    else:
                        break

            if len(all_items) >= self.limit:
                break
            if rounds >= max_rounds:
                if new_items_count > 0:
                    max_rounds += 1
                else:
                    break
            if hasattr(self, '_is_at_top') and await self._is_at_top(page):
                self.logger.info("📌 بالای صفحه – دور بعد")
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

        if len(all_items) > self.limit:
            all_items = all_items[:self.limit]
        self._last_items = all_items
        if not all_items:
            if context:
                await context.close()
            return

        self.logger.info(f"📥 {len(all_items)} پست در {rounds} دور")
        try:
            append_mode = getattr(self, 'resume', False) and getattr(self, '_resume_loaded', False)
            gen = OutputGenerator(self.base_dir, self.channel, all_items, {}, debug_mode=True, append_mode=append_mode)
            gen.run_all()
        except Exception as e:
            self.logger.warning(f"⚠️ خروجی: {e}")
        if context:
            await context.close()
        self.logger.info("✅ پایان دیباگ")


async def main():
    print("🐞 Telegram debug scraper")
    config_path = "config/config.yaml"
    try:
        config = load_config(config_path)
        print(f"کانال={config.channel} limit={config.limit} scroll={getattr(config,'scroll_direction','up')}")
    except Exception as e:
        print(f"❌ config: {e}")
        sys.exit(1)
    scraper = DebugTelegramChannelScraper(config, debug_screenshots=True)
    try:
        await scraper.run()
        print("✅ done")
    except Exception as e:
        print(f"❌ {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
