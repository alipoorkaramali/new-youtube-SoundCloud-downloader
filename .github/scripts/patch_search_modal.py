#!/usr/bin/env python3
"""Runtime patch: error screenshot + Escape retry when search click is blocked."""
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/scripts/scraper.py")
src = path.read_text(encoding="utf-8")

if "_force_error_screenshot" in src:
    print("already patched")
    sys.exit(0)

old = """        if not search_input:
            self.logger.error(\"❌ نوار جستجو پیدا نشد.\")
            return False

        await search_input.click()
        await human_sleep(0.3, 0.2)
        await search_input.fill('')
        await human_sleep(0.2, 0.1)
        await search_input.type(self.channel, delay=random.randint(80, 150))
        self.logger.info(f\"🔍 در حال جستجوی: @{self.channel}\")
        if self.save_screenshots:
            await self._take_screenshot(page, \"search_input_filled\")"""

new = """        if not search_input:
            self.logger.error(\"❌ نوار جستجو پیدا نشد.\")
            await self._force_error_screenshot(page, \"search_input_not_found\")
            return False

        try:
            await search_input.click(timeout=15000)
        except Exception as e:
            self.logger.error(f\"❌ کلیک روی نوار جستجو شکست: {e}\")
            await self._force_error_screenshot(page, \"search_click_blocked\")
            try:
                await page.keyboard.press(\"Escape\")
                await human_sleep(0.8, 0.2)
                await page.keyboard.press(\"Escape\")
                await human_sleep(0.5, 0.1)
                await self._force_error_screenshot(page, \"search_click_after_escape\")
                await search_input.click(timeout=10000, force=True)
                self.logger.info(\"✅ کلیک اجباری روی سرچ بعد از Escape موفق شد\")
            except Exception as e2:
                self.logger.error(f\"❌ کلیک اجباری هم شکست: {e2}\")
                await self._force_error_screenshot(page, \"search_click_force_failed\")
                return False

        await human_sleep(0.3, 0.2)
        await search_input.fill('')
        await human_sleep(0.2, 0.1)
        await search_input.type(self.channel, delay=random.randint(80, 150))
        self.logger.info(f\"🔍 در حال جستجوی: @{self.channel}\")
        if self.save_screenshots:
            await self._take_screenshot(page, \"search_input_filled\")"""

old2 = """    async def _take_screenshot(self, page, name: str):
        \"\"\"ذخیره اسکرین‌شات دیباگ کامل صفحه (فقط در صورت فعال بودن).\"\"\"
        if not self.save_screenshots:
            return
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
        await self._screenshot(page, name, full_page=True)"""

new2 = """    async def _force_error_screenshot(self, page, name: str):
        \"\"\"همیشه اسکرین‌شات خطای UI می‌گیرد (حتی اگر save_screenshots=false).\"\"\"
        try:
            self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
            safe = self._sanitize_filename(name)
            path = self.debug_screenshots_dir / f\"error_{self.channel}_{safe}.png\"
            await page.screenshot(path=str(path), full_page=True)
            self.logger.error(f\"📸 اسکرین‌شات خطا ذخیره شد: {path}\")
            try:
                info = await page.evaluate(\"\"\"() => {
                    const backdrops = document.querySelectorAll('.modal-backdrop, [class*=\"backdrop\"], #portals .opacity-transition');
                    const portals = document.getElementById('portals');
                    const texts = [];
                    document.querySelectorAll('.modal, [class*=\"modal\"], [role=\"dialog\"], #portals *').forEach(el => {
                        const t = (el.innerText || '').trim().slice(0, 120);
                        if (t && t.length > 8) texts.push(t);
                    });
                    return {
                        backdrop_count: backdrops.length,
                        portal_html_len: portals ? portals.innerHTML.length : 0,
                        sample_texts: [...new Set(texts)].slice(0, 8)
                    };
                }\"\"\")
                self.logger.error(f\"🧾 UI overlay info: {info}\")
            except Exception as ie:
                self.logger.debug(f\"overlay probe failed: {ie}\")
        except Exception as se:
            self.logger.warning(f\"⚠️ نتوانست اسکرین‌شات خطا بگیرد: {se}\")

    async def _take_screenshot(self, page, name: str):
        \"\"\"ذخیره اسکرین‌شات دیباگ کامل صفحه (فقط در صورت فعال بودن).\"\"\"
        if not self.save_screenshots:
            return
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
        await self._screenshot(page, name, full_page=True)"""

ok = True
if old not in src:
    print("WARN: click block not found")
    ok = False
else:
    src = src.replace(old, new, 1)
    print("OK: click block")
if old2 not in src:
    print("WARN: _take_screenshot not found")
    ok = False
else:
    src = src.replace(old2, new2, 1)
    print("OK: force screenshot method")
path.write_text(src, encoding="utf-8")
print("written", path, "ok=", ok)
