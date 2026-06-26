#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import random
from pathlib import Path
from typing import List, Dict, Optional

from playwright.async_api import Page, Download

logger = logging.getLogger("TelegramScraper")


async def human_sleep(base: float, jitter: float = 0.4):
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class PlaywrightDownloader:
    """
    دانلود مدیا با راست‌کلیک روی پیام و انتخاب گزینهٔ «Download» از منوی context.
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

        self.debug_dir = self.media_dir.parent / "debug_rightclick"
        self.debug_dir.mkdir(parents=True, exist_ok=True)

    async def download_all(self, page: Page, context, post_ids: List[str],
                           media_map: Optional[Dict[str, List[str]]] = None) -> None:
        if media_map is None:
            media_map = {}
        if not post_ids:
            logger.info("هیچ پستی برای دانلود وجود ندارد.")
            return

        for idx, post_id in enumerate(post_ids, start=1):
            logger.info(f"📥 [{idx}/{len(post_ids)}] پست {post_id}")
            try:
                await asyncio.wait_for(
                    self._process_post(page, post_id, media_map),
                    timeout=75
                )
            except asyncio.TimeoutError:
                logger.warning(f"⏰ پست {post_id} تایم‌اوت کلی شد، رد می‌شود.")
            except Exception as e:
                logger.error(f"❌ خطا در پست {post_id}: {e}")
            if idx < len(post_ids):
                await human_sleep(self.delay, 0.5)

    async def _process_post(self, page: Page, post_id: str,
                            media_map: Dict[str, List[str]]) -> None:
        logger.info(f"📍 شروع دانلود پست {post_id}")

        message_locator = page.locator(f'[data-message-id="{post_id}"]').first

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

        logger.info(f"   📍 پست {post_id} آماده شد. راست‌کلیک و دانلود...")
        await human_sleep(1.5, 0.4)

        downloaded_files = []
        file_index = 0

        async def on_download(download: Download):
            nonlocal file_index
            try:
                suggested = download.suggested_filename
                ext = suggested.rsplit('.', 1)[-1] if '.' in suggested else "bin"
                base_name = f"{post_id}_{file_index}.{ext}"
                filepath = self.media_dir / base_name
                counter = 1
                while filepath.exists():
                    filepath = self.media_dir / f"{post_id}_{file_index}_{counter}.{ext}"
                    counter += 1
                await download.save_as(str(filepath))
                size_mb = filepath.stat().st_size / 1024 / 1024 if filepath.exists() else 0
                if size_mb > self.max_bytes / 1024 / 1024:
                    logger.info(f"⏩ {filepath.name} رد شد (حجم {size_mb:.1f}MB)")
                    filepath.unlink(missing_ok=True)
                else:
                    logger.info(f"✅ دانلود شد: {filepath.name} ({size_mb:.1f} MB)")
                    downloaded_files.append(f"media/{filepath.name}")
                    file_index += 1
            except Exception as e:
                logger.error(f"❌ خطا در ذخیرهٔ دانلود: {e}")

        page.on("download", on_download)

        try:
            # ۱. راست‌کلیک روی پیام
            box = await message_locator.bounding_box()
            if box:
                x = box['x'] + box['width'] / 2
                y = box['y'] + box['height'] / 2
                await page.mouse.click(x, y, button='right')
                logger.info(f"   🖱️ راست‌کلیک روی پیام انجام شد در ({x:.0f}, {y:.0f})")
            else:
                await message_locator.click(button='right')
                logger.info(f"   🖱️ راست‌کلیک با force انجام شد")

            # ۲. منتظر منوی context (با state="attached" برای مقاومت در برابر opacity)
            menu_selector = '[role="menu"], [role="listbox"], div[class*="context-menu"], div[class*="ContextMenu"], div[class*="popup"]'
            try:
                await page.wait_for_selector(menu_selector, state="attached", timeout=6000)
                await human_sleep(0.8, 0.3)
            except Exception:
                logger.warning("   ⚠️ منوی context ظاهر نشد. رد کردن این پست.")
                return

            # ۳. پیدا کردن و کلیک روی گزینهٔ «Download»
            download_option = page.locator(
                '[role="menuitem"]:has-text("Download"), '
                '[role="menuitem"]:has-text("Save"), '
                'button:has-text("Download"), '
                'div:has-text("Download")'
            ).first
            if await download_option.count() == 0:
                download_option = page.get_by_text("Download", exact=False).first

            if await download_option.count() > 0:
                await download_option.click()
                logger.info(f"   ✅ کلیک روی گزینهٔ دانلود انجام شد")

                # ۴. صبر برای دریافت همهٔ فایل‌ها (مخصوصاً آلبوم‌ها)
                await human_sleep(15.0, 0.2)
            else:
                logger.warning("   ⚠️ گزینهٔ دانلود در منوی راست‌کلیک پیدا نشد!")
        except Exception as e:
            logger.warning(f"   ❌ خطا در فرایند راست‌کلیک/دانلود: {e}")
            try:
                path = self.debug_dir / f"error_{post_id}.png"
                await page.screenshot(path=path)
                logger.info(f"   📸 اسکرین‌شات خطا: {path.name}")
            except:
                pass
        finally:
            try:
                await page.mouse.click(10, 10)
                await human_sleep(0.3, 0.2)
            except:
                pass
            page.remove_listener("download", on_download)

        if downloaded_files:
            media_map[post_id] = downloaded_files
            logger.info(f"📦 پست {post_id}: {len(downloaded_files)} رسانه دانلود شد.")