#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import csv
import os
import re
import zipfile
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

class OutputGenerator:
    """تولید خروجی‌های JSON، CSV، HTML و ZIP — هماهنگ با ورک‌فلو"""

    def __init__(self, base_dir: Path, channel: str, posts: list, media_map: dict, debug_mode: bool = False):
        self.base_dir = base_dir
        self.channel = channel
        self.posts = posts
        self.media_map = media_map
        self.debug_mode = debug_mode
        self.logger = logging.getLogger("TelegramScraper")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """جایگزینی کاراکترهای غیرمجاز در نام فایل"""
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    def generate_json(self):
        safe_name = self._sanitize_filename(self.channel)
        json_path = self.base_dir / f"{safe_name}_posts.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.posts, f, indent=2, ensure_ascii=False)
        self.logger.info(f"📄 JSON: {json_path.name}")

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

    def generate_html(self):
        safe_name = self._sanitize_filename(self.channel)
        html_path = self.base_dir / f"{safe_name}_posts.html"
        current_iran = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).strftime('%Y/%m/%d - %H:%M')
        html = self._build_html_content(current_iran)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        self.logger.info(f"🌐 HTML: {html_path.name}")

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
                env = Environment(loader=FileSystemLoader(d), autoescape=select_autoescape(['html', 'xml']))
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
        raise FileNotFoundError("پوشه templates پیدا نشد. لطفاً فایل post_template.html را در یکی از مسیرهای مشخص قرار دهید.")

    def create_zip(self):
        safe_name = self._sanitize_filename(self.channel)
        zip_name = f"{safe_name}_archive.zip"
        zip_path = self.base_dir / zip_name

        # حذف ZIPهای قبلی
        for f in self.base_dir.glob(f"{safe_name}_archive*"):
            f.unlink(missing_ok=True)

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
            for root, _, files in os.walk(self.base_dir):
                for file in files:
                    # رد کردن فایل‌های موقت و خود ZIP
                    if file.startswith("temp_") or file.endswith(('.zip', '.z01', '.z02')):
                        continue
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(self.base_dir)

                    # حذف اسکرین‌شات‌ها در حالت معمولی (غیر دیباگ)
                    if not self.debug_mode and ("screenshots" in str(arcname)):
                        self.logger.debug(f"⏭️ حذف از ZIP: {arcname}")
                        continue

                    zipf.write(file_path, arcname)

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        self.logger.info(f"📦 ZIP آماده شد: {zip_name} ({size_mb:.1f} MB)")

    def run_all(self):
        """اجرای تمام مراحل تولید خروجی به‌صورت یکجا"""
        self.generate_json()
        self.generate_csv()
        self.generate_html()
        self.create_zip()
