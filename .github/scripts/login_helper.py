#!/usr/bin/env python3
import json, sys
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SESSION_FILE = Path("config/session.json")
TARGET_URL = "https://web.telegram.org/a/"

def main():
    with sync_playwright() as p:
        # باز کردن Chrome (بدون پروکسی، VPN سیستمی کافیست)
        browser = p.chromium.launch(channel="chrome", headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.set_default_navigation_timeout(60000)

        # باز کردن تلگرام وب
        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded")
        except PlaywrightTimeout:
            print("❌ نتواستیم به تلگرام وب وصل شویم. VPN را بررسی کنید.")
            browser.close()
            sys.exit(1)

        print("📱 در پنجره مرورگر وارد تلگرام شوید (شماره، کد تأیید، رمز دو مرحله‌ای)")
        print("⏳ صبر می‌کنم تا لیست چت‌ها ظاهر شود...")

        # ---------- مهم‌ترین تغییر: استفاده از selectorهای واقعی ----------
        login_success = False
        # چند انتخابگر ممکن برای تشخیص ورود موفق (نسخه A)
        selectors = [
            "input[type='search']",                # نوار جستجو
            "div.search-input",                    # حالت دیگر
            "div.chatlist",                        # لیست چت‌ها
            "div.bubbles",                         # ممکن است
        ]
        for selector in selectors:
            try:
                page.wait_for_selector(selector, timeout=180_000)  # ۳ دقیقه
                login_success = True
                break
            except PlaywrightTimeout:
                continue

        if not login_success:
            print("❌ پس از ۳ دقیقه هنوز وارد چت‌ها نشده‌اید. لطفاً دوباره تلاش کنید.")
            browser.close()
            sys.exit(1)
        # -----------------------------------------------------------

        print("✅ ورود موفق! در حال ذخیره‌سازی سشن...")
        cookies = context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        cookie_dict["updated_at"] = datetime.now().isoformat()

        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(cookie_dict, f, indent=2, ensure_ascii=False)

        print(f"🎉 سشن در {SESSION_FILE} ذخیره شد. می‌توانید مرورگر را ببندید.")
        browser.close()

if __name__ == "__main__":
    main()