#!/usr/bin/env python3
"""Patch scraper: when include_start_post=True, collect the start_link target itself (not the previous post)."""
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/scripts/scraper.py")
src = path.read_text(encoding="utf-8")

if "include_start_post" in src and "INCLUDE_START_POST_PATCH" in src:
    print("already patched")
    sys.exit(0)

# 1) Skip-target continue block
old1 = '''                        if self.start_link and not start_collecting:
                            if msg_id == self.target_msg_id:
                                start_collecting = True
                                self.logger.info(f"🎯 به پیام هدف رسیدیم (ID: {msg_id})، شروع جمع‌آوری...")
                                seen_ids.add(msg_id)
                                continue  # خود پیام هدف را جمع نمی‌کنیم (قبلاً اسکرپ شده)
                            else:
                                continue'''

new1 = '''                        if self.start_link and not start_collecting:
                            if msg_id == self.target_msg_id:
                                start_collecting = True
                                self.logger.info(f"🎯 به پیام هدف رسیدیم (ID: {msg_id})، شروع جمع‌آوری...")
                                # INCLUDE_START_POST_PATCH: اگر include_start_post=True خود پست هدف را هم جمع کن
                                if getattr(self, "include_start_post", False):
                                    self.logger.info(f"📌 include_start_post: جمع‌آوری خود پست {msg_id}")
                                    # fall through to extract this message (do not continue)
                                else:
                                    seen_ids.add(msg_id)
                                    continue  # خود پیام هدف را جمع نمی‌کنیم (قبلاً اسکرپ شده)
                            else:
                                continue'''

old2 = '''                        if self.start_link and self.target_msg_id:
                            try:
                                mid, tid = int(msg_id), int(self.target_msg_id)
                            except (TypeError, ValueError):
                                mid, tid = 0, 0
                            if self.scroll_direction == "down":
                                if mid <= tid:
                                    continue
                            else:
                                if mid >= tid:
                                    continue'''

new2 = '''                        if self.start_link and self.target_msg_id:
                            try:
                                mid, tid = int(msg_id), int(self.target_msg_id)
                            except (TypeError, ValueError):
                                mid, tid = 0, 0
                            include_self = getattr(self, "include_start_post", False)
                            if self.scroll_direction == "down":
                                # down: only newer than target (or equal if include_start_post)
                                if include_self:
                                    if mid < tid:
                                        continue
                                elif mid <= tid:
                                    continue
                            else:
                                # up: only older than target (or equal if include_start_post)
                                if include_self:
                                    if mid > tid:
                                        continue
                                elif mid >= tid:
                                    continue'''

ok = True
if old1 in src:
    src = src.replace(old1, new1, 1)
    print("OK: skip-target block")
else:
    print("WARN: skip-target block not found")
    ok = False

if old2 in src:
    src = src.replace(old2, new2, 1)
    print("OK: mid/tid filter")
else:
    print("WARN: mid/tid filter not found")
    ok = False

inserted = False
for n in (
    "self.start_link = getattr(config, 'start_link', None)",
    'self.start_link = getattr(config, "start_link", None)',
):
    if n in src and "self.include_start_post" not in src:
        src = src.replace(
            n,
            n + "\n        self.include_start_post = bool(getattr(config, 'include_start_post', False))",
            1,
        )
        print("OK: include_start_post attr")
        inserted = True
        break
if not inserted and "self.include_start_post" in src:
    print("skip: attr already present")
elif not inserted:
    print("WARN: could not insert attr")

path.write_text(src, encoding="utf-8")
print("written", path, "ok=", ok)
