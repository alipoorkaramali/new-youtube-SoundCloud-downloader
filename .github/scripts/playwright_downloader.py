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
    دانلود مدیا مستقیماً از صفحهٔ کانال (بدون باز کردن لینک جداگانه).
    نسخهٔ دیباگ پیشرفته: ضربدر قرمز روی نقطهٔ کلیک برای تشخیص دقیق.
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

        # پوشهٔ مخصوص دیباگ
        self.debug_dir = self.media_dir.parent / "debug_clicks"
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

    async def _process_post(self, page: Page, post_id: str, media_map: Dict[str, List[str]]) -> None:
        """پردازش یک پست با تلاش قوی‌تر برای نمایش و فیلتر مدیاهای واقعی"""
        logger.info(f"📍 شروع پردازش پست {post_id}")

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

        logger.info(f"   📍 پست {post_id} آماده شد. منتظر لود کامل...")
        await human_sleep(2.2, 0.5)

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

        for i in visible_indices:
            logger.info(f"   ▶️ شروع پردازش المان {i} از پست {post_id}")
            try:
                msg_locator = page.locator(f'[data-message-id="{post_id}"]').first
                current_element = msg_locator.locator(
                    'div.media-photo, div.media-video, div.document, a.media-photo, '
                    'video, img[src], div[class*="media"]'
                ).nth(i)

                await human_sleep(1.3, 0.4)
                await current_element.wait_for(state="visible", timeout=12000)
                logger.debug(f"   ✅ المان {i} visible شد")

                media_type = await self._detect_media_type(current_element)
                logger.info(f"   🏷️ نوع مدیا تشخیص داده شد: {media_type}")

                if media_type == "document":
                    await self._download_document(page, current_element, post_id, i, media_map)
                else:
                    await self._download_media_viewer(page, current_element, post_id, i, media_map)
            except Exception as e:
                logger.warning(f"   ⚠️ المان {i} پست {post_id} رد شد: {e}")
                continue

        if post_id in media_map:
            logger.info(f"📦 پست {post_id}: {len(media_map[post_id])} رسانه دانلود شد.")

    async def _detect_media_type(self, element) -> str:
        has_img = await element.evaluate("el => !!el.querySelector('img')")
        has_video = await element.evaluate("el => !!el.querySelector('video, div.media-video')")
        has_file = await element.evaluate("el => !!el.querySelector('a[href*=\"/file/\"]')")
        logger.debug(f"   🔎 تشخیص: img={has_img}, video={has_video}, file={has_file}")
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
        logger.info(f"   📄 دانلود فایل (document) شروع شد")
        download_occurred = [False]

        async def on_download(download: Download):
            download_occurred[0] = True
            logger.info(f"   📥 رویداد دانلود فعال شد: {download.suggested_filename}")
            await self._save_download(download, post_id, idx, media_map)

        page.on("download", on_download)
        try:
            await self._human_click(element, debug_name=f"file_{post_id}_{idx}", draw_cross=True)
            logger.info(f"   ✅ کلیک روی المان فایل انجام شد")
            await human_sleep(3, 0.4)
            if not download_occurred[0]:
                download_btn = element.locator(
                    'button[aria-label="Download"], [title="Download"], .icon-download, [class*="download"]'
                ).first
                btn_count = await download_btn.count()
                logger.info(f"   🔍 تعداد دکمه دانلود فایل: {btn_count}")
                if btn_count > 0:
                    await self._human_click(download_btn, debug_name=f"file_download_btn_{post_id}_{idx}", draw_cross=True)
                    logger.info(f"   ✅ کلیک روی دکمه دانلود فایل انجام شد")
                    await human_sleep(3, 0.4)
        except Exception as e:
            logger.warning(f"   ⚠️ خطا در کلیک فایل: {e}")
        finally:
            page.remove_listener("download", on_download)

        if not download_occurred[0]:
            logger.info(f"   🔄 رویداد دانلود فعال نشد — رفتن به fallback")
            await self._direct_download_from_element(page, element, post_id, idx, media_map)

    async def _download_media_viewer(self, page: Page, element, post_id: str,
                                     idx: int, media_map: Dict[str, List[str]]):
        logger.info(f"   🖼️ دانلود عکس/ویدیو با Media Viewer شروع شد")
        try:
            await self._human_click(element, debug_name=f"media_{post_id}_{idx}", draw_cross=True)
            logger.info(f"   ✅ کلیک روی عکس/ویدیو انجام شد — منتظر Media Viewer...")
            await human_sleep(1.5, 0.4)
        except Exception as e:
            logger.warning(f"   ❌ کلیک اولیه ناموفق: {e}")
            return

        viewer_selectors = [
            'div.media-viewer', 'div[class*="MediaViewer"]',
            'div[class*="lightbox"]', 'div.media-viewer-content'
        ]
        viewer_selector = ", ".join(viewer_selectors)
        try:
            await page.wait_for_selector(viewer_selector, timeout=12000)
            logger.info(f"   ✅ Media Viewer باز شد")
            await human_sleep(2.2, 0.5)
        except Exception as e:
            logger.warning(f"   ❌ Media Viewer باز نشد: {e}")
            # اسکرین‌شات بعد از شکست
            debug_path = self.debug_dir / f"debug_viewer_failed_{post_id}_{idx}.png"
            await page.screenshot(path=debug_path)
            logger.info(f"   📸 اسکرین‌شات بعد از شکست: {debug_path.name}")
            await self._direct_download_from_element(page, element, post_id, idx, media_map)
            return

        album_idx = idx
        while True:
            current_album_idx = album_idx
            download_occurred = [False]

            async def on_download(download: Download):
                download_occurred[0] = True
                logger.info(f"   📥 رویداد دانلود در آلبوم: {download.suggested_filename}")
                await self._save_download(download, post_id, current_album_idx, media_map)

            page.on("download", on_download)
            try:
                download_btn = page.locator(
                    'button[aria-label="Download"], [title="Download"], .btn-download, button:has(svg)'
                ).first
                btn_count = await download_btn.count()
                logger.info(f"   🔍 تعداد دکمه دانلود در Media Viewer: {btn_count}")
                if btn_count > 0:
                    await self._human_click(download_btn, debug_name=f"download_btn_{post_id}_{current_album_idx}", draw_cross=True)
                    logger.info(f"   ✅ کلیک روی دکمه دانلود انجام شد")
                    await human_sleep(3, 0.5)
                else:
                    logger.warning("   ⚠️ دکمه دانلود در Media Viewer پیدا نشد!")
            except Exception as e:
                logger.warning(f"   ❌ خطا در کلیک دکمه دانلود: {e}")
            finally:
                page.remove_listener("download", on_download)

            album_idx += 1

            next_btn = page.locator(
                'button[aria-label="Next"], [title="Next"], .btn-next, '
                'div[class*="nav-next"], button:has(svg[class*="arrow"])'
            ).first
            next_count = await next_btn.count()
            logger.debug(f"   🔍 دکمه Next: {next_count}")
            if next_count > 0:
                try:
                    await self._human_click(next_btn, debug_name=f"next_{post_id}_{album_idx}")
                    logger.info(f"   ➡️ رفتن به آیتم بعدی آلبوم")
                    await human_sleep(1.5, 0.4)
                except Exception as e:
                    logger.warning(f"   ⚠️ خطا در کلیک Next: {e}")
                    break
            else:
                logger.debug(f"   🏁 آلبوم به پایان رسید")
                break

        await self._close_media_viewer(page)

    async def _close_media_viewer(self, page: Page):
        logger.debug(f"   🚪 بستن Media Viewer")
        close_btn = page.locator('button[aria-label="Close"], [title="Close"], .btn-close').first
        if await close_btn.count() > 0:
            try:
                await close_btn.click(timeout=3000)
                await human_sleep(0.5, 0.2)
                logger.debug(f"   ✅ با دکمه بسته شد")
                return
            except Exception:
                pass
        try:
            await page.keyboard.press("Escape")
            await human_sleep(0.5, 0.2)
            logger.debug(f"   ✅ با کلید Escape بسته شد")
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

    async def _human_click(self, locator, debug_name: str = "", draw_cross: bool = False):
        """کلیک همراه با حرکت موس و امکان رسم ضربدر قرمز"""
        try:
            await locator.scroll_into_view_if_needed()
            box = await locator.bounding_box()
            if box:
                x = box['x'] + box['width'] / 2 + random.uniform(-8, 8)
                y = box['y'] + box['height'] / 2 + random.uniform(-8, 8)
                await locator.page.mouse.move(x, y)

                if draw_cross and debug_name:
                    await self._draw_debug_cross(locator.page, x, y, f"{debug_name}_cross")
            else:
                x = y = None

            await human_sleep(0.6, 0.3)

            if debug_name and not draw_cross:
                path = self.debug_dir / f"debug_click_{debug_name}.png"
                await locator.page.screenshot(path=path)
                logger.info(f"   📸 اسکرین‌شات قبل از کلیک ذخیره شد: {path.name}")

            await locator.click(timeout=8000, force=True)
            logger.info(f"   ✅ کلیک انجام شد ({debug_name})")
        except Exception as e:
            logger.warning(f"   ⚠️ کلیک ناموفق ({debug_name}): {e}")
            await locator.click(timeout=8000, force=True)

    async def _draw_debug_cross(self, page: Page, x: float, y: float, name: str):
        """رسم ضربدر قرمز و ذخیره اسکرین‌شات"""
        # افزودن عنصر ضربدر به صورت موقت
        await page.evaluate(f"""
            () => {{
                const container = document.createElement('div');
                container.id = 'debug-cross-container';
                container.style.position = 'fixed';
                container.style.left = '0px';
                container.style.top = '0px';
                container.style.zIndex = '99999';
                container.style.pointerEvents = 'none';
                document.body.appendChild(container);

                const cross = document.createElement('div');
                cross.style.position = 'absolute';
                cross.style.left = '{x}px';
                cross.style.top = '{y}px';
                cross.style.width = '24px';
                cross.style.height = '24px';
                cross.style.transform = 'translate(-50%, -50%)';
                cross.innerHTML = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <line x1="2" y1="2" x2="22" y2="22" stroke="red" stroke-width="3"/>
                    <line x1="22" y1="2" x2="2" y2="22" stroke="red" stroke-width="3"/>
                </svg>`;
                container.appendChild(cross);
            }}
        """)
        path = self.debug_dir / f"debug_click_{name}.png"
        await page.screenshot(path=path)
        logger.info(f"   📸 اسکرین‌شات با ضربدر ذخیره شد: {path.name}")
        # حذف ضربدر
        await page.evaluate("""
            () => {
                const container = document.getElementById('debug-cross-container');
                if (container) container.remove();
            }
        """)

    async def _direct_download_from_element(self, page: Page, element, post_id: str,
                                            idx: int, media_map: Dict[str, List[str]]):
        logger.info(f"   🔄 Fallback: استخراج لینک‌های مستقیم شروع شد")
        links = await element.evaluate('''(el) => {
            const links = new Set();
            const add = (url) => { if (url && url.startsWith('http')) links.add(url); };
            el.querySelectorAll('img[src]').forEach(i => add(i.src));
            el.querySelectorAll('video source[src]').forEach(s => add(s.src));
            el.querySelectorAll('a[href*="/file/"]').forEach(a => add(a.href));
            return Array.from(links);
        }''')
        logger.info(f"   🔗 {len(links)} لینک در fallback پیدا شد")
        if not links:
            logger.debug("   ⚠️ هیچ لینکی پیدا نشد.")
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
                    else:
                        logger.warning(f"⚠️ HTTP {resp.status} برای {link}")
                except Exception as e:
                    logger.error(f"❌ خطای دانلود: {e}")
                if attempt < self.max_retries:
                    await human_sleep(2, 0.5)

    def _guess_ext(self, response, url: str) -> str:
        ct = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if ct in self.MIME_TO_EXT:
            return self.MIME_TO_EXT[ct]
        path = url.