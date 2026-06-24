#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت عیب‌یابی کامل برای Telegram Channel Scraper.
نسخهٔ نهایی: جستجوی مقاوم، انتخاب تب Channels، force click، fallback بهبودیافته.
"""

import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

CHANNEL = os.getenv("CHANNEL", "bbcpersian").lstrip("@")
LIMIT = int(os.getenv("LIMIT", "10"))
PROFILE_DIR = Path("config/browser_profile")
OUTPUT_DIR = Path("debug_output")
OUTPUT_DIR.mkdir(exist_ok=True)
HOME_URL = "https://web.telegram.org/a/"

def is_github_actions() -> bool:
    return os.getenv("GITHUB_ACTIONS", "").lower() == "true"

async def screenshot(page, name: str):
    path = OUTPUT_DIR / f"{name}.png"
    await page.screenshot(path=path, full_page=True)
    print(f"📸 {name} ذخیره شد: {path}")

async def main():
    async with async_playwright() as p:
        if is_github_actions():
            print("☁️ محیط: گیت‌هاب (headless + کرومیوم)")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                viewport={"width": 1366, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
            )
        else:
            print("💻 محیط: لوکال (Chrome + نمایشگر)")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=False,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                viewport={"width": 1366, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
            )

        page = await context.new_page()

        # ════════════ ۱. صفحه اصلی ════════════
        print("🌐 باز کردن صفحه اصلی تلگرام...")
        try:
            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            await screenshot(page, "01_homepage")
        except Exception as e:
            print(f"❌ خطا: {e}")
            await context.close()
            return

        # ════════════ ۲. پیدا کردن نوار جستجو ════════════
        print("🔍 جستجوی نوار جستجو...")
        search_input = None
        for sel in [
            'input[placeholder*="Search"], input[placeholder*="جستجو"]',
            'div.input-search input',
            '[data-testid="search-input"]',
            'input[role="textbox"]'
        ]:
            try:
                search_input = await page.wait_for_selector(sel, timeout=8000)
                if search_input:
                    print(f"   ✅ نوار جستجو پیدا شد: {sel[:50]}")
                    break
            except Exception:
                continue
        if not search_input:
            print("❌ نوار جستجو پیدا نشد.")
            await screenshot(page, "02_searchbar_missing")
            await context.close()
            return
        await screenshot(page, "02_searchbar_found")

        # ════════════ ۳. جستجوی کانال (مقاوم‌سازی شده) ════════════
        print(f"🔎 جستجوی @{CHANNEL} ...")
        await search_input.fill(CHANNEL)
        await asyncio.sleep(1)
        await search_input.press("Enter")

        print("⏳ منتظر بارگذاری نتایج جستجو (تا ۲۵ ثانیه)...")
        await asyncio.sleep(5)

        # کلیک روی تب Channels (اگر وجود داشته باشد)
        try:
            channels_tab = page.get_by_role("tab", name="Channels").first
            if await channels_tab.count() > 0:
                await channels_tab.click()
                await asyncio.sleep(3)
                print("📑 تب Channels انتخاب شد.")
                await screenshot(page, "03_after_channels_tab")   # <-- اسکرین‌شات جدید
        except Exception:
            pass

        # انتظار هوشمند برای نتایج
        found = False
        search_result_selectors = [
            'div.search-result', 'div.chatlist-item', 'a[data-peer-id]',
            'div.search-results', '[role="listitem"]', 'div[role="button"]'
        ]

        for wait_time in [8, 10, 12]:
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(wait_time)

            for sel in search_result_selectors:
                try:
                    count = await page.locator(sel).count()
                    if count > 0:
                        print(f"   ✅ {count} نتیجه با سلکتور '{sel}' پیدا شد.")
                        found = True
                        break
                except Exception:
                    continue
            if found:
                break

        if not found:
            has_results = await page.evaluate(
                """() => document.querySelectorAll('div.search-result, div.chatlist-item, a[data-peer-id]').length > 0"""
            )
            if has_results:
                found = True

        if not found:
            print("❌ نتایج جستجو پیدا نشدند.")
            await screenshot(page, "04_no_search_results")
            await context.close()
            return

        print("   ✅ نتایج جستجو ظاهر شدند.")
        await screenshot(page, "04_search_results")

        # ════════════ ۴. کلیک روی اولین نتیجه (force click) ════════════
        print("🖱️ کلیک روی اولین نتیجه...")
        clicked = False

        click_selectors = [
            'div.search-result [role="button"]',
            'div.search-result [role="link"]',
            'div.chatlist-item',
            'a[href*="/c/"]',
            'div.search-results div[role="button"]',
            'div[role="button"]',
            'div.search-result',
        ]

        for attempt in range(3):
            for sel in click_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() == 0:
                        continue
                    await loc.wait_for(state="visible", timeout=5000)
                    print(f"   🖱️ تلاش کلیک با سلکتور: {sel} (attempt {attempt+1})")
                    await loc.click(timeout=8000, force=True)
                    await asyncio.sleep(3)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                        await asyncio.sleep(2)
                        await page.wait_for_selector(
                            'div.message, div[data-message-id], article[role="article"]',
                            timeout=10000
                        )
                        print("   ✅ کانال با موفقیت باز شد.")
                        clicked = True
                        break
                    except Exception:
                        print("   ⚠️ کانال باز شد اما پیام‌ها کامل لود نشدند. ادامه...")
                        clicked = True
                        break
                except Exception:
                    continue
            if clicked:
                break

        if not clicked:
            # fallback با get_by_text (با نام اصلی و حروف بزرگ)
            print("   🔄 تلاش fallback با get_by_text...")
            fallback_names = {CHANNEL, CHANNEL.upper()}  # نام اصلی و حروف بزرگ
            for name in fallback_names:
                try:
                    result_item = page.get_by_text(name, exact=False).first
                    if await result_item.count() > 0:
                        await result_item.click(timeout=8000, force=True)
                        await asyncio.sleep(3)
                        await page.wait_for_load_state("networkidle", timeout=15000)
                        await asyncio.sleep(2)
                        await page.wait_for_selector(
                            'div.message, div[data-message-id]', timeout=10000
                        )
                        print(f"   ✅ با fallback get_by_text('{name}') وارد کانال شدیم.")
                        clicked = True
                        break
                except Exception as e:
                    continue

        if not clicked:
            print("❌ کلیک روی هیچ نتیجه‌ای موفق نبود.")
            await screenshot(page, "05_click_failed")
            await context.close()
            return
        await screenshot(page, "05_entered_channel")

        # ════════════ ۵. اسکرول و استخراج پست‌ها (فقط پیام‌های جدید) ════════════
        print("📜 شروع اسکرول و استخراج پست‌ها...")
        seen_ids = set()
        items = []
        scroll_attempts = 0
        last_count = 0

        while len(items) < LIMIT and scroll_attempts < 12:
            try:
                messages = page.locator(
                    'div.message, div[data-message-id], article[role="article"], div.bubbles-group > div'
                )
                count = await messages.count()
                print(f"   🔍 {count} المان پیام پیدا شد (قبلاً {last_count} تا).")

                for i in range(last_count, count):
                    try:
                        msg = messages.nth(i)
                        msg_id = await msg.get_attribute('data-message-id')
                        if not msg_id:
                            inner = msg.locator('[data-message-id]').first
                            if await inner.count() > 0:
                                msg_id = await inner.get_attribute('data-message-id')
                        if not msg_id or msg_id in seen_ids:
                            continue

                        text = (await msg.inner_text()).strip()[:600]
                        date_el = msg.locator('time, .message-date, .date, span[class*="date"]').first
                        date = ""
                        if await date_el.count() > 0:
                            date = await date_el.inner_text() or await date_el.get_attribute('datetime') or ""

                        items.append({
                            'id': msg_id,
                            'text': text,
                            'date': date,
                            'url': f"https://t.me/{CHANNEL}/{msg_id}"
                        })
                        seen_ids.add(msg_id)
                    except Exception:
                        continue

                last_count = count
                print(f"   📊 {len(items)} پست یکتا جمع‌آوری شد.")
            except Exception as e:
                print(f"   ❌ خطا: {e}")

            if len(items) >= LIMIT:
                break

            old_height = await page.evaluate("document.documentElement.scrollHeight")
            await page.evaluate("window.scrollBy(0, 2000)")
            await asyncio.sleep(2)
            new_height = await page.evaluate("document.documentElement.scrollHeight")

            if new_height == old_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0

            if scroll_attempts == 1 or len(items) % 8 == 0:
                await screenshot(page, f"06_scroll_{len(items)}")

        await screenshot(page, "07_final_state")
        print(f"✅ دیباگ تمام شد. {len(items)} پست استخراج شدند.")
        print(f"اسکرین‌شات‌ها در پوشه {OUTPUT_DIR} قرار دارند.")
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
