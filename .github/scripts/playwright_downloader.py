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
    دانلود مدیا مستقیماً از صفحهٔ کانال (بدون باز کردن لینک جداگانه).
    رفتار کاملاً انسانی: کلیک روی مدیا، Media Viewer، دانلود، پیمایش آلبوم و fallback.
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
                    timeout=45
                )
            except asyncio.TimeoutError:
                logger.warning(f"⏰ پست {post_id} تایم‌اوت شد، رد می‌شود.")
            except Exception as e:
                logger.error(f"❌ خطا در پست {post_id}: {e}")
            if idx < len(post_ids):
                await human_sleep(self.delay, 0.5)

    async def _process_post(self, page: Page, post_id: str,
                            media_map: Dict[str, List[str]]) -> None:
        message_locator = page.locator(f'[data-message-id="{post_id}"]').first

        try:
            await message_locator.scroll_into_view_if_needed(timeout=10000)
            await human_sleep(0.8, 0.3)
            await message_locator.wait_for(state="visible", timeout=15000)
        except Exception:
            try:
                await page.evaluate(f'''(id) => {{
                    const el = document.querySelector(`[data-message-id="${{id}}"]`);
                    if (el) el.scrollIntoView({{ behavior: "smooth", block: "center" }});
                }}''', post_id)
                await human_sleep(1.5, 0.4)
                await message_locator.wait_for(state="visible", timeout=10000)
            except Exception as e:
                logger.warning(f"⚠️ المان پست {post_id} پیدا نشد (حتی با اسکرول): {e}")
                return

        media_elements = message_locator.locator(
            'div.media-photo, div.media-video, div.document, a.media-photo, '
            'video, img[src], div[class*="media"]'
        )
        media_count = await media_elements.count()
        if media_count == 0:
            logger.debug(f"📝 پست {post_id} بدون مدیا.")
            return

        logger.info(f"🎯 {media_count} المان مدیا در پست {post_id} یافت شد.")
        await human_sleep(0.5, 0.2)

        for i in range(media_count):
            msg_locator = page.locator(f'[data-message-id="{post_id}"]').first
            current_element = msg_locator.locator(
                'div.media-photo, div.media-video, div.document, a.media-photo, '
                'video, img[src], div[class*="media"]'
            ).nth(i)

            media_type = await self._detect_media_type(current_element)
            if media_type == "document":
                await self._download_document(page, current_element, post_id, i, media_map)
            else:
                await self._download_media_viewer(page, current_element, post_id, i, media_map)

        if post_id in media_map:
            logger.info(f"📦 پست {post_id}: {len(media_map[post_id])} رسانه دانلود شد.")

    async def _detect_media_type(self, element) -> str:
        has_img = await element.evaluate("el => !!el.querySelector('img')")
        has_video = await element.evaluate("el => !!el.querySelector('video, div.media-video')")
        has_file = await element.evaluate("el => !!el.querySelector('a[href*=\"/file/\"]')")
        if has_file:
            return "document"
        if has_video:
            return "video"
        if has_img:
            return "image"
        class_attr = await element.get_attribute("class") or ""
        if "document" in class_attr:
            return "document"
        return "image"

    async def _download_document(self, page: Page, element, post_id: str,
                                 idx: int, media_map: Dict[str, List[str]]):
        download_occurred = [False]

        async def on_download(download: Download):
            download_occurred[0] = True
            await self._save_download(download, post_id, idx, media_map)

        page.on("download", on_download)
        try:
            await self._human_click(element)
            await human_sleep(3, 0.4)
            if not download_occurred[0]:
                download_btn = element.locator(
                    'button[aria-label="Download"], [title="Download"], .icon-download, [class*="download"]'
                ).first
                if await download_btn.count() > 0:
                    await self._human_click(download_btn)
                    await human_sleep(3, 0.4)
        except Exception as e:
            logger.debug(f"خطا در کلیک فایل: {e}")
        finally:
            page.remove_listener("download", on_download)

        if not download_occurred[0]:
            await self._direct_download_from_element(page, element, post_id, idx, media_map)

    async def _download_media_viewer(self, page: Page, element, post_id: str,
                                     idx: int, media_map: Dict[str, List[str]]):
        try:
            await self._human_click(element)
        except Exception as e:
            logger.debug(f"کلیک اولیه ناموفق: {e}")
            return

        viewer_selectors = [
            'div.media-viewer', 'div[class*="MediaViewer"]',
            'div[class*="lightbox"]', 'div.media-viewer-content'
        ]
        viewer_selector = ", ".join(viewer_selectors)
        try:
            await page.wait_for_selector(viewer_selector, timeout=8000)
        except Exception:
            logger.debug("Media Viewer باز نشد.")
            await self._direct_download_from_element(page, element, post_id, idx, media_map)
            return

        album_idx = idx
        while True:
            current_album_idx = album_idx
            download_occurred = [False]

            async def on_download(download: Download):
                download_occurred[0] = True
                await self._save_download(download, post_id, current_album_idx, media_map)

            page.on("download", on_download)
            try:
                download_btn = page.locator(
                    'button[aria-label="Download"], [title="Download"], .btn-download'
                ).first
                if await download_btn.count() > 0:
                    await self._human_click(download_btn)
                    await human_sleep(2, 0.3)
                else:
                    logger.debug("دکمهٔ دانلود در Media Viewer پیدا نشد.")
            except Exception as e:
                logger.debug(f"خطا در دانلود آیتم آلبوم: {e}")
            finally:
                page.remove_listener("download", on_download)

            album_idx += 1

            next_btn = page.locator(
                'button[aria-label="Next"], [title="Next"], .btn-next, '
                'div[class*="nav-next"], button:has(svg[class*="arrow"])'
            ).first
            if await next_btn.count() > 0:
                try:
                    await self._human_click(next_btn)
                    await human_sleep(1.5, 0.4)
                except Exception:
                    break
            else:
                break

        await self._close_media_viewer(page)

    async def _close_media_viewer(self, page: Page):
        close_btn = page.locator('button[aria-label="Close"], [title="Close"], .btn-close').first
        if await close_btn.count() > 0:
            try:
                await close_btn.click(timeout=3000)
                await human_sleep(0.5, 0.2)
                return
            except Exception:
                pass
        try:
            await page.keyboard.press("Escape")
            await human_sleep(0.5, 0.2)
        except Exception:
            pass

    async def _save_download(self, download: Download, post_id: str,
                             idx: int, media_map: Dict[str, List[str]]):
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

    async def _human_click(self, locator):
        try:
            await locator.scroll_into_view_if_needed()
            box = await locator.bounding_box()
            if box:
                x = box['x'] + box['width'] / 2 + random.uniform(-5, 5)
                y = box['y'] + box['height'] / 2 + random.uniform(-5, 5)
                await locator.page.mouse.move(x, y)
            await human_sleep(0.3, 0.4)
            await locator.click(timeout=5000, force=True)
        except Exception:
            await locator.click(timeout=5000, force=True)

    async def _direct_download_from_element(self, page: Page, element, post_id: str,
                                            idx: int, media_map: Dict[str, List[str]]):
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