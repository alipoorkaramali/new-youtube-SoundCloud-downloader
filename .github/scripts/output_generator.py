#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ماژول تولید خروجی‌های چندگانه برای اسکرپر تلگرام
---------------------------------------------
این ماژول وظیفه دارد داده‌های استخراج‌شده از کانال تلگرام را به فرمت‌های مختلف
JSON، CSV، HTML و ZIP تبدیل کند. همچنین از قابلیت append_mode برای ادامه‌ی
استخراج (Resume) پشتیبانی می‌کند و در این حالت، فایل‌های قبلی را با داده‌های
جدید ادغام می‌کند بدون اینکه اطلاعات قبلی از بین برود.
"""

import json
import csv
import os
import re
import zipfile
import subprocess
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

# تلاش برای وارد کردن BeautifulSoup برای خواندن فایل‌های HTML
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
    print("⚠️ BeautifulSoup نصب نیست. برای حالت append_mode لطفاً نصب کنید: pip install beautifulsoup4")


class OutputGenerator:
    """
    تولید فایل‌های خروجی JSON، CSV، HTML و ZIP از پست‌های استخراج‌شده.

    ویژگی‌ها:
        - تولید JSON: تمام پست‌ها با ساختار کامل و بدون از دست دادن اطلاعات
        - تولید CSV: داده‌های مهم در فرمت جدولی برای استفاده در صفحه‌گسترده
        - تولید HTML: نمایش زیبا و تعاملی با استفاده از قالب Jinja2
        - تولید ZIP: بسته‌بندی تمام فایل‌ها با قابلیت تقسیم به قطعات ۳۰ مگابایتی
        - Append Mode: در صورت فعال بودن، فایل‌های قبلی را خوانده و با داده‌های جدید ادغام می‌کند
        - مدیریت اسکرین‌شات‌ها: در حالت غیر دیباگ، اسکرین‌شات‌ها از ZIP حذف می‌شوند
        - پاک‌سازی نام فایل‌ها: حذف کاراکترهای غیرمجاز برای سازگاری با سیستم‌عامل‌های مختلف

    Args:
        base_dir (Path): مسیر پایه برای ذخیره فایل‌های خروجی
        channel (str): نام کانال تلگرام (بدون @)
        posts (list): لیست دیکشنری‌های پست‌ها
        media_map (dict): نگاشت شناسه پست به لیست فایل‌های رسانه
        debug_mode (bool): اگر True باشد، اسکرین‌شات‌ها در ZIP نگهداری می‌شوند
        append_mode (bool): اگر True باشد، فایل‌های قبلی با داده‌های جدید ادغام می‌شوند
    """

    def __init__(
        self,
        base_dir: Path,
        channel: str,
        posts: list,
        media_map: dict,
        debug_mode: bool = False,
        append_mode: bool = False
    ):
        """
        سازنده کلاس OutputGenerator.

        Args:
            base_dir (Path): مسیر پایه ذخیره‌سازی
            channel (str): نام کانال
            posts (list): لیست پست‌ها
            media_map (dict): نقشه رسانه‌ها
            debug_mode (bool): حالت دیباگ
            append_mode (bool): حالت ادامه/ادغام
        """
        self.base_dir = base_dir
        self.channel = channel
        self.posts = posts
        self.media_map = media_map
        self.debug_mode = debug_mode
        self.append_mode = append_mode
        self.logger = logging.getLogger("TelegramScraper")

        # اطمینان از وجود پوشه خروجی
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # ذخیره نام پاک‌سازی‌شده برای استفاده مکرر
        self._safe_name = self._sanitize_filename(self.channel)

    # ═══════════════════════════════════════════════════════════════════
    # متدهای کمکی
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """
        پاک‌سازی نام فایل با حذف کاراکترهای غیرمجاز.

        کاراکترهای غیرمجاز در سیستم‌عامل‌های مختلف:
            Windows: < > : " / \ | ? *
            Linux/Unix: / (تنها کاراکتر ممنوع)

        Args:
            name (str): نام اصلی

        Returns:
            str: نام پاک‌سازی‌شده
        """
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    # ═══════════════════════════════════════════════════════════════════
    # ادغام با داده‌های قبلی (Append Mode)
    # ═══════════════════════════════════════════════════════════════════

    def _merge_with_existing_posts(self) -> list:
        """
        خواندن داده‌های قبلی از فایل JSON یا HTML و ادغام با پست‌های جدید.

        استراتژی:
            ۱. ابتدا فایل JSON را امتحان می‌کند (دقیق‌ترین منبع)
            ۲. اگر JSON موجود نبود یا خطا داشت، از HTML به‌عنوان پشتیبان استفاده می‌کند
            ۳. پست‌های تکراری بر اساس `id` حذف می‌شوند
            ۴. مرتب‌سازی نزولی بر اساس `id` (جدیدترین در بالا)

        Returns:
            list: لیست نهایی پست‌ها پس از ادغام
        """
        if not self.append_mode:
            return self.posts

        json_path = self.base_dir / f"{self._safe_name}_posts.json"
        html_path = self.base_dir / f"{self._safe_name}_posts.html"
        existing_posts = []

        # ─── مرحله ۱: تلاش برای خواندن از JSON ──────────────────
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    existing_posts = json.load(f)
                self.logger.info(
                    f"📄 {len(existing_posts)} پست از فایل JSON قبلی بارگذاری شد: {json_path.name}"
                )
            except (json.JSONDecodeError, IOError) as e:
                self.logger.warning(
                    f"⚠️ خطا در خواندن JSON: {e}. تلاش برای خواندن HTML..."
                )
                existing_posts = []

        # ─── مرحله ۲: در صورت عدم موفقیت JSON، از HTML استفاده کن ──
        if not existing_posts and html_path.exists():
            self.logger.info(f"📄 تلاش برای خواندن پست‌ها از فایل HTML: {html_path.name}")

            if BeautifulSoup is None:
                self.logger.warning("⚠️ BeautifulSoup نصب نیست، نمی‌توان HTML را خواند.")
            else:
                try:
                    with open(html_path, 'r', encoding='utf-8') as f:
                        soup = BeautifulSoup(f, 'html.parser')

                    # جستجوی تمام divهای با کلاس 'post'
                    post_divs = soup.find_all('div', class_='post')
                    self.logger.debug(f"🔍 تعداد divهای با کلاس 'post': {len(post_divs)}")

                    for div in post_divs:
                        msg_id = div.get('data-msg-id')
                        if msg_id:
                            text_div = div.find('div', class_='text')
                            date_div = div.find('div', class_='date')
                            existing_posts.append({
                                'id': msg_id,
                                'text': text_div.get_text(strip=True) if text_div else '',
                                'date': date_div.get_text(strip=True) if date_div else ''
                            })

                    if existing_posts:
                        self.logger.info(
                            f"📄 {len(existing_posts)} پست از فایل HTML قبلی استخراج شد."
                        )
                    else:
                        self.logger.warning(
                            "⚠️ در فایل HTML هیچ پستی با ساختار مورد انتظار یافت نشد."
                        )

                except Exception as e:
                    self.logger.warning(f"⚠️ خطا در خواندن HTML: {e}")

        # ─── مرحله ۳: اگر هیچ داده‌ای یافت نشد ──────────────────
        if not existing_posts:
            self.logger.info("ℹ️ هیچ پست قبلی یافت نشد. فقط پست‌های جدید ذخیره می‌شوند.")
            return self.posts

        # ─── مرحله ۴: ترکیب و حذف تکراری‌ها ──────────────────
        all_posts = existing_posts + self.posts
        seen_ids = set()
        unique_posts = []

        for post in all_posts:
            post_id = post.get('id')
            if post_id and post_id not in seen_ids:
                seen_ids.add(post_id)
                unique_posts.append(post)
            elif post_id:
                self.logger.debug(f"⏭️ پست تکراری حذف شد: id={post_id}")

        # ─── مرحله ۵: مرتب‌سازی نزولی ──────────────────────────
        unique_posts.sort(key=lambda x: int(x.get('id', 0)), reverse=True)

        self.logger.info(
            f"🔄 append_mode: {len(existing_posts)} پست قبلی + "
            f"{len(self.posts)} پست جدید = {len(unique_posts)} پست کل "
            f"(پس از حذف {len(all_posts) - len(unique_posts)} تکراری)"
        )

        return unique_posts

    # ═══════════════════════════════════════════════════════════════════
    # تولید فایل‌های خروجی
    # ═══════════════════════════════════════════════════════════════════

    def generate_json(self) -> None:
        """
        تولید فایل JSON با تمام پست‌ها.

        ساختار JSON شامل لیستی از دیکشنری‌ها با کلیدهای:
            - id: شناسه عددی پست
            - date: تاریخ انتشار
            - text: متن پست
            - url: لینک مستقیم به پست
            - views: تعداد بازدید
            - forwards: تعداد بازنشر
            - replies: تعداد پاسخ‌ها
        """
        json_path = self.base_dir / f"{self._safe_name}_posts.json"
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(self.posts, f, indent=2, ensure_ascii=False)
            self.logger.info(f"📄 JSON: {json_path.name} ({len(self.posts)} پست)")
        except Exception as e:
            self.logger.error(f"❌ خطا در ذخیره JSON: {e}")
            raise

    def generate_csv(self) -> None:
        """
        تولید فایل CSV برای استفاده در صفحه‌گسترده.

        ستون‌های CSV:
            - id: شناسه عددی
            - date: تاریخ
            - text: متن
            - url: لینک
            - views: بازدید
            - forwards: بازنشر
            - replies: پاسخ‌ها
        """
        if not self.posts:
            self.logger.warning("ℹ️ هیچ پستی برای تولید CSV وجود ندارد.")
            return

        csv_path = self.base_dir / f"{self._safe_name}_posts.csv"
        fieldnames = ['id', 'date', 'text', 'url', 'views', 'forwards', 'replies']

        try:
            with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                for post in self.posts:
                    # اطمینان از وجود همه فیلدها
                    row = {field: post.get(field, '') for field in fieldnames}
                    writer.writerow(row)
            self.logger.info(f"📊 CSV: {csv_path.name} ({len(self.posts)} پست)")
        except Exception as e:
            self.logger.error(f"❌ خطا در ذخیره CSV: {e}")
            raise

    def generate_html(self) -> None:
        """
        تولید فایل HTML با استفاده از قالب Jinja2.

        در صورت فعال بودن append_mode:
            ۱. پست‌های قبلی را از JSON/HTML می‌خواند
            ۲. با پست‌های جدید ادغام می‌کند
            ۳. تکراری‌ها را حذف می‌کند
            ۴. مرتب‌سازی نزولی انجام می‌دهد

        فایل HTML شامل:
            - تمام پست‌ها با فرمت زیبا
            - هشتگ‌های هایلایت‌شده
            - تاریخ و زمان انتشار
            - رسانه‌های مرتبط (در صورت وجود)
        """
        # ─── ادغام در صورت نیاز ──────────────────────────────────
        if self.append_mode:
            self.logger.info("🔄 append_mode فعال است. تلاش برای ادغام با داده‌های قبلی...")
            merged_posts = self._merge_with_existing_posts()
            if len(merged_posts) != len(self.posts):
                self.logger.info(
                    f"📊 تعداد پست‌ها پس از ادغام: {len(merged_posts)} "
                    f"(قبلاً {len(self.posts)})"
                )
            self.posts = merged_posts
        else:
            self.logger.info("ℹ️ append_mode غیرفعال است. فایل HTML از نو ساخته می‌شود.")

        # ─── تولید HTML ──────────────────────────────────────────
        html_path = self.base_dir / f"{self._safe_name}_posts.html"
        current_iran = (
            datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
        ).strftime('%Y/%m/%d - %H:%M')

        try:
            html_content = self._build_html_content(current_iran)
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            self.logger.info(
                f"🌐 HTML: {html_path.name} ({len(self.posts)} پست)"
            )
        except Exception as e:
            self.logger.error(f"❌ خطا در تولید HTML: {e}")
            raise

    def _build_html_content(self, current_iran: str) -> str:
        """
        ساخت محتوای HTML با استفاده از قالب Jinja2.

        مسیرهای جستجو برای فایل قالب:
            ۱. پوشه templates در کنار فایل فعلی
            ۲. پوشه templates در مسیر والد
            ۳. پوشه templates در مسیر اجرا
            ۴. پوشه .github/templates در مسیر اجرا

        Args:
            current_iran (str): زمان فعلی به‌وقت ایران

        Returns:
            str: محتوای HTML کامل

        Raises:
            FileNotFoundError: اگر هیچ قالب مناسبی پیدا نشود
        """
        script_dir = Path(__file__).resolve().parent
        template_dirs = [
            script_dir / "templates",
            script_dir.parent / "templates",
            Path.cwd() / "templates",
            Path.cwd() / ".github" / "templates",
        ]

        for template_dir in template_dirs:
            template_file = template_dir / "post_template.html"
            if template_file.exists():
                self.logger.debug(f"✅ قالب پیدا شد: {template_file}")

                env = Environment(
                    loader=FileSystemLoader(template_dir),
                    autoescape=select_autoescape(['html', 'xml'])
                )

                # افزودن فیلتر برای هایلایت هشتگ‌ها
                def hashtagify(text: str) -> Markup:
                    return Markup(
                        re.sub(
                            r'(#\w+)',
                            r'<span class="hashtag">\1</span>',
                            str(text)
                        )
                    )

                env.filters['hashtagify'] = hashtagify
                template = env.get_template('post_template.html')

                return template.render(
                    channel=self.channel,
                    posts=self.posts,
                    media_map=self.media_map,
                    current_time=current_iran
                )

        # اگر هیچ قالبی پیدا نشد
        raise FileNotFoundError(
            "❌ پوشه templates پیدا نشد. لطفاً فایل post_template.html را در یکی از مسیرهای زیر قرار دهید:\n" +
            "\n".join(f"  - {d}" for d in template_dirs)
        )

    def create_zip(self) -> None:
        """
        تولید فایل ZIP از تمام فایل‌های خروجی با قابلیت تقسیم‌بندی.

        ویژگی‌ها:
            - استفاده از فشرده‌سازی DEFLATED
            - حذف اسکرین‌شات‌ها در حالت غیر دیباگ
            - تقسیم فایل‌های بزرگتر از ۳۰ مگابایت به قطعات
            - حذف ZIPهای قبلی قبل از ساخت ZIP جدید

        نیازمندی‌های سیستمی:
            - دستور `zip` برای تقسیم‌بندی (در صورت نصب نبودن، فایل کامل ذخیره می‌شود)
        """
        zip_name = f"{self._safe_name}_archive.zip"
        zip_path = self.base_dir / zip_name
        temp_zip = self.base_dir / "temp_archive.zip"

        # ─── حذف ZIPهای قبلی ────────────────────────────────────
        for file in os.listdir(self.base_dir):
            if file.startswith(f"{self._safe_name}_archive") and (
                file.endswith('.zip') or '.z' in file
            ):
                (self.base_dir / file).unlink(missing_ok=True)
                self.logger.debug(f"🗑️ حذف ZIP قدیمی: {file}")

        # ─── ساخت ZIP موقت ──────────────────────────────────────
        try:
            with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(self.base_dir):
                    for file in files:
                        # رد کردن فایل‌های موقت و خود ZIP
                        if (
                            file.startswith("temp_archive") or
                            file.startswith(f"{self._safe_name}_archive")
                        ):
                            continue

                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, self.base_dir)

                        # حذف اسکرین‌شات‌ها در حالت غیر دیباگ
                        if not self.debug_mode:
                            if arcname.startswith("post_screenshots/") or \
                               arcname.startswith("debug_screenshots/"):
                                self.logger.debug(f"⏭️ حذف اسکرین‌شات از ZIP: {arcname}")
                                continue

                        zipf.write(file_path, arcname)

        except Exception as e:
            self.logger.error(f"❌ خطا در ساخت ZIP: {e}")
            raise

        # ─── بررسی حجم و تقسیم‌بندی ─────────────────────────────
        size_mb = os.path.getsize(temp_zip) / (1024 * 1024)
        self.logger.info(f"📦 حجم فایل ZIP: {size_mb:.1f} MB")

        MAX_SPLIT_MB = 30

        if size_mb > MAX_SPLIT_MB:
            self.logger.info(f"📦 تقسیم فایل ZIP به قطعات {MAX_SPLIT_MB} مگابایتی...")

            try:
                # بررسی وجود دستور zip
                subprocess.run(["zip", "--version"], check=True, capture_output=True)

                cmd = [
                    "zip", "-s", f"{MAX_SPLIT_MB}m",
                    str(temp_zip), "--out", str(zip_path)
                ]
                result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                os.remove(temp_zip)

                # نمایش قطعات ایجاد شده
                parts = sorted([
                    f for f in os.listdir(self.base_dir)
                    if f.startswith(f"{self._safe_name}_archive")
                ])
                self.logger.info(f"✅ فایل ZIP به {len(parts)} قطعه تقسیم شد:")
                for part in parts:
                    part_size = os.path.getsize(self.base_dir / part) / (1024 * 1024)
                    self.logger.info(f"   - {part} ({part_size:.1f} MB)")

            except subprocess.CalledProcessError as e:
                self.logger.error(f"❌ خطا در تقسیم ZIP: {e.stderr}")
                os.rename(temp_zip, zip_path)
                self.logger.warning(f"⚠️ تقسیم ناموفق – فایل کامل ZIP ذخیره شد: {zip_name}")

            except FileNotFoundError:
                self.logger.error("❌ دستور 'zip' پیدا نشد. لطفاً zip را نصب کنید (apt install zip).")
                os.rename(temp_zip, zip_path)
                self.logger.warning(f"⚠️ فایل کامل ZIP (بدون تقسیم) ذخیره شد: {zip_name}")

        else:
            os.rename(temp_zip, zip_path)
            self.logger.info(f"ℹ️ حجم ZIP کمتر از {MAX_SPLIT_MB}MB است – تقسیم نیاز نیست")
            self.logger.info(f"✅ فایل ZIP آماده شد: {zip_name}")

    # ═══════════════════════════════════════════════════════════════════
    # اجرای یک‌جای همه مراحل
    # ═══════════════════════════════════════════════════════════════════

    def run_all(self) -> None:
        """
        اجرای تمام مراحل تولید خروجی به‌ترتیب.

        ترتیب اجرا:
            ۱. تولید JSON
            ۲. تولید CSV
            ۳. تولید HTML (با ادغام در صورت نیاز)
            ۴. تولید ZIP
        """
        self.logger.info("🚀 شروع تولید فایل‌های خروجی...")

        try:
            self.generate_json()
            self.generate_csv()
            self.generate_html()
            self.create_zip()
            self.logger.info("✅ تمام فایل‌های خروجی با موفقیت تولید شدند.")

        except Exception as e:
            self.logger.error(f"❌ خطا در تولید خروجی: {e}")
            raise
