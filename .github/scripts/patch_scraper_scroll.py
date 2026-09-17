#!/usr/bin/env python3
"""Safe patch for scraper.py — direction-aware start_link + stronger jump-to-bottom."""
from pathlib import Path
import re
import sys
import py_compile


def patch(path: Path) -> None:
    sc = path.read_text(encoding="utf-8")
    orig = sc

    if "SCROLL_DOWN" not in sc:
        sc = sc.replace("SCROLL_UP = -1200", "SCROLL_UP = -1200\nSCROLL_DOWN = 1200")

    old_f = (
        "                        if self.start_link and int(msg_id) >= int(self.target_msg_id):\n"
        '                            self.logger.debug(f"⏭️ پست {msg_id} جدیدتر یا مساوی هدف است، رد می‌شود.")\n'
        "                            continue\n"
    )
    new_f = (
        "                        if self.start_link and self.target_msg_id:\n"
        "                            try:\n"
        "                                mid, tid = int(msg_id), int(self.target_msg_id)\n"
        "                            except (TypeError, ValueError):\n"
        "                                mid, tid = 0, 0\n"
        '                            if self.scroll_direction == "down":\n'
        "                                if mid <= tid:\n"
        "                                    continue\n"
        "                            else:\n"
        "                                if mid >= tid:\n"
        "                                    continue\n"
    )
    if old_f in sc:
        sc = sc.replace(old_f, new_f)
        print("filter: fixed")
    elif "mid <= tid" in sc:
        print("filter: already patched")
    else:
        print("filter: pattern not found")

    def repl_scroll(m):
        ind = m.group(1)
        return (
            f'{ind}if self.scroll_direction == "down":\n'
            f'{ind}    self.logger.info("⬇️ بارگذاری پست‌های جدیدتر با اسکرول به پایین...")\n'
            f"{ind}    _amt = 1200\n"
            f"{ind}else:\n"
            f'{ind}    self.logger.info("⬆️ بارگذاری پست‌های قدیمی‌تر با اسکرول به بالا...")\n'
            f"{ind}    _amt = SCROLL_UP\n"
            f"{ind}for scroll_step in range(3):\n"
            f'{ind}    await page.evaluate(f"window.scrollBy(0, {{_amt}})")\n'
        )

    sc2, n = re.subn(
        r'(\s*)self\.logger\.info\("⬆️ بارگذاری پست‌های قدیمی‌تر با اسکرول به بالا\.\.\."\)\s*\n'
        r"\s*for scroll_step in range\(3\):\s*\n"
        r'\s*await page\.evaluate\(f"window\.scrollBy\(0, \{SCROLL_UP\}\)"\)\s*\n',
        repl_scroll,
        sc,
    )
    if n:
        sc = sc2
        print(f"scroll init: fixed {n}")
    elif "بارگذاری پست‌های جدیدتر با اسکرول به پایین" in sc:
        print("scroll init: already patched")
    else:
        print("scroll init: pattern not found")

    old_sels = """            scroll_button_selectors = [
                'button[title="Go to bottom"]',
                'div[class*="scroll-to-bottom"]',
                'div[class*="ScrollButton"]',
                '[aria-label="Scroll to bottom"]',
                'button:has(svg[class*="arrow-down"])',
            ]"""
    new_sels = """            scroll_button_selectors = [
                'button[title="Go to bottom"]',
                'button[aria-label="Go to bottom"]',
                'button[aria-label="Scroll to bottom"]',
                '[aria-label="Go to bottom"]',
                '[aria-label="Scroll to bottom"]',
                'div[class*="scroll-to-bottom"]',
                'div[class*="ScrollButton"]',
                'button.scroll-to-bottom',
                '.FloatingActionButtons button',
                'button:has(svg[class*="arrow-down"])',
            ]"""
    if old_sels in sc:
        sc = sc.replace(old_sels, new_sels)
        print("selectors: expanded")

    sc = sc.replace(
        """                    if await btn.count() > 0:
                        await btn.click(timeout=5000)
                        self.logger.info("   ✅ روی دکمه فلش کلیک شد. منتظر بارگذاری جدیدترین پست‌ها...")
""",
        """                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(timeout=4000)
                        self.logger.info(f"   ✅ دکمه پرش کلیک شد ({sel})")
""",
    )

    marker = '                self.logger.info("   ℹ️ دکمه پرش به پایین پیدا نشد. ادامه با وضعیت فعلی.")'
    js_fallback = '''                self.logger.info("   ℹ️ دکمه پرش پیدا نشد — تلاش با End و اسکرول JS...")
                try:
                    await page.keyboard.press("End")
                    await human_sleep(0.4, 0.1)
                    await page.keyboard.press("Control+End")
                    await human_sleep(0.5, 0.1)
                except Exception:
                    pass
                try:
                    await page.evaluate("""() => {
                        const sels = ['.MessageList','[class*="MessageList"]','.messages-container',
                                      '[class*="messages"]','.Transition_slide-active'];
                        for (const s of sels) {
                            const el = document.querySelector(s);
                            if (el) { try { el.scrollTop = el.scrollHeight; } catch (e) {} }
                        }
                        if (document.scrollingElement) {
                            document.scrollingElement.scrollTop = document.scrollingElement.scrollHeight;
                        }
                        window.scrollTo(0, document.body.scrollHeight);
                    }""")
                    for _i in range(5):
                        await page.evaluate("window.scrollBy(0, 1200)")
                        await human_sleep(0.4, 0.1)
                    self.logger.info("   ✅ اسکرول JS به انتهای لیست")
                    clicked = True
                except Exception as e:
                    self.logger.warning(f"   ⚠️ اسکرول JS: {e}")
'''
    if marker in sc and "اسکرول JS به انتهای لیست" not in sc:
        sc = sc.replace(marker, js_fallback)
        print("js fallback: added")
    elif "اسکرول JS به انتهای لیست" in sc:
        print("js fallback: already present")

    if sc != orig:
        path.write_text(sc, encoding="utf-8")
        print(f"wrote {path}")
    else:
        print("no file changes")

    py_compile.compile(str(path), doraise=True)
    print("SYNTAX OK")


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/scripts/scraper.py")
    patch(target)
