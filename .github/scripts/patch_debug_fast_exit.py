#!/usr/bin/env python3
"""Runtime patch: fast exit when no new posts (auto hourly)."""
from pathlib import Path
import sys
import py_compile

def patch(path: Path) -> None:
    sc = path.read_text(encoding="utf-8")
    orig = sc

    a2 = 'if not items and rounds > 1 and all_items:\n                self.logger.warning("⚠️ resume ناموفق – حدس id قدیمی‌تر")'
    b2 = 'if not items and rounds > 1 and all_items and not getattr(self, "stop_before_id", None):\n                self.logger.warning("⚠️ resume ناموفق – حدس id قدیمی‌تر")'
    if a2 in sc:
        sc = sc.replace(a2, b2, 1)
        print("gated id-guess")
    elif 'not getattr(self, "stop_before_id"' in sc:
        print("id-guess already gated")
    else:
        print("WARN: id-guess block not found")

    if "خروج سریع" not in sc:
        needle = (
            '            self.logger.info(f"📈 +{new_items_count} | مجموع {len(all_items)}/{self.limit}")\n'
            "\n"
            "            if current_timeout > 0:"
        )
        insert = (
            '            self.logger.info(f"📈 +{new_items_count} | مجموع {len(all_items)}/{self.limit}")\n'
            "\n"
            "            # اگر این دور پست جدیدی نبود → خروج سریع\n"
            "            if new_items_count == 0:\n"
            '                if getattr(self, "stop_before_id", None):\n'
            "                    self.logger.info(\n"
            '                        f"✅ پست جدیدی بعد از last_saved={self.stop_before_id} نیست — خروج سریع"\n'
            "                    )\n"
            "                else:\n"
            '                    self.logger.info("✅ این دور پست جدیدی نبود — خروج سریع")\n'
            "                break\n"
            "\n"
            "            if current_timeout > 0:"
        )
        if needle in sc:
            sc = sc.replace(needle, insert, 1)
            print("early exit added")
        else:
            print("WARN: early-exit needle missing")
    else:
        print("early exit exists")

    c = (
        "        if not all_items:\n"
        "            if context:\n"
        "                await context.close()\n"
        "            return"
    )
    d = (
        "        if not all_items:\n"
        '            self.logger.info("ℹ️ هیچ پست جدیدی برای ذخیره نبود — آرشیو قبلی دست‌نخورده می‌ماند")\n'
        "            if context:\n"
        "                await context.close()\n"
        '            self.logger.info("✅ پایان دیباگ (بدون تغییر)")\n'
        "            return"
    )
    if c in sc:
        sc = sc.replace(c, d, 1)
        print("empty-exit message added")
    elif "آرشیو قبلی دست‌نخورده" in sc:
        print("empty-exit exists")
    else:
        print("WARN: empty-exit block not found")

    if sc != orig:
        path.write_text(sc, encoding="utf-8")
        print(f"wrote {path}")
    else:
        print("no file changes")
    py_compile.compile(str(path), doraise=True)
    print("SYNTAX OK")

if __name__ == "__main__":
    patch(Path(sys.argv[1] if len(sys.argv) > 1 else ".github/scripts/debug_scraper.py"))
