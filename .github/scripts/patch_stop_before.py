#!/usr/bin/env python3
"""Add stop_before_id: from channel newest back until saved post boundary."""
from pathlib import Path
import sys
import py_compile


def patch(path: Path) -> None:
    sc = path.read_text(encoding="utf-8")
    orig = sc

    if "self.stop_before_id" not in sc:
        needle = '        self.logger.info(f"🧭 جهت اسکرول: {self.scroll_direction}")'
        insert = (
            '        self.stop_before_id = str(getattr(config, "stop_before_id", "") or "").strip()\n'
            '        if self.stop_before_id:\n'
            '            self.logger.info(\n'
            '                f"🛑 مرز توقف (stop_before_id): {self.stop_before_id} — '
            'پست‌های قدیمی‌تر/مساوی جمع نمی‌شوند"\n'
            '            )\n'
            '        self.logger.info(f"🧭 جهت اسکرول: {self.scroll_direction}")'
        )
        if needle not in sc:
            raise SystemExit("scroll log needle missing")
        sc = sc.replace(needle, insert, 1)
        print("stop_before init added")
    else:
        print("stop_before init exists")

    if 'مرز last_post ذخیره‌شده' not in sc:
        text_marker = "                        # ═══════════════ استخراج هوشمند متن پست ═══════════════"
        stop_block = (
            "                        # مرز last_post ذخیره‌شده: فقط پست‌های جدیدتر از آن\n"
            '                        if getattr(self, "stop_before_id", None):\n'
            "                            try:\n"
            "                                if int(msg_id) <= int(self.stop_before_id):\n"
            "                                    continue\n"
            "                            except (TypeError, ValueError):\n"
            "                                pass\n"
            "\n"
        )
        if text_marker not in sc:
            raise SystemExit("text extraction marker missing")
        sc = sc.replace(text_marker, stop_block + text_marker, 1)
        print("stop_before filter added")
    else:
        print("stop_before filter exists")

    hit_marker = "            # ─── تاخیر برای جلوگیری از بارگذاری بیش از حد ──────"
    if "به مرز stop_before" not in sc and hit_marker in sc:
        hit_code = (
            '            # اگر به مرز stop_before رسیدیم، اسکرول را قطع کن\n'
            '            if getattr(self, "stop_before_id", None) and self.scroll_direction == "up":\n'
            "                try:\n"
            "                    boundary = int(self.stop_before_id)\n"
            "                    if seen_ids:\n"
            "                        min_seen = min(int(x) for x in seen_ids if str(x).isdigit())\n"
            "                        if min_seen <= boundary:\n"
            '                            self.logger.info(\n'
            '                                f"🛑 به مرز stop_before={self.stop_before_id} رسیدیم — توقف اسکرول"\n'
            "                            )\n"
            "                            scroll_attempts = self.max_scroll_attempts\n"
            "                except Exception:\n"
            "                    pass\n"
            "            # ─── تاخیر برای جلوگیری از بارگذاری بیش از حد ──────"
        )
        sc = sc.replace(hit_marker, hit_code, 1)
        print("stop_before early exit added")
    else:
        print("stop_before early exit exists or marker missing")

    if sc != orig:
        path.write_text(sc, encoding="utf-8")
        print(f"wrote {path}")
    else:
        print("no file changes")

    py_compile.compile(str(path), doraise=True)
    print("SYNTAX OK")


if __name__ == "__main__":
    patch(Path(sys.argv[1] if len(sys.argv) > 1 else ".github/scripts/scraper.py"))
