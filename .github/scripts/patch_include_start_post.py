#!/usr/bin/env python3
"""Patch scraper: include_start_post=True collects the start_link target itself."""
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/scripts/scraper.py")
src = path.read_text(encoding="utf-8")

# A) Early target found: do NOT put target in seen_ids when include_start_post
old_early = '''                    self.logger.info("✅ پیام هدف به بالای صفحه منتقل شد.")
                    target_found = True
                    # بلافاصله start_collecting را فعال کن تا اسکرول اضافی انجام نشود
                    start_collecting = True
                    seen_ids.add(self.target_msg_id)
                    self.logger.info(f"🎯 شروع جمع‌آوری از پیام هدف {self.target_msg_id}")'''

new_early = '''                    self.logger.info("✅ پیام هدف به بالای صفحه منتقل شد.")
                    target_found = True
                    # بلافاصله start_collecting را فعال کن تا اسکرول اضافی انجام نشود
                    start_collecting = True
                    # INCLUDE_START_POST_PATCH: اگر باید خود پست هدف دانلود شود، آن را در seen نگذار
                    if not getattr(self, "include_start_post", False):
                        seen_ids.add(self.target_msg_id)
                    self.logger.info(f"🎯 شروع جمع‌آوری از پیام هدف {self.target_msg_id}")'''

if old_early in src:
    src = src.replace(old_early, new_early, 1)
    print("OK: early seen_ids")
elif "اگر باید خود پست هدف دانلود شود" in src:
    print("skip: early already patched")
else:
    print("WARN: early target block not found")

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
                                # INCLUDE_START_POST_PATCH
                                if getattr(self, "include_start_post", False):
                                    self.logger.info(f"📌 include_start_post: جمع‌آوری خود پست {msg_id}")
                                else:
                                    seen_ids.add(msg_id)
                                    continue
                            else:
                                continue'''

old1b = '''                        if self.start_link and not start_collecting:
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

if old1 in src:
    src = src.replace(old1, new1, 1)
    print("OK: skip-target (original)")
elif old1b in src:
    print("skip: skip-target already good")
else:
    print("WARN: skip-target not found")

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
                                if include_self:
                                    if mid < tid:
                                        continue
                                elif mid <= tid:
                                    continue
                            else:
                                if include_self:
                                    if mid > tid:
                                        continue
                                elif mid >= tid:
                                    continue'''

if old2 in src:
    src = src.replace(old2, new2, 1)
    print("OK: mid/tid filter")
elif "include_self = getattr(self, \"include_start_post\"" in src or "include_self = getattr(self, 'include_start_post'" in src:
    print("skip: mid/tid already")
else:
    print("WARN: mid/tid not found")

if "self.include_start_post" not in src:
    for n in (
        "self.start_link = getattr(config, 'start_link', None)",
        'self.start_link = getattr(config, "start_link", None)',
    ):
        if n in src:
            src = src.replace(
                n,
                n + "\n        self.include_start_post = bool(getattr(config, 'include_start_post', False))",
                1,
            )
            print("OK: attr")
            break
    else:
        print("WARN: attr insert failed")
else:
    print("skip: attr present")

path.write_text(src, encoding="utf-8")
print("written", path)
