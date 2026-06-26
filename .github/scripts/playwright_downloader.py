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
    برای پست‌های صوتی/ویس، هدف راست‌کلیک را دقیق‌تر روی المان صوتی تنظیم می‌کند.
    در صورت شکست اولیه، صفحه را کمی به بالا اسکرول می‌کند (برای خارج شدن از زیر
    پست‌های پین‌شده) و دوباره تلاش می‌کند.
    اگر همچنان ناموفق بود، لینک مستقیم را از DOM استخراج و دانلود می‌کند.
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
                await message_locator.scroll_into_view_if_needed(timeout=20000)
                if attempt == 0:
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
                    path = self.debug_dir / f"post_not_found_{post_id}.png"
                    await page.screenshot(path=path)
                    logger.warning(f"⚠️ پست {post_id} بعد از ۵ تلاش پیدا نشد. اسکرین‌شات: {path.name}")
                    return

        if not success:
            return

        logger.info(f"   📍 پست {post_id} آماده شد.")
        await human_sleep(1.5, 0.4)

        # ──────────────── هدف دقیق برای راست‌کلیک ────────────────
        audio_locator = message_locator.locator(
            'div.audio-message, div[class*="Voice"], audio, '
            'div[class*="voice"], div[class*="player"]'
        ).first
        if await audio_locator.count() > 0 and await audio_locator.is_visible():
            click_target = audio_locator
            logger.info("   🎯 هدف دقیق: المان صوتی")
        else:
            click_target = message_locator
            logger.info("   🎯 هدف: کل حباب پیام")

        # شمارش مدیای visible (فقط برای اطلاع)
        media_elements = message_locator.locator(
            'div.media-photo, div.media-video, div.document, a.media-photo, '
            'video, img[src], div[class*="media"], audio'
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

        menu_success = False

        # ──────────────── تلاش برای راست‌کلیک و منوی context (با اسکرول کمکی در صورت شکست) ────────────────
        # حداکثر ۳ بار کل پروسه (هر بار ۲ تلاش راست‌کلیک) انجام می‌شود
        # اگر منو ظاهر نشد، قبل از تلاش بعدی ۳۰۰px به بالا اسکرول می‌کنیم
        for scroll_attempt in range(3):
            if menu_success:
                break
            if scroll_attempt > 0:
                logger.info(f"   📜 اسکرول کمکی ۳۰۰px به بالا (تلاش کلی {scroll_attempt+1})")
                await page.evaluate("window.scrollBy(0, -300)")
                await human_sleep(1.5, 0.3)

            try:
                menu_appeared = False
                for right_attempt in range(2):
                    # رسم ضربدر روی هدف و ذخیره اسکرین‌شات
                    box = await click_target.bounding_box()
                    if box:
                        x = box['x'] + box['width'] / 2
                        y = box['y'] + box['height'] / 2
                        await self._draw_debug_cross(page, x, y, f"target_{post_id}_{scroll_attempt}_{right_attempt}")
                        logger.info(f"   📸 ضربدر روی هدف کلیک (تلاش {scroll_attempt+1}-{right_attempt+1})")
                        await page.mouse.click(x, y, button='right')
                        logger.info(f"   🖱️ راست‌کلیک روی هدف در ({x:.0f}, {y:.0f})")
                    else:
                        await click_target.click(button='right', force=True)
                        logger.info(f"   🖱️ راست‌کلیک با force (تلاش {scroll_attempt+1}-{right_attempt+1})")

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
                            path = self.debug_dir / f"menu_failed_{post_id}_{scroll_attempt}.png"
                            await page.screenshot(path=path)
                            logger.warning(f"   ⚠️ منوی context در تلاش {scroll_attempt+1} ظاهر نشد. اسکرین‌شات: {path.name}")

                if not menu_appeared:
                    continue  # برو به اسکرول بعدی

                # ۲. یافتن گزینهٔ "Download"
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
                    await self._draw_debug_cross(page, download_coords['x'], download_coords['y'], f"download_option_{post_id}_{scroll_attempt}")
                    logger.info(f"   📸 اسکرین‌شات با ضربدر ذخیره شد")
                    await page.mouse.click(download_coords['x'], download_coords['y'])
                    logger.info(f"   ✅ کلیک روی گزینهٔ دانلود انجام شد (مختصات)")
                    menu_success = True
                else:
                    download_option = page.get_by_text("Download", exact=False).first
                    if await download_option.count() > 0:
                        await download_option.click()
                        logger.info(f"   ✅ کلیک روی گزینهٔ دانلود (fallback)")
                        menu_success = True
                    else:
                        logger.warning("   ⚠️ گزینهٔ دانلود در منوی راست‌کلیک پیدا نشد!")

                if menu_success:
                    # انتظار تطبیقی
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
                logger.warning(f"   ❌ خطا در فرایند راست‌کلیک/دانلود (تلاش {scroll_attempt+1}): {e}")
                try:
                    path = self.debug_dir / f"error_{post_id}_{scroll_attempt}.png"
                    await page.screenshot(path=path)
                    logger.info(f"   📸 اسکرین‌شات خطا: {path.name}")
                except:
                    pass

        # بستن منو و حذف listener (اگر هنوز باز باشد)
        try:
            await page.mouse.click(10, 10)
            await human_sleep(0.3, 0.2)
        except:
            pass
        page.remove_listener("download", on_download)

        # Fallback مستقیم + پشتیبانی از <audio src="...">
        if not menu_success and not downloaded_files:
            logger.info(f"   🔄 منوی context ناموفق – استفاده از دانلود مستقیم...")
            links = await message_locator.evaluate('''(el) => {
                const links = new Set();
                const add = (url) => { if (url && url.startsWith('http')) links.add(url); };
                el.querySelectorAll('img[src]').forEach(i => add(i.src));
                el.querySelectorAll('video source[src]').forEach(s => add(s.src));
                el.querySelectorAll('audio[src]').forEach(a => add(a.src));
                el.querySelectorAll('audio source[src]').forEach(s => add(s.src));
                el.querySelectorAll('a[href*="/file/"]').forEach(a => add(a.href));
                return Array.from(links);
            }''')
            logger.info(f"   🔗 {len(links)} لینک در کل پیام پیدا شد")
            if links:
                for idx, link in enumerate(links):
                    await self._download_link(page, link, post_id, idx, media_map)
            else:
                logger.warning(f"   ⚠️ هیچ لینکی برای دانلود مستقیم یافت نشد.")

        if downloaded_files:
            media_map[post_id] = downloaded_files
            logger.info(f"📦 پست {post_id}: {len(downloaded_files)} رسانه دانلود شد.")

    async def _download_link(self, page: Page, link: str, post_id: str, idx: int,
                             media_map: Dict[str, List[str]]):
        """کمکی برای دانلود یک لینک مستقیم و اضافه کردن به media_map"""
        for attempt in range(self.max_retries + 1):
            try:
                resp = await page.request.get(link, headers={"Referer": "https://web.telegram.org/"})
                if resp.ok:
                    body = await resp.body()
                    if len(body) > self.max_bytes:
                        logger.info(f"⏩ رد شد (حجم {len(body)/1024/1024:.1f}MB)")
                        return
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
                    return
                else:
                    logger.warning(f"⚠️ HTTP {resp.status} برای {link}")
            except Exception as e:
                logger.error(f"❌ خطای دانلود {link}: {e}")
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
