#!/usr/bin/env python3
"""Patch scraper: allow Service Workers, dismiss Telegram SW modal (OK), error screenshots."""
from pathlib import Path
import re
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/scripts/scraper.py")
src = path.read_text(encoding="utf-8")
changed = False

# ── 1) launch: service_workers=allow ──
old_launch = (
    '            context = await p.chromium.launch_persistent_context(\n'
    '                user_data_dir=str(self.profile_dir),\n'
    '                headless=False,\n'
    '                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],\n'
    '                viewport={"width": 1366, "height": 900},\n'
    '                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"\n'
    '            )'
)
new_launch = (
    '            context = await p.chromium.launch_persistent_context(\n'
    '                user_data_dir=str(self.profile_dir),\n'
    '                headless=False,\n'
    '                # Telegram Web needs Service Worker; block causes "Something went wrong" modal\n'
    '                service_workers="allow",\n'
    '                args=[\n'
    '                    "--no-sandbox",\n'
    '                    "--disable-blink-features=AutomationControlled",\n'
    '                ],\n'
    '                viewport={"width": 1366, "height": 900},\n'
    '                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",\n'
    '            )'
)
if "service_workers=" not in src:
    if old_launch in src:
        src = src.replace(old_launch, new_launch, 1)
        changed = True
        print("OK: service_workers=allow on launch")
    else:
        print("WARN: launch block not found")
else:
    print("skip: service_workers already set")

# ── 2) helpers ──
if "_dismiss_blocking_modals" not in src:
    insert_before = (
        '    async def _take_screenshot(self, page, name: str):\n'
        '        """ذخیره اسکرین‌شات دیباگ کامل صفحه (فقط در صورت فعال بودن)."""\n'
        '        if not self.save_screenshots:\n'
        '            return\n'
        '        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)\n'
        '        await self._screenshot(page, name, full_page=True)'
    )
    helper = r'''    async def _dismiss_blocking_modals(self, page, soft_reload: bool = True) -> bool:
        """
        بستن مودال‌های مسدودکننده تلگرام وب (مثل Service Worker disabled).
        اول OK، بعد Escape. در صورت نیاز یک reload معمولی (بدون Shift).
        """
        dismissed = False
        try:
            for label in ("OK", "Ok", "Close", "Dismiss", "Got it"):
                try:
                    btn = page.get_by_role("button", name=label)
                    if await btn.count() > 0:
                        await btn.first.click(timeout=3000)
                        dismissed = True
                        self.logger.info(f"✅ مودال با دکمه '{label}' بسته شد")
                        await human_sleep(0.5, 0.2)
                        break
                except Exception:
                    continue
            if not dismissed:
                for sel in (
                    'button:has-text("OK")',
                    '[role="dialog"] button',
                    '.modal-backdrop',
                    '#portals button',
                ):
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0 and await el.is_visible():
                            await el.click(timeout=2000, force=True)
                            dismissed = True
                            self.logger.info(f"✅ مودال با selector {sel} بسته شد")
                            await human_sleep(0.4, 0.1)
                            break
                    except Exception:
                        continue
            try:
                await page.keyboard.press("Escape")
                await human_sleep(0.3, 0.1)
                await page.keyboard.press("Escape")
            except Exception:
                pass
            if soft_reload:
                try:
                    body = (await page.inner_text("body"))[:2000]
                    if "Service Worker is disabled" in body or "Something went wrong" in body:
                        self.logger.warning("⚠️ مودال SW هنوز هست — reload معمولی (بدون Shift)")
                        await page.reload(wait_until="domcontentloaded", timeout=30000)
                        await human_sleep(2.0, 0.3)
                        try:
                            btn = page.get_by_role("button", name="OK")
                            if await btn.count() > 0:
                                await btn.first.click(timeout=3000)
                                dismissed = True
                                self.logger.info("✅ OK بعد از reload")
                        except Exception:
                            pass
                except Exception as re_err:
                    self.logger.debug(f"soft reload skip: {re_err}")
        except Exception as e:
            self.logger.debug(f"dismiss modals: {e}")
        return dismissed

    async def _force_error_screenshot(self, page, name: str):
        """همیشه اسکرین‌شات خطای UI (حتی اگر save_screenshots=false)."""
        try:
            self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
            safe = self._sanitize_filename(name)
            path = self.debug_screenshots_dir / f"error_{self.channel}_{safe}.png"
            await page.screenshot(path=str(path), full_page=True)
            self.logger.error(f"📸 اسکرین‌شات خطا ذخیره شد: {path}")
            try:
                info = await page.evaluate("""() => {
                    const backdrops = document.querySelectorAll('.modal-backdrop, [class*="backdrop"], #portals .opacity-transition');
                    const portals = document.getElementById('portals');
                    const texts = [];
                    document.querySelectorAll('.modal, [class*="modal"], [role="dialog"], #portals *').forEach(el => {
                        const t = (el.innerText || '').trim().slice(0, 120);
                        if (t && t.length > 8) texts.push(t);
                    });
                    return {
                        backdrop_count: backdrops.length,
                        portal_html_len: portals ? portals.innerHTML.length : 0,
                        sample_texts: [...new Set(texts)].slice(0, 8)
                    };
                }""")
                self.logger.error(f"🧾 UI overlay info: {info}")
            except Exception as ie:
                self.logger.debug(f"overlay probe failed: {ie}")
        except Exception as se:
            self.logger.warning(f"⚠️ نتوانست اسکرین‌شات خطا بگیرد: {se}")

    async def _take_screenshot(self, page, name: str):
        """ذخیره اسکرین‌شات دیباگ کامل صفحه (فقط در صورت فعال بودن)."""
        if not self.save_screenshots:
            return
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
        await self._screenshot(page, name, full_page=True)'''
    if insert_before in src:
        src = src.replace(insert_before, helper, 1)
        changed = True
        print("OK: dismiss + force screenshot helpers")
    else:
        print("WARN: _take_screenshot block not found")
else:
    print("skip: helpers already present")

# ── 3) after goto → dismiss ──
old_goto = (
    '        try:\n'
    '            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)\n'
    '        except Exception as e:\n'
    '            self.logger.error(f"❌ صفحه اصلی باز نشد: {e}")\n'
    '            if existing_context is None:\n'
    '                await context.close()\n'
    '            return [], None, None\n'
    '\n'
    '        # ─── ورود به کانال یا لینک ──────────────────────────────'
)
new_goto = (
    '        try:\n'
    '            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)\n'
    '            await human_sleep(1.5, 0.3)\n'
    '            # بستن مودال Service Worker / Something went wrong قبل از هر کلیک\n'
    '            await self._dismiss_blocking_modals(page, soft_reload=True)\n'
    '            await human_sleep(0.5, 0.2)\n'
    '        except Exception as e:\n'
    '            self.logger.error(f"❌ صفحه اصلی باز نشد: {e}")\n'
    '            if existing_context is None:\n'
    '                await context.close()\n'
    '            return [], None, None\n'
    '\n'
    '        # ─── ورود به کانال یا لینک ──────────────────────────────'
)
if old_goto in src:
    src = src.replace(old_goto, new_goto, 1)
    changed = True
    print("OK: dismiss after goto")
else:
    print("WARN: goto block not found (maybe already patched)")

# ── 4) search click ──
new_search = (
    '        if not search_input:\n'
    '            self.logger.error("❌ نوار جستجو پیدا نشد.")\n'
    '            await self._force_error_screenshot(page, "search_input_not_found")\n'
    '            return False\n'
    '\n'
    '        # اول مودال (مثل Service Worker) را با OK ببند، بعد کلیک\n'
    '        await self._dismiss_blocking_modals(page, soft_reload=False)\n'
    '        try:\n'
    '            await search_input.click(timeout=15000)\n'
    '        except Exception as e:\n'
    '            self.logger.error(f"❌ کلیک روی نوار جستجو شکست: {e}")\n'
    '            await self._force_error_screenshot(page, "search_click_blocked")\n'
    '            await self._dismiss_blocking_modals(page, soft_reload=True)\n'
    '            try:\n'
    '                await search_input.click(timeout=10000, force=True)\n'
    '                self.logger.info("✅ کلیک اجباری روی سرچ بعد از بستن مودال موفق شد")\n'
    '            except Exception as e2:\n'
    '                self.logger.error(f"❌ کلیک اجباری هم شکست: {e2}")\n'
    '                await self._force_error_screenshot(page, "search_click_force_failed")\n'
    '                return False\n'
    '\n'
    '        await human_sleep(0.3, 0.2)\n'
    '        await search_input.fill(\'\')\n'
    '        await human_sleep(0.2, 0.1)\n'
    '        await search_input.type(self.channel, delay=random.randint(80, 150))\n'
    '        self.logger.info(f"🔍 در حال جستجوی: @{self.channel}")\n'
    '        if self.save_screenshots:\n'
    '            await self._take_screenshot(page, "search_input_filled")'
)

old_search = (
    '        if not search_input:\n'
    '            self.logger.error("❌ نوار جستجو پیدا نشد.")\n'
    '            return False\n'
    '\n'
    '        await search_input.click()\n'
    '        await human_sleep(0.3, 0.2)\n'
    '        await search_input.fill(\'\')\n'
    '        await human_sleep(0.2, 0.1)\n'
    '        await search_input.type(self.channel, delay=random.randint(80, 150))\n'
    '        self.logger.info(f"🔍 در حال جستجوی: @{self.channel}")\n'
    '        if self.save_screenshots:\n'
    '            await self._take_screenshot(page, "search_input_filled")'
)

if old_search in src:
    src = src.replace(old_search, new_search, 1)
    changed = True
    print("OK: search click patched (original)")
elif "search_click_blocked" in src:
    m = re.search(
        r'        if not search_input:\n            self\.logger\.error\("❌ نوار جستجو پیدا نشد\."\).*?await self\._take_screenshot\(page, "search_input_filled"\)',
        src,
        re.S,
    )
    if m:
        src = src.replace(m.group(0), new_search, 1)
        changed = True
        print("OK: search click replaced (previous patch)")
    else:
        print("WARN: could not regex-replace previous search patch")
else:
    print("WARN: search click block not found")

path.write_text(src, encoding="utf-8")
print("written", path, "changed=", changed)
for s in ("service_workers", "_dismiss_blocking_modals", "Something went wrong", "search_click_blocked"):
    print(f"  has {s}: {s in path.read_text(encoding='utf-8')}")
