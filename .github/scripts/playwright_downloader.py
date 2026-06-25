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
    """خواب انسانی با کمی تصادف"""
    time = base * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, time))


class PlaywrightDownloader:
    """
    دانلود مدیا از طریق راست‌کلیک روی مدیا و انتخاب گزینهٔ «Download» از منوی سفارشی تلگرام.
    کاملاً انسانی و بدون وابستگی به Media Viewer.
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

    async def _process_post(self, page: Page, post_id: str, media_map: Dict[str, List[str]]) -> None:
        """پردازش یک پست و دانلود تمام مدیاهای visible با راست‌کلیک"""
        logger.info(f"📍 شروع پردازش پست {post_id}")

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

        # برای هر المان visible، راست‌کلیک و انتخاب Download
        for i in visible_indices:
            logger.info(f"   ▶️ شروع دانلود با راست‌کلیک برای المان {i} از پست {post_id}")
            try:
                msg_locator = page.locator(f'[data-message-id="{post_id}"]').first
                current_element = msg_locator.locator(
                    'div.media-photo, div.media-video, div.document, a.media-photo, '
                    'video, img[src], div[class*="media"]'
                ).nth(i)

                await human_sleep(1.3, 0.4)
                await current_element.wait_for(state="visible", timeout=12000)
                logger.debug(f"   ✅ المان {i} visible شد")

                # راست‌کلیک و دانلود
                await self._context_menu_download(page, current_element, post_id, i, media_map)
            except Exception as e:
                logger.warning(f"   ⚠️ المان {i} پست {post_id} رد شد: {e}")
                continue

        if post_id in media_map:
            logger.info(f"📦 پست {post_id}: {len(media_map[post_id])} رسانه دانلود شد.")

    async def _context_menu_download(self, page: Page, element, post_id: str,
                                     idx: int, media_map: Dict[str, List[str]]):
        """کلیک راست روی المان و انتخاب گزینهٔ Download از منوی سفارشی"""
        download_occurred = [False]

        async def on_download(download: Download):
            download_occurred[0] = True
            logger.info(f"   📥 رویداد دانلود فعال شد: {download.suggested_filename}")
            await self._save_download(download, post_id, idx, media_map)

        page.on("download", on_download)

        try:
            # ۱. راست‌کلیک روی المان
            box = await element.bounding_box()
            if box:
                x = box['x'] + box['width'] / 2
                y = box['y'] + box['height'] / 2
                await page.mouse.click(x, y, button='right')
                logger.info(f"   🖱️ راست‌کلیک انجام شد در ({x:.0f}, {y:.0f})")
            else:
                await element.click(button='right')
                logger.info(f"   🖱️ راست‌کلیک با force انجام شد")

            # ۲. منتظر ظاهر شدن منوی سفارشی (معمولاً div با role="menu" یا مشابه)
            #     چند سلکتور رایج برای منوی تلگرام
            menu_selector = '[role="menu"], [role="listbox"], div[class*="context-menu"], div[class*="ContextMenu"], div[class*="popup"]'
            await page.wait_for_selector(menu_selector, timeout=5000)
            await human_sleep(0.5, 0.2)

            # ۳. پیدا کردن گزینهٔ دانلود
            #     ممکن است عبارت "Download" یا "Save image as…" یا "Save as…" باشد
            download_option = page.locator(
                '[role="menuitem"]:has-text("Download"), '
                '[role="menuitem"]:has-text("Save"), '
                'button:has-text("Download"), '
                'div:has-text("Download")'
            ).first

            if await download_option.count() == 0:
                # شاید منو ساختار دیگری داشته باشد – جستجوی کلی‌تر
                download_option = page.get_by_text("Download", exact=False).first

            if await download_option.count() > 0:
                await download_option.click()
                logger.info(f"   ✅ کلیک روی گزینهٔ دانلود انجام شد")
                # صبر برای شروع دانلود
                await human_sleep(3, 0.5)
            else:
                logger.warning("   ⚠️ گزینهٔ دانلود در منوی راست‌کلیک پیدا نشد!")
        except Exception as e:
            logger.warning(f"   ❌ خطا در راست‌کلیک/دانلود: {e}")
        finally:
            page.remove_listener("download", on_download)

        # اگر دانلود از طریق راست‌کلیک موفق نشد، به روش مستقیم fallback کن
        if not download_occurred[0]:
            logger.info(f"   🔄 دانلود از طریق راست‌کلیک ناموفق — Fallback به دانلود مستقیم")
            await self._direct_download_from_element(page, element, post_id, idx, media_map)

    async def _direct_download_from_element(self, page: Page, element, post_id: str,
                                            idx: int, media_map: Dict[str, List[str]]):
        """Fallback: استخراج لینک و دانلود مستقیم (همان روش قبلی)"""
        links = await element.evaluate('''(el) => {
            const links = new Set();
            const add = (url) => { if (url && url.startsWith('http')) links.add(url); };
            el.querySelectorAll('img[src]').forEach(i => add(i.src));
            el.querySelectorAll('video source[src]').forEach(s => add(s.src));
            el.querySelectorAll('a[href*="/file/"]').forEach(a => add(a.href));
            return Array.from(links);
        }''')
        if not links:
            return
        for link in links:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await page.request.get(link, headers={"Referer": "https://web.telegram.org/"})
                    if resp.ok:
                        body = await resp.body()
                        if len(body) > self.max_bytes:
                            logger.info(f"⏩ رد شد (حجم {len(body)/1024/1024:.1f}MB)")
                            break
                        ext = self._guess_ext(resp, link)
                        base_name = f"{post_id}_{idx}.{ext}"
                        filepath = self.media_dir / base_name
                        counter = 1
                        while filepath.exists():
                            filepath = self.media_dir / f"{post_id}_{idx}_{counter}.{ext}"
                            counter += 1
                        with open(filepath, 'wb') as f:
                            f.write(body)
                        logger.info(f"✅ مستقیم: {filepath.name} ({len(body)/1024/1024:.1f} MB)")
                        media_map.setdefault(post_id, []).append(f"media/{filepath.name}")
                        break
                except Exception as e:
                    logger.error(f"❌ خطای دانلود: {e}")
                if attempt < self.max_retries:
                    await human_sleep(2, 0.5)

    async def _save_download(self, download: Download, post_id: str,
                             idx: int, media_map: Dict[str, List[str]]):
        """ذخیرهٔ فایل و ثبت در media_map"""
        try:
            suggested = download.suggested_filename
            ext = suggested.rsplit('.', 1)[-1] if '.' in suggested else "bin"
            base_name = f"{post_id}_{idx}.{ext}"
            filepath = self.media_dir / base_name
            counter = 1
            while filepath.exists():
                filepath = self.media_dir / f"{post_id}_{idx}_{counter}.{ext}"
                counter += 1
            await download.save_as(str(filepath))
            size_mb = filepath.stat().st_size / 1024 / 1024 if filepath.exists() else 0
            if size_mb > self.max_bytes / 1024 / 1024:
                logger.info(f"⏩ {filepath.name} رد شد (حجم {size_mb:.1f}MB)")
                filepath.unlink(missing_ok=True)
            else:
                logger.info(f"✅ دانلود شد: {filepath.name} ({size_mb:.1f} MB)")
                media_map.setdefault(post_id, []).append(f"media/{filepath.name}")
        except Exception as e:
            logger.error(f"❌ ذخیره دانلود: {e}")

    def _guess_ext(self, response, url: str) -> str:
        ct = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if ct in self.MIME_TO_EXT:
            return self.MIME_TO_EXT[ct]
        path = url.split("?")[0]
        if '.' in path:
            ext = path.rsplit('.', 1)[-1][:5]
            if ext.isalnum():
                return ext
        return "bin"