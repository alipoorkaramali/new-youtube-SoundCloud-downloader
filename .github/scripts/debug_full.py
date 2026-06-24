#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت عیب‌یابی کامل برای Telegram Channel Scraper.
نسخهٔ اصلاح‌شده: جستجوی ساده + کلیک با سلکتورهای جدید.
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

        # ════════════ ۳. جستجوی کانال ════════════
        print(f"🔎 جستجوی @{CHANNEL} ...")
        await search_input.fill(CHANNEL)
        await asyncio.sleep(0.5)
        await search_input.press("Enter")
        await asyncio.sleep(2)
        await screenshot(page, "03_after_search")

        # ════════════ ۴. انتظار برای نتایج ════════════
        print("📋 منتظر نتایج جستجو...")
        try:
            await page.wait_for_selector('div.search-results, a[data-peer-id], div.search-result', timeout=12000)
            print("   ✅ نتایج جستجو ظاهر شدند.")
            await screenshot(page, "04_search_results")
        except Exception:
            print("❌ نتایج جستجو ظاهر نشد.")
            await screenshot(page, "04_no_search_results")
            await context.close()
            return

        # ════════════ ۵. کلیک روی اولین نتیجه (سلکتورهای بهبودیافته) ════════════
        print("🖱️ کلیک روی اولین نتیجه...")
        clicked = False
        for sel in [
            'div.search-result a', 'a[data-peer-id]', 'div.chatlist-item a',
            'div.search-result:first-child', 'div[data-peer-id]', '.search-results a'
        ]:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                print(f"   🖱️ تلاش برای کلیک با سلکتور: {sel}")
                await loc.click(timeout=5000)
                await asyncio.sleep(2)
                try:
                    await page.wait_for_selector('div.message, div[class*="Message"], div[data-message-id]', timeout=10000)
                    print("   ✅ محتوای کانال بارگذاری شد.")
                except Exception:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    print("   ✅ صفحه کانال باز شد (بدون پیام قابل تشخیص).")
                clicked = True
                break
            except Exception as e:
                print(f"   ⚠️ سلکتور {sel} ناموفق: {e}")
                continue

        if not clicked:
            print("❌ کلیک روی هیچ نتیجه‌ای موفق نبود.")
            await screenshot(page, "05_click_failed")
            await context.close()
            return
        await screenshot(page, "05_entered_channel")

        # ════════════ ۶. اسکرول و استخراج پست‌ها ════════════
        print("📜 شروع اسکرول برای جمع‌آوری پست‌ها...")
        seen_ids = set()
        items = []
        scroll_attempts = 0
        while len(items) < LIMIT and scroll_attempts < 10:
            try:
                new_posts = await page.evaluate(f"""(channel) => {{
                    const posts = [];
                    const messageSelectors = [
                        'div.message', 'div.bubbles-group > div', 'div[data-message-id]',
                        '[data-peer-id] div.message', 'div.chatlist-message', 'div[class*="Message"]'
                    ];
                    const allMessages = new Set();
                    messageSelectors.forEach(sel => {{
                        document.querySelectorAll(sel).forEach(el => allMessages.add(el));
                    }});
                    for (const el of allMessages) {{
                        let id = el.getAttribute('data-message-id') ||
                                 el.closest('[data-message-id]')?.getAttribute('data-message-id') ||
                                 el.querySelector('[data-message-id]')?.getAttribute('data-message-id');
                        if (!id || posts.some(p => p.id === id)) continue;
                        const textEl = el.querySelector('.text-content, .message-text, .bubble-content, div[class*="text"]');
                        const text = textEl ? textEl.innerText.trim() : '';
                        const dateEl = el.querySelector('time, .message-date, span[class*="date"]');
                        const date = dateEl ? (dateEl.getAttribute('datetime') || dateEl.innerText) : '';
                        const linkEl = el.querySelector(`a[href*="/${{channel}}/"]`);
                        const url = linkEl ? linkEl.href : '';
                        posts.push({{ id, text, date, url }});
                    }}
                    return posts;
                }}""", CHANNEL)
                for p in new_posts:
                    if p['id'] and p['id'] not in seen_ids:
                        seen_ids.add(p['id'])
                        items.append(p)
                print(f"   📊 {len(items)} پست تا الان جمع‌آوری شده.")
            except Exception as e:
                print(f"❌ خطا: {e}")

            if len(items) >= LIMIT:
                break

            old_height = await page.evaluate("document.documentElement.scrollHeight")
            await page.evaluate("window.scrollBy(0, 1800)")
            await asyncio.sleep(1.5)
            new_height = await page.evaluate("document.documentElement.scrollHeight")
            if new_height == old_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0

            if scroll_attempts == 1:
                await screenshot(page, f"06_scroll_{len(items)}")

        await screenshot(page, "07_final_state")
        print(f"✅ دیباگ تمام شد. {len(items)} پست استخراج شدند.")
        print(f"اسکرین‌شات‌ها در پوشه {OUTPUT_DIR} قرار دارند.")
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
