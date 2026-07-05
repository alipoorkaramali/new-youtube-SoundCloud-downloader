#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ماژول تولید خروجی‌های چندگانه برای اسکرپر تلگرام
---------------------------------------------
این ماژول وظیفه دارد داده‌های استخراج‌شده از کانال تلگرام را به فرمت‌های مختلف
JSON، CSV، HTML و ZIP تبدیل کند. همچنین از قابلیت append_mode برای ادامه‌ی
استخراج (Resume) پشتیبانی می‌کند و در این حالت، فایل‌های قبلی را با داده‌های
جدید ادغام می‌کند بدون اینکه اطلاعات قبلی از بین برود.

استراتژی ادغام (Merge Strategy):
    ۱. اولویت اول: خواندن از فایل JSON (دقیق‌ترین و مطمئن‌ترین منبع)
    ۲. در صورت عدم موفقیت یا عدم وجود JSON: خواندن از فایل HTML (به‌عنوان پشتیبان)
    ۳. ترکیب داده‌های قبلی با داده‌های جدید
    ۴. حذف پست‌های تکراری بر اساس `id`
    ۵. مرتب‌سازی نزولی بر اساس `id` (جدیدترین در بالا)

مشکلات رفع‌شده:
    - از دست رفتن پست‌های قدیمی در اجراهای متوالی Resume
    - عدم تشخیص صحیح فایل‌های JSON خراب
    - لاگ‌های ناکافی برای دیباگ فرآیند ادغام
    - عدم مقاومت در برابر خطاهای خواندن فایل
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
from typing import List, Dict, Any, Optional, Union

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

        # ذخیره وضعیت اولیه برای لاگ‌های دقیق‌تر
        self._initial_post_count = len(self.posts)

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

    def _validate_post_structure(self, post: Dict) -> bool:
        """
        اعتبارسنجی ساختار یک پست.

        Args:
            post (Dict): دیکشنری پست

        Returns:
            bool: True اگر ساختار معتبر باشد
        """
        if not isinstance(post, dict):
            return False
        if 'id' not in post:
            return False
        if not post['id']:
            return False
        return True

    def _extract_posts_from_html(self, html_path: Path) -> List[Dict]:
        """
        استخراج پست‌ها از فایل HTML با استفاده از BeautifulSoup.

        Args:
            html_path (Path): مسیر فایل HTML

        Returns:
            List[Dict]: لیست پست‌های استخراج‌شده
        """
        if BeautifulSoup is None:
            self.logger.warning("⚠️ BeautifulSoup نصب نیست، نمی‌توان HTML را خواند.")
            return []

        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')

            existing_posts = []
            # جستجوی تمام divهای با کلاس 'post'
            post_divs = soup.find_all('div', class_='post')
            self.logger.debug(f"🔍 تعداد divهای با کلاس 'post' در HTML: {len(post_divs)}")

            for div in post_divs:
                msg_id = div.get('data-msg-id')
                if msg_id:
                    text_div = div.find('div', class_='text')
                    date_div = div.find('div', class_='date')
                    post_data = {
                        'id': str(msg_id).strip(),
                        'text': text_div.get_text(strip=True) if text_div else '',
                        'date': date_div.get_text(strip=True) if date_div else ''
                    }
                    if self._validate_post_structure(post_data):
                        existing_posts.append(post_data)
                    else:
                        self.logger.debug(f"⚠️ پست نامعتبر در HTML: {post_data}")

            return existing_posts

        except Exception as e:
            self.logger.warning(f"⚠️ خطا در خواندن HTML: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════════
    # ادغام با داده‌های قبلی (Append Mode)
    # ═══════════════════════════════════════════════════════════════════

    def _merge_with_existing_posts(self) -> list:
        """
        خواندن داده‌های قبلی از فایل JSON یا HTML و ادغام با پست‌های جدید.

        استراتژی:
            ۱. ابتدا فایل JSON را امتحان می‌کند (دقیق‌ترین منبع)
            ۲. اگر JSON موجود نبود یا خطا داشت، از HTML به‌عنوان پشتیبان استفاده می‌کند
            ۳. اعتبارسنجی ساختار هر پست
            ۴. پست‌های تکراری بر اساس `id` حذف می‌شوند
            ۵. مرتب‌سازی نزولی بر اساس `id` (جدیدترین در بالا)

        Returns:
            list: لیست نهایی پست‌ها پس از ادغام
        """
        if not self.append_mode:
            self.logger.info("ℹ️ append_mode غیرفعال است. بدون ادغام ادامه می‌یابد.")
            return self.posts

        self.logger.info("🔄 شروع فرآیند ادغام با داده‌های قبلی...")

        json_path = self.base_dir / f"{self._safe_name}_posts.json"
        html_path = self.base_dir / f"{self._safe_name}_posts.html"
        existing_posts = []

        # ─── مرحله ۱: تلاش برای خواندن از JSON (اولویت اول) ──
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)

                # اعتبارسنجی داده‌ها
                if not isinstance(raw_data, list):
                    self.logger.warning(f"⚠️ فایل JSON حاوی لیست نیست: {type(raw_data)}")
                    raise ValueError("JSON must contain a list")

                # فیلتر کردن پست‌های معتبر
                for post in raw_data:
                    if self._validate_post_structure(post):
                        existing_posts.append(post)
                    else:
                        self.logger.debug(f"⚠️ پست نامعتبر در JSON: {post}")

                self.logger.info(
                    f"📄 {len(existing_posts)} پست معتبر از فایل JSON قبلی بارگذاری شد: {json_path.name}"
                )

            except json.JSONDecodeError as e:
                self.logger.warning(f"⚠️ خطا در دیکد JSON (نقص در ساختار): {e}")
                self.logger.info("ℹ️ تلاش برای خواندن از HTML به‌عنوان پشتیبان...")
                existing_posts = []

            except (IOError, OSError) as e:
                self.logger.warning(f"⚠️ خطای ورودی/خروجی در خواندن JSON: {e}")
                existing_posts = []

            except Exception as e:
                self.logger.warning(f"⚠️ خطای غیرمنتظره در خواندن JSON: {e}")
                existing_posts = []

        # ─── مرحله ۲: اگر JSON موفق نبود، از HTML استفاده کن ──
        if not existing_posts and html_path.exists():
            self.logger.info(f"📄 تلاش برای خواندن پست‌ها از فایل HTML: {html_path.name}")
            html_posts = self._extract_posts_from_html(html_path)

            if html_posts:
                existing_posts = html_posts
                self.logger.info(
                    f"📄 {len(existing_posts)} پست از فایل HTML قبلی استخراج شد."
                )
            else:
                self.logger.warning(
                    "⚠️ در فایل HTML هیچ پست معتبری یافت نشد."
                )

        # ─── مرحله ۳: اگر هیچ داده‌ای یافت نشد ──────────────────
        if not existing_posts:
            self.logger.info("ℹ️ هیچ پست قبلی یافت نشد. فقط پست‌های جدید ذخیره می‌شوند.")
            self.logger.info(f"📊 تعداد پست‌های جدید: {len(self.posts)}")
            return self.posts

        self.logger.info(f"📊 تعداد پست‌های قبلی: {len(existing_posts)}")
        self.logger.info(f"📊 تعداد پست‌های جدید: {len(self.posts)}")

        # ─── مرحله ۴: ترکیب و حذف تکراری‌ها ──────────────────
        all_posts = existing_posts + self.posts
        seen_ids = set()
        unique_posts = []
        duplicate_count = 0

        for post in all_posts:
            post_id = post.get('id')
            if not post_id:
                self.logger.debug("⚠️ پست بدون 'id' یافت شد که نادیده گرفته شد.")
                continue

            if post_id not in seen_ids:
                seen_ids.add(post_id)
                unique_posts.append(post)
            else:
                duplicate_count += 1
                self.logger.debug(f"⏭️ پست تکراری حذف شد: id={post_id}")

        # ─── مرحله ۵: مرتب‌سازی نزولی ──────────────────────────
        try:
            unique_posts.sort(key=lambda x: int(x.get('id', 0)), reverse=True)
        except (ValueError, TypeError) as e:
            self.logger.warning(f"⚠️ خطا در مرتب‌سازی: {e}. تلاش با روش جایگزین...")
            # مرتب‌سازی به‌عنوان رشته (فال‌بک)
            unique_posts.sort(key=lambda x: str(x.get('id', '0')), reverse=True)

        self.logger.info(
            f"🔄 نتیجه ادغام: {len(existing_posts)} پست قبلی + "
            f"{len(self.posts)} پست جدید = {len(unique_posts)} پست کل "
            f"(پس از حذف {duplicate_count} تکراری)"
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
            else:
                self.logger.info(f"📊 تعداد پست‌ها بدون تغییر باقی ماند: {len(self.posts)}")

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

        تغییر مهم: در حالت append_mode، ابتدا ادغام انجام می‌شود و سپس همه‌ی فایل‌ها
        با داده‌های کامل تولید می‌شوند تا از دست رفتن پست‌های قبلی جلوگیری شود.
        """
        self.logger.info("🚀 شروع تولید فایل‌های خروجی...")
        self.logger.info(f"📊 تعداد پست‌های ورودی: {self._initial_post_count}")
        self.logger.info(f"📌 append_mode: {self.append_mode}")

        try:
            # ─── مرحله ۰: ادغام با داده‌های قبلی (اگر append_mode فعال باشد) ───
            if self.append_mode:
                merged_posts = self._merge_with_existing_posts()
                if len(merged_posts) != len(self.posts):
                    self.logger.info(
                        f"📊 تعداد پست‌ها پس از ادغام: {len(merged_posts)} "
                        f"(قبلاً {len(self.posts)})"
                    )
                    self.posts = merged_posts
                else:
                    self.logger.info(f"📊 تعداد پست‌ها بدون تغییر باقی ماند: {len(self.posts)}")
            else:
                self.logger.info("ℹ️ append_mode غیرفعال است. بدون ادغام ادامه می‌یابد.")

            # ─── مرحله ۱: تولید JSON (با داده‌های کامل) ───
            self.generate_json()

            # ─── مرحله ۲: تولید CSV ───
            self.generate_csv()

            # ─── مرحله ۳: تولید HTML ───
            # از آنجا که قبلاً ادغام انجام شده، دیگر نیازی به ادغام مجدد در generate_html نیست.
            # بنابراین append_mode را موقتاً غیرفعال می‌کنیم تا دوباره ادغام نکند.
            original_append_mode = self.append_mode
            if original_append_mode:
                self.append_mode = False  # جلوگیری از ادغام مجدد
            self.generate_html()
            self.append_mode = original_append_mode  # بازگردانی

            # ─── مرحله ۴: تولید ZIP ───
            self.create_zip()

            self.logger.info("✅ تمام فایل‌های خروجی با موفقیت تولید شدند.")

            # لاگ نهایی تعداد پست‌ها
            final_count = len(self.posts)
            if original_append_mode and final_count != self._initial_post_count:
                self.logger.info(
                    f"📊 خلاصه نهایی: {self._initial_post_count} پست ورودی → "
                    f"{final_count} پست خروجی (افزایش {final_count - self._initial_post_count} پست از ادغام)"
                )
            else:
                self.logger.info(f"📊 تعداد نهایی پست‌ها: {final_count}")

        except Exception as e:
            self.logger.error(f"❌ خطا در تولید خروجی: {e}")
            raise
