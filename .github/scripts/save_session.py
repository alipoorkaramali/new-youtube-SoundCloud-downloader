#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ساخت پروفایل دائمی تلگرام وب (نسخه A) برای استفاده در Playwright.
فقط یک بار اجرا شود. پس از لاگین موفق، پروفایل در config/browser_profile ذخیره می‌شود.
می‌توانید بعداً با tar -czf config/browser_profile.tar.gz -C config browser_profile آن را فشرده کنید.
"""

import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

PROFILE_DIR = Path("config/browser_profile")
TARGET_URL = "https://web.telegram.org/a/"

def main():
    # اگر پروفایل از قبل وجود دارد، هشدار بده
    if PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir()):
        print("⚠️ پوشه browser_profile از قبل وجود دارد و خالی نیست.")
        ans = input("آیا می‌خواهید با همان پروفایل ادامه دهید؟ (y/n) ").strip().lower()
        if ans != 'y':
            print("لطفاً پوشه را حذف یا rename کنید و دوباره اجرا نمایید.")
            sys.exit(0)

    with sync_playwright() as p:
        # باز کردن Chrome با پروفایل دائمی (اگر وجود نداشته باشد ساخته می‌شود)
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,                     # باید مرورگر را ببینید
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            # اگر نیاز به پروکسی دارید، می‌توانید proxy={"server": "http://127.0.0.1:10809"} را اضافه کنید.
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        except PlaywrightTimeout:
            print("❌ صفحه باز نشد. لطفاً VPN/فیلترشکن خود را بررسی کنید.")
            context.close()
            sys.exit(1)

        print("📱 لطفاً در مرورگر باز شده وارد تلگرام شوید (شماره، کد تأیید، رمز دو مرحله‌ای)")
        print("⏳ منتظر ورود کامل شما هستم...")

        # صبر می‌کنیم تا صفحهٔ چت‌ها ظاهر شود
        try:
            # چند selector مختلف برای نسخه A
            page.wait_for_selector("div.chat-list, input[type='search']", timeout=300_000)  # ۵ دقیقه
        except PlaywrightTimeout:
            print("❌ ورود در زمان مقرر کامل نشد. لطفاً دوباره تلاش کنید.")
            context.close()
            sys.exit(1)

        print("✅ ورود موفق! پروفایل در config/browser_profile ذخیره شد.")
        print("می‌توانید مرورگر را ببندید یا همین‌جا بمانید.")
        print("برای استفاده در گیت‌هاب، پوشه را فشرده کنید:")
        print("  tar -czf config/browser_profile.tar.gz -C config browser_profile")
        context.close()

if __name__ == "__main__":
    main()
