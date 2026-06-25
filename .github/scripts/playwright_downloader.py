#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import random
from pathlib import Path
from typing import List, Dict, Optional

from playwright.async_api import Page

logger = logging.getLogger("TelegramScraper")


async def human_sleep(base: float, jitter: float = 0.4):
    """خواب انسانی با کمی تصادف"""
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class PlaywrightDownloader:
    """
    **نسخهٔ دیباگ راست‌کلیک – یک کلیک روی کل پیام**
    برای هر پست، یک بار روی حباب پیام راست‌کلیک می‌کند، اسکرین‌شات می‌گیرد،
    منو را با کلیک چپ می‌بندد و به پست بعدی می‌رود.
    هیچ پردازشی روی مدیاهای درون پیام انجام نمی‌شود.
    """

    def __init__(self, profile_dir: Path, media_dir: Path, max_bytes: int,
                 delay: float = 5.0, max_retries: int = 2):
        self.profile_dir = profile_dir
        self.media_dir = media_dir
        self.max_bytes = max_bytes
        self.delay = delay
        self.max_retries = max_retries
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # پوشهٔ دیباگ
        self.debug_dir = self.media_dir.parent / "debug_rightclick"
        self.debug_dir.mkdir(parents=True, exist_ok=True)

    async def download_all(self, page: Page, context, post_ids: List[str],
                           media_map: Optional[Dict[str, List[str]]] = None) -> None:
        """حلقهٔ اصلی – فقط راست‌کلیک روی پیام، اسکرین‌شات، بستن با کلیک چپ"""
        if not post_ids:
            logger.info("هیچ پستی برای بررسی وجود ندارد.")
            return

        for idx, post_id in enumerate(post_ids, start=1):
            logger.info(f"📥 [{idx}/{len(post_ids)}] پست {post_id}")
            try:
                await asyncio.wait_for(
                    self._process_post(page, post_id),
                    timeout=45      # کاهش timeout چون کار زیادی انجام نمی‌شود
                )
            except asyncio.TimeoutError:
                logger.warning(f"⏰ پست {post_id} تایم‌اوت کلی شد، رد می‌شود.")
            except Exception as e:
                logger.error(f"❌ خطا در پست {post_id}: {e}")
            if idx < len(post_ids):
                await human_sleep(self.delay, 0.5)

    async def _process_post(self, page: Page, post_id: str) -> None:
        """نمایان کردن پست، راست‌کلیک روی خود پیام، اسکرین‌شات، بستن منو"""
        logger.info(f"📍 شروع بررسی پست {post_id}")

        message_locator = page.locator(f'[data-message-id="{post_id}"]').first

        # تلاش برای نمایان کردن پست (۵ تلاش مثل قبل)
        success = False
        for attempt in range(5):
            try:
                logger.debug(f"   🔄 تلاش {attempt+1} برای نمایان کردن پست")
                await message_locator.scroll_into_view_if_needed(timeout=20000)
                wait = 1.8 if attempt == 0 else 1.2
                await human_sleep(wait, 0.4)
                await message_locator.wait_for(state="visible", timeout=20000)
                await human_sleep(1.0, 0.3)

                if await message_locator.count() > 0:
                    success = True
                    logger.debug(f"   ✅ پست بعد از {attempt+1} تلاش نمایان شد")
                    break
            except Exception:
                if attempt < 4:
                    logger.debug(f"   🔄 تلاش ناموفق — اسکرول کمکی و صبر دوباره")
                    await page.evaluate("window.scrollBy(0, -1200)")
                    await human_sleep(2.5, 0.5)
                else:
                    logger.warning(f"⚠️ پست {post_id} بعد از ۵ تلاش پیدا نشد.")
                    return

        if not success:
            return

        logger.info(f"   📍 پست {post_id} آماده شد. راست‌کلیک روی پیام...")
        await human_sleep(1.5, 0.4)

        try:
            # ۱. راست‌کلیک روی مرکز حباب پیام
            box = await message_locator.bounding_box()
            if box:
                x = box['x'] + box['width'] / 2
                y = box['y'] + box['height'] / 2
                await page.mouse.click(x, y, button='right')
                logger.info(f"   🖱️ راست‌کلیک روی پیام انجام شد در ({x:.0f}, {y:.0f})")
            else:
                await message_locator.click(button='right')
                logger.info(f"   🖱️ راست‌کلیک با force انجام شد")

            # ۲. صبر برای ظاهر شدن منوی context
            await human_sleep(1.5, 0.3)

            # ۳. اسکرین‌شات از صفحه
            screenshot_path = self.debug_dir / f"rightclick_{post_id}.png"
            await page.screenshot(path=screenshot_path, full_page=False)
            logger.info(f"   📸 اسکرین‌شات ذخیره شد: {screenshot_path.name}")

            # ۴. بستن منو با کلیک چپ در نقطه‌ای امن
            await page.mouse.click(10, 10)
            await human_sleep(0.3, 0.2)

        except Exception as e:
            logger.warning(f"   ⚠️ خطا در پردازش پست {post_id}: {e}")
            try:
                path = self.debug_dir / f"error_{post_id}.png"
                await page.screenshot(path=path)
                logger.info(f"   📸 اسکرین‌شات خطا: {path.name}")
            except:
                pass

        logger.info(f"   ✅ پایان بررسی پست {post_id}")