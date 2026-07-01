#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import csv
import os
import re
import zipfile
import subprocess
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup


class OutputGenerator:
    """
    تولید فایل‌های خروجی JSON، CSV، HTML و ZIP
    – در صورت حجم بالای ZIP، آن را با دستور `zip -s` به قطعات ۳۰ مگابایتی تقسیم می‌کند.
    – در حالت غیر دیباگ، اسکرین‌شات‌ها از ZIP حذف می‌شوند.
    – نام فایل‌ها با `_sanitize_filename` پاک‌سازی می‌شوند.
    """

    def __init__(self, base_dir: Path, channel: str, posts: list, media_map: dict, debug_mode: bool = False):
        self.base_dir = base_dir
        self.channel = channel
        self.posts = posts
        self.media_map = media_map
        self.debug_mode = debug_mode
        self.logger = logging.getLogger("TelegramScraper")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ════════════════════════════════════════════════════════════════
    # متد کمکی: پاک‌سازی نام فایل
    # ════════════════════════════════════════════════════════════════
    @staticmethod
    def _sanitize_filename(name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    # ════════════════════════════════════════════════════════════════
    # تولید JSON
    # ════════════════════════════════════════════════════════════════
    def generate_json(self):
        safe_name = self._sanitize_filename(self.channel)
        json_path = self.base_dir / f"{safe_name}_posts.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.posts, f, indent=2, ensure_ascii=False)
        self.logger.info(f"📄 JSON: {json_path.name}")

    # ════════════════════════════════════════════════════════════════
    # تولید CSV
    # ════════════════════════════════════════════════════════════════
    def generate_csv(self):
        if not self.posts:
            return
        safe_name = self._sanitize_filename(self.channel)
        csv_path = self.base_dir / f"{safe_name}_posts.csv"
        fieldnames = ['id', 'date', 'text', 'url', 'views', 'forwards', 'replies']
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for post in self.posts:
                writer.writerow(post)
        self.logger.info(f"📊 CSV: {csv_path.name}")

    # ════════════════════════════════════════════════════════════════
    # تولید HTML
    # ════════════════════════════════════════════════════════════════
    def generate_html(self):
        safe_name = self._sanitize_filename(self.channel)
        html_path = self.base_dir / f"{safe_name}_posts.html"
        current_iran = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).strftime('%Y/%m/%d - %H:%M')
        html = self._build_html_content(current_iran)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        self.logger.info(f"🌐 HTML: {html_path.name}")

    # ════════════════════════════════════════════════════════════════
    # ساخت محتوای HTML با قالب (جستجوی خودکار در چند مسیر)
    # ════════════════════════════════════════════════════════════════
    def _build_html_content(self, current_iran: str) -> str:
        script_dir = Path(__file__).resolve().parent
        template_dirs = [
            script_dir / "templates",
            script_dir.parent / "templates",
            Path.cwd() / "templates",
            Path.cwd() / ".github" / "templates",
        ]
        for d in template_dirs:
            if (d / "post_template.html").exists():
                env = Environment(
                    loader=FileSystemLoader(d),
                    autoescape=select_autoescape(['html', 'xml'])
                )

                def hashtagify(text):
                    return Markup(re.sub(r'(#\w+)', r'<span class="hashtag">\1</span>', str(text)))

                env.filters['hashtagify'] = hashtagify
                template = env.get_template('post_template.html')
                return template.render(
                    channel=self.channel,
                    posts=self.posts,
                    media_map=self.media_map,
                    current_time=current_iran
                )

        raise FileNotFoundError(
            "پوشه templates پیدا نشد. لطفاً فایل post_template.html را در یکی از مسیرهای زیر قرار دهید:\n" +
            "\n".join(f"  - {d}" for d in template_dirs)
        )

    # ════════════════════════════════════════════════════════════════
    # تولید ZIP (با تقسیم‌بندی به قطعات ۳۰ مگابایتی با `zip -s`)
    # ════════════════════════════════════════════════════════════════
    def create_zip(self):
        safe_name = self._sanitize_filename(self.channel)
        zip_name = f"{safe_name}_archive.zip"
        zip_path = self.base_dir / zip_name

        # حذف ZIPهای قبلی (هم قطعات و هم فایل کامل)
        for f in os.listdir(self.base_dir):
            if f.startswith(f"{safe_name}_archive") and (f.endswith('.zip') or '.z' in f):
                (self.base_dir / f).unlink(missing_ok=True)

        temp_zip = self.base_dir / "temp_archive.zip"

        # ─── ساخت ZIP موقت ────────────────────────────────────────
        with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(self.base_dir):
                for file in files:
                    # رد کردن فایل‌های موقت و خود ZIPها
                    if file.startswith("temp_archive") or file.startswith(f"{safe_name}_archive"):
                        continue

                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, self.base_dir)

                    # حذف اسکرین‌شات‌ها در حالت غیر دیباگ
                    if not self.debug_mode:
                        if arcname.startswith("post_screenshots/") or arcname.startswith("debug_screenshots/"):
                            self.logger.debug(f"⏭️ حذف اسکرین‌شات از ZIP: {arcname}")
                            continue

                    zipf.write(file_path, arcname)

        size_mb = os.path.getsize(temp_zip) / (1024 * 1024)
        self.logger.info(f"📦 حجم فایل ZIP: {size_mb:.1f} MB")

        MAX_SPLIT_MB = 30

        # ─── تقسیم‌بندی در صورت نیاز ────────────────────────────
        if size_mb > MAX_SPLIT_MB:
            self.logger.info(f"📦 تقسیم فایل ZIP به قطعات {MAX_SPLIT_MB} مگابایتی...")
            try:
                cmd = ["zip", "-s", f"{MAX_SPLIT_MB}m", str(temp_zip), "--out", str(zip_path)]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                os.remove(temp_zip)

                parts = sorted([f for f in os.listdir(self.base_dir) if f.startswith(f"{safe_name}_archive")])
                self.logger.info(f"✅ فایل ZIP به {len(parts)} قطعه تقسیم شد:")
                for p in parts:
                    part_size = os.path.getsize(self.base_dir / p) / (1024 * 1024)
                    self.logger.info(f"   - {p} ({part_size:.1f} MB)")

            except subprocess.CalledProcessError as e:
                self.logger.error(f"❌ خطا در تقسیم فایل ZIP: {e.stderr}")
                os.rename(temp_zip, zip_path)
                self.logger.info(f"⚠️ تقسیم ناموفق بود – فایل کامل ZIP ذخیره شد: {zip_name}")

            except FileNotFoundError:
                self.logger.error("❌ دستور 'zip' پیدا نشد. لطفاً zip را نصب کنید (apt install zip).")
                os.rename(temp_zip, zip_path)
                self.logger.info(f"⚠️ فایل کامل ZIP (بدون تقسیم) ذخیره شد: {zip_name}")

        else:
            os.rename(temp_zip, zip_path)
            self.logger.info(f"ℹ️ حجم ZIP کمتر از {MAX_SPLIT_MB}MB است – تقسیم نیاز نیست")
            self.logger.info(f"✅ فایل ZIP آماده شد: {zip_name}")

    # ════════════════════════════════════════════════════════════════
    # اجرای یک‌جای همه مراحل
    # ════════════════════════════════════════════════════════════════
    def run_all(self):
        self.generate_json()
        self.generate_csv()
        self.generate_html()
        self.create_zip()
