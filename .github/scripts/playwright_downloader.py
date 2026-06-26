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
    موقعیت گزینه با جستجوی دقیق متن «Download» مانند جستجوی نام کانال پیدا می‌شود.
    پس از کلیک، با یک روش تطبیقی منتظر می‌ماند تا همهٔ فایل‌ها دریافت شوند.
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
                    timeout=600
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

        # ──────────────── نمایش پست ────────────────
        success = False
        for attempt in range(5):
            try:
                logger.debug(f"   🔄 تلاش {attempt+1} برای نمایان کردن پست")
                # ابتدا یک بار ساده اسکرول، سپس با margine اجباری
                await message_locator.scroll_into_view_if_needed(timeout=20000)
                if attempt == 0:
                    # دفعه اول کمی بیشتر صبر
                    await human_sleep(2.0, 0.4)
                else:
                    await human_sleep(1.0, 0.3)
                await message_locator.wait_for(state="visible", timeout=20000)
                await human_sleep(0.8, 0.3)

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
                    # 🌟 عکس از وضعیت صفحه وقتی پست پیدا نشد
                    path = self.debug_dir / f"post_not_found_{post_id}.png"
                    await page.screenshot(path=path)
                    logger.warning(f"⚠️ پست {post_id} بعد از ۵ تلاش پیدا نشد. اسکرین‌شات: {path.name}")
                    return

        if not success:
            return

        logger.info(f"   📍 پست {post_id} آماده شد. راست‌کلیک و دانلود...")
        await human_sleep(1.5, 0.4)

        # شمارش مدیای visible (فقط برای اطلاع)
        media_elements = message_locator.locator(
            'div.media-photo, div.media-video, div.document, a.media-photo, '
            'video, img[src], div[class*="media"]'
        )
        visible_count = 0
        try:
            all_media = await media_elements.count()
            for i in range(all_media):
                if await media_elements.nth(i).is_visible(timeout=3000):
                    visible_count += 1
        except Exception:
            visible_count = 1
        logger.info(f"   🖼️ تعداد مدیای visible (تقریبی): {visible_count}")

        # لیست فایل‌های دانلودشده و listener
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
            # ۱. راست‌کلیک (با دو تلاش در صورت نیاز)
            menu_appeared = False
            for right_attempt in range(2):
                # کلیک راست روی مرکز حباب
                box = await message_locator.bounding_box()
                if box:
                    x = box['x'] + box['width'] / 2
                    y = box['y'] + box['height'] / 2
                    await page.mouse.click(x, y, button='right')
                    logger.info(f"   🖱️ راست‌کلیک روی پیام انجام شد در ({x:.0f}, {y:.0f}) (تلاش {right_attempt+1})")
                else:
                    await message_locator.click(button='right')
                    logger.info(f"   🖱️ راست‌کلیک با force (تلاش {right_attempt+1})")

                # ۲. منتظر منوی context (با timeout کوتاه)
                menu_selector = '[role="menu"], [role="listbox"], div[class*="context-menu"], div[class*="ContextMenu"], div[class*="popup"]'
                try:
                    await page.wait_for_selector(menu_selector, state="attached", timeout=5000 if right_attempt == 0 else 7000)
                    menu_appeared = True
                    await human_sleep(0.8, 0.3)
                    break
                except Exception:
                    if right_attempt == 0:
                        logger.debug("   🔄 منو نیامد – صبر کوتاه و تلاش دوباره...")
                        await human_sleep(3.0, 0.5)
                    else:
                        # 🌟 عکس از وضعیت صفحه وقتی منو اصلاً باز نشد
                        path = self.debug_dir / f"menu_failed_{post_id}.png"
                        await page.screenshot(path=path)
                        logger.warning(f"   ⚠️ منوی context بعد از ۲ تلاش ظاهر نشد. اسکرین‌شات: {path.name}")

            if not menu_appeared:
                logger.warning("   ❌ رد کردن این پست به دلیل عدم نمایش منو.")
                return

            # ۳. یافتن گزینهٔ "Download" (مانند قبل)
            download_coords = await page.evaluate('''() => {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
                let node;
                while (node = walker.nextNode()) {
                    if (node.textContent.trim().toLowerCase() === 'download') {
                        const parent = node.parentElement;
                        if (parent && (parent.getAttribute('role') === 'menuitem' || parent.closest('[role="menu"]'))) {
                            const rect = parent.getBoundingClientRect();
                            return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                        }
                    }
                }
                const elements = document.querySelectorAll('[role="menuitem"], button, div');
                for (const el of elements) {
                    if (el.innerText.trim().toLowerCase() === 'download') {
                        const rect = el.getBoundingClientRect();
                        return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                    }
                }
                return null;
            }''')

            if download_coords:
                await self._draw_debug_cross(page, download_coords['x'], download_coords['y'], f"download_option_{post_id}")
                logger.info(f"   📸 اسکرین‌شات با ضربدر ذخیره شد")
                await page.mouse.click(download_coords['x'], download_coords['y'])
                logger.info(f"   ✅ کلیک روی گزینهٔ دانلود انجام شد (مختصات)")
            else:
                download_option = page.get_by_text("Download", exact=False).first
                if await download_option.count() > 0:
                    await download_option.click()
                    logger.info(f"   ✅ کلیک روی گزینهٔ دانلود (fallback)")
                else:
                    logger.warning("   ⚠️ گزینهٔ دانلود در منوی راست‌کلیک پیدا نشد!")

            # 🌟 انتظار تطبیقی (همان منطق قبلی)
            absolute_timeout = 600
            quiet_threshold = 15
            check_interval = 2
            waited = 0
            last_count = 0
            quiet_elapsed = 0

            while waited < absolute_timeout:
                await asyncio.sleep(check_interval)
                waited += check_interval
                current_count = len(downloaded_files)
                if current_count > last_count:
                    last_count = current_count
                    quiet_elapsed = 0
                    logger.debug(f"   ⏳ {waited}s – {current_count} فایل دریافت شد (فعالیت جدید)")
                else:
                    quiet_elapsed += check_interval
                    logger.debug(f"   ⏳ {waited}s – {current_count} فایل، {quiet_elapsed}s سکوت")

                if quiet_elapsed >= quiet_threshold:
                    logger.info(f"   🔇 {quiet_threshold} ثانیه بدون دانلود جدید – اتمام دانلودهای این پست")
                    break

            if waited >= absolute_timeout:
                logger.warning(f"   ⚠️ زمان کلی {absolute_timeout}s به پایان رسید – {len(downloaded_files)} فایل دریافت شد.")

        except Exception as e:
            logger.warning(f"   ❌ خطا در فرایند راست‌کلیک/دانلود: {e}")
            try:
                path = self.debug_dir / f"error_{post_id}.png"
                await page.screenshot(path=path)
                logger.info(f"   📸 اسکرین‌شات خطا: {path.name}")
            except:
                pass
        finally:
            # بستن منو و حذف listener
            try:
                await page.mouse.click(10, 10)
                await human_sleep(0.3, 0.2)
            except:
                pass
            page.remove_listener("download", on_download)

        if downloaded_files:
            media_map[post_id] = downloaded_files
            logger.info(f"📦 پست {post_id}: {len(downloaded_files)} رسانه دانلود شد.")

    async def _draw_debug_cross(self, page: Page, x: float, y: float, name: str):
        """رسم ضربدر قرمز و ذخیره اسکرین‌شات"""
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
                cross.innerHTML = `
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <line x1="2" y1="2" x2="22" y2="22" stroke="red" stroke-width="3"/>
                        <line x1="22" y1="2" x2="2" y2="22" stroke="red" stroke-width="3"/>
                    </svg>`;
                container.appendChild(cross);
            }}
        """)
        path = self.debug_dir / f"debug_click_{name}.png"
        await page.screenshot(path=path)
        logger.info(f"   📸 اسکرین‌شات با ضربدر ذخیره شد: {path.name}")
        await page.evaluate("""
            () => {
                const container = document.getElementById('debug-cross-container');
                if (container) container.remove();
            }
        """)
