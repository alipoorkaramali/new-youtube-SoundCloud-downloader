#!/usr/bin/env python3
"""Patch scraper.py: jump-to-bottom + respect scroll_direction after start_link."""
from pathlib import Path
import re
import sys

def patch(path: Path) -> bool:
    sc = path.read_text(encoding="utf-8")
    orig = sc
    changed = False

    if "SCROLL_DOWN" not in sc:
        sc = sc.replace("SCROLL_UP = -1200", "SCROLL_UP = -1200\nSCROLL_DOWN = 1200")
        changed = True

    if "mid <= tid" not in sc and "int(msg_id) >= int(self.target_msg_id)" in sc:
        sc = sc.replace(
            """                        if self.start_link and int(msg_id) >= int(self.target_msg_id):
                            self.logger.debug(f\"⏭️ پست {msg_id} جدیدتر یا مساوی هدف است، رد می‌شود.\")
                            continue
""",
            """                        if self.start_link and self.target_msg_id:
                            try:
                                mid, tid = int(msg_id), int(self.target_msg_id)
                            except (TypeError, ValueError):
                                mid, tid = 0, 0
                            if self.scroll_direction == \"down\":
                                if mid <= tid:
                                    continue
                            else:
                                if mid >= tid:
                                    continue
""",
        )
        changed = True

    def scroll_repl(m):
        indent = m.group(1)
        return (
            f'{indent}if self.scroll_direction == "down":\n'
            f'{indent}    self.logger.info("⬇️ بارگذاری پست‌های جدیدتر با اسکرول به پایین...")\n'
            f'{indent}    _amt = 1200\n'
            f'{indent}else:\n'
            f'{indent}    self.logger.info("⬆️ بارگذاری پست‌های قدیمی‌تر با اسکرول به بالا...")\n'
            f'{indent}    _amt = SCROLL_UP\n'
            f'{indent}for scroll_step in range(3):\n'
            f'{indent}    await page.evaluate(f"window.scrollBy(0, {{_amt}})")\n'
        )

    sc2, n = re.subn(
        r'(\s*)self\.logger\.info\("⬆️ بارگذاری پست‌های قدیمی‌تر با اسکرول به بالا\.\.\."\)\s*\n'
        r'\s*for scroll_step in range\(3\):\s*\n'
        r'\s*await page\.evaluate\(f"window\.scrollBy\(0, \{SCROLL_UP\}\)"\)\s*\n',
        scroll_repl,
        sc,
    )
    if n:
        sc = sc2
        changed = True
        print(f"scroll init blocks fixed: {n}")

    if "اسکرول JS به انتهای لیست" not in sc:
        weak_start = 'self.logger.info("⬇️ تلاش برای پرش به جدیدترین پست‌ها...")'
        if weak_start in sc:
            idx = sc.find(weak_start)
            end_marker = 'دکمه پرش به پایین پیدا نشد. ادامه با وضعیت فعلی.")'
            end = sc.find(end_marker, idx)
            if end > 0:
                end = sc.find("\n", end) + 1
                line_start = sc.rfind("\n", 0, idx) + 1
                indent = sc[line_start:idx]
                strong = '''self.logger.info("⬇️ تلاش چندلایه برای پرش به جدیدترین پست‌ها...")
clicked = False
scroll_button_selectors = [
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
]
for sel in scroll_button_selectors:
    try:
        btn = page.locator(sel).first
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click(timeout=4000)
            self.logger.info(f"   ✅ دکمه پرش کلیک شد ({sel})")
            clicked = True
            await human_sleep(2.5, 0.3)
            break
    except Exception:
        continue
try:
    await page.keyboard.press("End")
    await human_sleep(0.4, 0.1)
    await page.keyboard.press("Control+End")
    await human_sleep(0.6, 0.2)
except Exception:
    pass
try:
    await page.evaluate("""() => {
        const sels = ['.MessageList','[class*="MessageList"]','.messages-container',
                      '[class*="messages"]','.Transition_slide-active'];
        for (const s of sels) {
            const el = document.querySelector(s);
            if (el) { try { el.scrollTop = el.scrollHeight; } catch(e) {} }
        }
        if (document.scrollingElement) {
            document.scrollingElement.scrollTop = document.scrollingElement.scrollHeight;
        }
        window.scrollTo(0, document.body.scrollHeight);
    }""")
    for _i in range(5):
        await page.evaluate("window.scrollBy(0, 1200)")
        await human_sleep(0.45, 0.1)
    self.logger.info("   ✅ اسکرول JS به انتهای لیست")
    clicked = True
except Exception as e:
    self.logger.warning(f"   ⚠️ اسکرول JS: {e}")
if clicked:
    self.logger.info("   ✅ پرش به جدیدترین پست‌ها انجام شد")
else:
    self.logger.warning("   ⚠️ پرش به پایین ممکن است کامل نباشد")
'''
                strong_indented = "\n".join(
                    (indent + ln if ln.strip() else "") for ln in strong.strip("\n").split("\n")
                ) + "\n"
                sc = sc[:idx] + strong_indented + sc[end:]
                changed = True
                print("jump-to-bottom strengthened")

    if sc != orig:
        path.write_text(sc, encoding="utf-8")
        print(f"patched {path}")
        return True
    print("no changes (already patched or patterns missing)")
    return changed


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/scripts/scraper.py")
    patch(target)
    text = target.read_text(encoding="utf-8")
    ok = ("mid <= tid" in text) or ("اسکرول JS به انتهای لیست" in text)
    print("verify_ok", ok)
    sys.exit(0 if ok else 1)
