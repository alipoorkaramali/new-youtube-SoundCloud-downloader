#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت عیب‌یابی کامل برای Telegram Channel Scraper.
نسخهٔ نهایی: جستجوی مقاوم + کلیک ترکیبی + پرش به آخرین پست + استخراج پایدار.
"""

import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

CHANNEL = os.getenv("CHANNEL", "bbcpersian").lstrip("@")
LIMIT = int(os.getenv("LIMIT", "10"))
PROFILE_DIR = Path("config/browser_profile")
OUTPUT_DIR = Path("debug_output")
OUTPUT_DIR.mkdir(exist_ok=True)
HOME_URL = "https://web.telegram.org/a/"

def is_github_actions() -> bool:
    return os.getenv("GITHUB_ACTIONS", "").lower() == "true"

async def screenshot(page, name: str):
    try:
        path = OUTPUT_DIR / f"{name}.png"
        await page.screenshot(path=path, full_page=True)
        print(f"📸 {name} ذخیره شد: {path}")
    except Exception as e:
        print(f"⚠️ خطای اسکرین‌شات: {e}")

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
            'input[placeholder*="Search"]',
            'input[role="textbox"]',
            '[data-testid="search-input"]'
        ]:
            try:
                search_input = await page.wait_for_selector(sel, timeout=10000)
                if search_input:
                    print(f"   ✅ نوار جستجو پیدا شد.")
                    break
            except Exception:
                continue
        if not search_input:
            print("❌ نوار جستجو پیدا نشد.")
            await screenshot(page, "02_searchbar_missing")
            await context.close()
            return
        await screenshot(page, "02_searchbar_found")

        # ════════════ ۳. جستجوی کانال (مقاوم) ════════════
        print(f"🔎 جستجوی @{CHANNEL} ...")
        await search_input.fill(CHANNEL)
        await asyncio.sleep(1)
        await search_input.press("Enter")
        print("⏳ منتظر نتایج...")
        await asyncio.sleep(5)

        # تب Channels (اگر وجود دارد)
        try:
            channels_tab = page.get_by_role("tab", name="Channels").first
            if await channels_tab.count() > 0:
                await channels_tab.click()
                await asyncio.sleep(3)
                print("📑 تب Channels انتخاب شد.")
                await screenshot(page, "03_after_channels_tab")
        except Exception:
            pass

        # بررسی نتایج با چندین تلاش
        found = False
        for wait_time in [6, 10, 14]:
            await asyncio.sleep(wait_time)
            for sel in ['div[role="button"]', 'div.search-result', 'div.chatlist-item', 'a[data-peer-id]']:
                try:
                    if await page.locator(sel).count() > 0:
                        print(f"   ✅ نتیجه پیدا شد با سلکتور '{sel}'")
                        found = True
                        break
                except Exception:
                    continue
            if found:
                break

        if not found:
            print("❌ نتایج پیدا نشد.")
            await screenshot(page, "04_no_search_results")
            await context.close()
            return

        await screenshot(page, "04_search_results")

        # ════════════ ۴. کلیک (ترکیبی ساده + force) ════════════
        print("🖱️ تلاش برای ورود به کانال...")
        clicked = False

        # روش 1: سلکتورهای ساده + force click
        for sel in ['div.chatlist-item', 'div[role="button"]', 'div.search-result', 'a[data-peer-id]']:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                await loc.wait_for(state="visible", timeout=5000)
                print(f"   → کلیک با {sel}")
                await loc.click(timeout=8000, force=True)
                await asyncio.sleep(4)
                clicked = True
                break
            except Exception:
                continue

        # روش 2: fallback با get_by_text
        if not clicked:
            print("   🔄 fallback get_by_text...")
            for name in [CHANNEL, CHANNEL.upper(), "BBCPersian"]:
                try:
                    item = page.get_by_text(name, exact=False).first
                    if await item.count() > 0:
                        await item.click(timeout=8000, force=True)
                        await asyncio.sleep(4)
                        clicked = True
                        print(f"   ✅ با fallback '{name}' کلیک شد.")
                        break
                except Exception:
                    continue

        if not clicked:
            print("❌ کلیک ناموفق.")
            await screenshot(page, "05_click_failed")
            await context.close()
            return

        # منتظر بارگذاری کانال (با پیام‌ها)
        try:
            await page.wait_for_selector('div.message, div[data-message-id], article[role="article"]', timeout=15000)
            print("✅ کانال با موفقیت باز شد.")
        except Exception:
            print("⚠️ کانال باز شد ولی پیام‌ها کامل لود نشدند. ادامه می‌دهیم...")
        await screenshot(page, "05_entered_channel")

        # ════════════ ۴.۵ **پرش به آخرین پست** (جدید) ════════════
        print("⬇️ تلاش برای پرش به آخرین پست‌ها...")
        try:
            # سلکتورهای رایج برای دکمهٔ «برو به پایین» یا «آخرین پیام‌ها»
            scroll_button_selectors = [
                'button[title="Go to bottom"]',
                'div[class*="scroll-to-bottom"]',
                'div[class*="ScrollButton"]',
                '[aria-label="Scroll to bottom"]',
                'button:has(svg[class*="arrow-down"])',   # آیکن فلش پایین
            ]
            for sel in scroll_button_selectors:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    await btn.click(timeout=3000)
                    print("   ✅ روی دکمهٔ فلش کلیک شد. منتظر بارگذاری آخرین پست‌ها...")
                    await asyncio.sleep(3)
                    await screenshot(page, "05b_jumped_to_latest")
                    break
            else:
                print("   ℹ️ دکمهٔ پرش به پایین پیدا نشد (شاید از قبل در آخرین پست‌ها هستیم).")
        except Exception as e:
            print(f"   ⚠️ خطا در کلیک دکمه پرش: {e}")

        # ════════════ ۵. اسکرول و استخراج پست‌ها (روش اثبات‌شده قبلی) ════════════
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

                # فقط پیام‌های جدید از last_count به بعد
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

            # اسکرول هوشمند
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
