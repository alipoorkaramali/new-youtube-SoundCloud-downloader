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
    **نسخهٔ دیباگ راست‌کلیک**
    فقط راست‌کلیک روی مدیاها انجام می‌دهد، اسکرین‌شات می‌گیرد و هیچ دانلودی انجام نمی‌شود.
    هدف: بررسی ظاهر شدن منوی context و گزینه‌های آن.
    """

    MIME_TO_EXT = {
        "image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
        "image/webp": "webp", "video/mp4": "mp4", "video/webm": "webm",
        "audio/mpeg": "mp3", "audio/ogg": "ogg", "application/pdf": "pdf",
        "application/zip": "zip", "application/x-rar-compressed": "rar",
        "application/octet-stream": "bin",
    }

    def __init__(self, profile_dir: Path, media_dir: Path, max_bytes: int,
                 delay: float = 5.0, max_retries: int = 2):
        self.profile_dir = profile_dir
        self.media_dir = media_dir
        self.max_bytes = max_bytes
        self.delay = delay
        self.max_retries = max_retries
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # پوشهٔ مخصوص اسکرین‌شات‌های دیباگ راست‌کلیک
        self.debug_dir = self.media_dir.parent / "debug_rightclick"
        self.debug_dir.mkdir(parents=True, exist_ok=True)

    async def download_all(self, page: Page, context, post_ids: List[str],
                           media_map: Optional[Dict[str, List[str]]] = None) -> None:
        """حلقهٔ اصلی – فقط راست‌کلیک و اسکرین‌شات، بدون دانلود"""
        # media_map را نادیده می‌گیریم چون دانلودی در کار نیست
        if not post_ids:
            logger.info("هیچ پستی برای بررسی وجود ندارد.")
            return

        for idx, post_id in enumerate(post_ids, start=1):
            logger.info(f"📥 [{idx}/{len(post_ids)}] پست {post_id}")
            try:
                await asyncio.wait_for(
                    self._process_post(page, post_id),
                    timeout=75
                )
            except asyncio.TimeoutError:
                logger.warning(f"⏰ پست {post_id} تایم‌اوت کلی شد، رد می‌شود.")
            except Exception as e:
                logger.error(f"❌ خطا در پست {post_id}: {e}")
            if idx < len(post_ids):
                await human_sleep(self.delay, 0.5)

    async def _process_post(self, page: Page, post_id: str) -> None:
        """نمایش پست، سپس راست‌کلیک روی هر المان مدیا و اسکرین‌شات"""
        logger.info(f"📍 شروع بررسی پست {post_id}")

        message_locator = page.locator(f'[data-message-id="{post_id}"]').first

        # تلاش برای نمایان کردن پست
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

        logger.info(f"   📍 پست {post_id} آماده شد. منتظر لود کامل...")
        await human_sleep(2.2, 0.5)

        # استخراج المان‌های مدیا
        media_elements = message_locator.locator(
            'div.media-photo, div.media-video, div.document, a.media-photo, '
            'video, img[src], div[class*="media"]'
        )
        media_count = await media_elements.count()
        logger.info(f"   🔍 تعداد المان‌های مدیا یافت‌شده: {media_count}")
        if media_count == 0:
            logger.debug(f"📝 پست {post_id} بدون مدیا.")
            return

        # فیلتر visible
        visible_indices = []
        for i in range(media_count):
            try:
                el = media_elements.nth(i)
                if await el.is_visible(timeout=6000):
                    visible_indices.append(i)
                    logger.debug(f"   ✅ المان {i} visible است")
                else:
                    logger.debug(f"   ⚠️ المان {i} visible نیست")
            except Exception as e:
                logger.debug(f"   ❌ خطا در بررسی visibility المان {i}: {e}")

        if not visible_indices:
            logger.debug(f"📝 پست {post_id} مدیای visible ندارد.")
            return

        logger.info(f"🎯 {len(visible_indices)} مدیای واقعی در پست {post_id} یافت شد.")
        await human_sleep(1.8, 0.4)

        # برای هر المان visible: راست‌کلیک، اسکرین‌شات، سپس بستن منو
        for i in visible_indices:
            logger.info(f"   ▶️ راست‌کلیک روی المان {i} از پست {post_id}")
            try:
                msg_locator = page.locator(f'[data-message-id="{post_id}"]').first
                current_element = msg_locator.locator(
                    'div.media-photo, div.media-video, div.document, a.media-photo, '
                    'video, img[src], div[class*="media"]'
                ).nth(i)

                await human_sleep(1.3, 0.4)
                await current_element.wait_for(state="visible", timeout=12000)
                logger.debug(f"   ✅ المان {i} visible شد")

                # انجام راست‌کلیک
                box = await current_element.bounding_box()
                if box:
                    x = box['x'] + box['width'] / 2
                    y = box['y'] + box['height'] / 2
                    await page.mouse.click(x, y, button='right')
                    logger.info(f"   🖱️ راست‌کلیک انجام شد در ({x:.0f}, {y:.0f})")
                else:
                    await current_element.click(button='right')
                    logger.info(f"   🖱️ راست‌کلیک با force انجام شد")

                # کمی صبر برای ظاهر شدن منو
                await human_sleep(1.5, 0.3)

                # اسکرین‌شات از کل صفحه (با منوی باز)
                screenshot_path = self.debug_dir / f"rightclick_{post_id}_{i}.png"
                await page.screenshot(path=screenshot_path, full_page=False)
                logger.info(f"   📸 اسکرین‌شات ذخیره شد: {screenshot_path.name}")

                # بستن منوی context (با کلید Escape)
                await page.keyboard.press("Escape")
                await human_sleep(0.5, 0.2)

            except Exception as e:
                logger.warning(f"   ⚠️ خطا در پردازش المان {i} پست {post_id}: {e}")
                # در صورت خطا هم یک اسکرین‌شات بگیریم
                try:
                    path = self.debug_dir / f"error_{post_id}_{i}.png"
                    await page.screenshot(path=path)
                    logger.info(f"   📸 اسکرین‌شات خطا: {path.name}")
                except:
                    pass
                continue

        logger.info(f"   ✅ پایان بررسی پست {post_id}")

    # تمام متدهای دانلود (save, direct, context_menu) در این نسخه کامنت شده یا حذف شده‌اند.
    # فقط _guess_ext (اگر لازم باشد) می‌تواند باقی بماند.