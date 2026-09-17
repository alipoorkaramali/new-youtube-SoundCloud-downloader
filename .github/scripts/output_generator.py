#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ماژول تولید خروجی‌های چندگانه برای اسکرپر تلگرام
---------------------------------------------
این ماژول وظیفه دارد داده‌های استخراج‌شده از کانال تلگرام را
به فرمت‌های مختلف (JSON, CSV, HTML, ZIP) تبدیل و ذخیره کند.

قابلیت‌های اصلی:
    ۱. تولید فایل JSON با تمام پست‌ها
    ۲. تولید فایل CSV برای تحلیل داده‌ها
    ۳. تولید فایل HTML زیبا با قالب Jinja2
    ۴. فشرده‌سازی خروجی‌ها در فایل ZIP
    ۵. پشتیبانی از حالت append (ادغام با داده‌های قبلی)
    ۶. مرتب‌سازی اجباری پست‌ها از جدید به قدیم (id نزولی)
"""

from __future__ import annotations

import csv
import json
import logging
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup


class OutputGenerator:
    """تولیدکننده خروجی‌های چندفرمتی برای آرشیو تلگرام."""

    def __init__(
        self,
        posts: list,
        channel: str,
        media_map: Optional[Dict] = None,
        base_dir: Optional[Path] = None,
        append_mode: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        self.posts = posts or []
        self.channel = channel
        self.media_map = media_map or {}
        self.append_mode = append_mode
        self.logger = logger or logging.getLogger(__name__)
        self.base_dir = Path(base_dir) if base_dir else Path('Download/telegram_downloads') / self._safe_channel_name()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._safe_name = self._safe_channel_name()
        self._initial_post_count = len(self.posts)

    def _safe_channel_name(self) -> str:
        name = (self.channel or 'channel').strip().lstrip('@')
        return re.sub(r'[^\w\-]', '_', name) or 'channel'

    def _validate_post_structure(self, post: Dict) -> bool:
        if not isinstance(post, dict):
            return False
        if 'id' not in post:
            return False
        if not post['id']:
            return False
        return True

    def _extract_posts_from_html(self, html_path: Path) -> List[Dict]:
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
            existing_posts = []
            for div in soup.select('[data-msg-id], .post'):
                msg_id = div.get('data-msg-id')
                if not msg_id:
                    continue
                text_el = div.select_one('.post-text, .text, p')
                text = text_el.get_text('\n', strip=True) if text_el else ''
                post_data = {
                    'id': str(msg_id).strip(),
                    'text': text,
                    'url': f'https://t.me/{self._safe_name}/{msg_id}',
                }
                if self._validate_post_structure(post_data):
                    existing_posts.append(post_data)
            return existing_posts
        except Exception as e:
            self.logger.warning(f'⚠️ خواندن HTML قبلی ناموفق: {e}')
            return []

    def _merge_with_existing_posts(self) -> list:
        json_path = self.base_dir / f'{self._safe_name}_posts.json'
        html_path = self.base_dir / f'{self._safe_name}_posts.html'
        existing_posts: List[Dict] = []

        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for post in data:
                        if self._validate_post_structure(post):
                            existing_posts.append(post)
                self.logger.info(
                    f'📄 {len(existing_posts)} پست معتبر از فایل JSON قبلی بارگذاری شد: {json_path.name}'
                )
            except Exception as e:
                self.logger.warning(f'⚠️ خواندن JSON قبلی ناموفق: {e}')
                existing_posts = []

        if not existing_posts and html_path.exists():
            self.logger.info(f'📄 تلاش برای خواندن پست‌ها از فایل HTML: {html_path.name}')
            html_posts = self._extract_posts_from_html(html_path)
            if html_posts:
                existing_posts = html_posts
                self.logger.info(f'📄 {len(existing_posts)} پست از فایل HTML قبلی استخراج شد.')

        if not existing_posts:
            self.logger.info('ℹ️ هیچ پست قبلی یافت نشد. فقط پست‌های جدید ذخیره می‌شوند.')
            self.logger.info(f'📊 تعداد پست‌های جدید: {len(self.posts)}')
            return list(self.posts)

        self.logger.info(f'📊 تعداد پست‌های قبلی: {len(existing_posts)}')
        self.logger.info(f'📊 تعداد پست‌های جدید: {len(self.posts)}')

        all_posts = existing_posts + list(self.posts)
        seen_ids = set()
        unique_posts = []
        duplicate_count = 0
        for post in all_posts:
            post_id = post.get('id')
            if not post_id:
                continue
            if post_id not in seen_ids:
                seen_ids.add(post_id)
                unique_posts.append(post)
            else:
                duplicate_count += 1

        try:
            unique_posts.sort(key=lambda x: int(x.get('id', 0) or 0), reverse=True)
        except (ValueError, TypeError):
            unique_posts.sort(key=lambda x: str(x.get('id', '0')), reverse=True)

        self.logger.info(
            f'🔄 نتیجه ادغام: {len(existing_posts)} پست قبلی + '
            f'{len(self.posts)} پست جدید = {len(unique_posts)} پست کل '
            f'(پس از حذف {duplicate_count} تکراری)'
        )
        return unique_posts

    def _sort_posts_newest_first(self) -> None:
        """مرتب‌سازی اجباری پست‌ها از جدید به قدیم (id نزولی) برای HTML/JSON."""
        if not self.posts:
            return
        try:
            self.posts.sort(key=lambda x: int(x.get('id', 0) or 0), reverse=True)
        except (ValueError, TypeError):
            self.posts.sort(key=lambda x: str(x.get('id', '0')), reverse=True)
        self.logger.info(
            f"🔃 ترتیب پست‌ها: از جدید به قدیم "
            f"(اول={self.posts[0].get('id')}, آخر={self.posts[-1].get('id')})"
        )

    def generate_json(self) -> None:
        json_path = self.base_dir / f'{self._safe_name}_posts.json'
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(self.posts, f, indent=2, ensure_ascii=False)
            self.logger.info(f'📄 JSON: {json_path.name} ({len(self.posts)} پست)')
        except Exception as e:
            self.logger.error(f'❌ خطا در تولید JSON: {e}')
            raise

    def generate_csv(self) -> None:
        csv_path = self.base_dir / f'{self._safe_name}_posts.csv'
        if not self.posts:
            self.logger.warning('⚠️ هیچ پستی برای CSV وجود ندارد.')
            return
        fieldnames = ['id', 'date', 'text', 'url', 'views', 'forwards', 'replies']
        try:
            with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                for post in self.posts:
                    row = {k: post.get(k, '') for k in fieldnames}
                    writer.writerow(row)
            self.logger.info(f'📄 CSV: {csv_path.name}')
        except Exception as e:
            self.logger.error(f'❌ خطا در تولید CSV: {e}')
            raise

    def generate_html(self) -> None:
        if self.append_mode:
            self.logger.info('🔄 append_mode فعال است. تلاش برای ادغام با داده‌های قبلی...')
            merged_posts = self._merge_with_existing_posts()
            self.posts = merged_posts
        else:
            self.logger.info('ℹ️ append_mode غیرفعال است. فایل HTML از نو ساخته می‌شود.')

        self._sort_posts_newest_first()

        html_path = self.base_dir / f'{self._safe_name}_posts.html'
        current_iran = (
            datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
        ).strftime('%Y/%m/%d - %H:%M')

        try:
            html_content = self._build_html_content(current_iran)
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f'🌐 HTML: {html_path.name} ({len(self.posts)} پست)')
        except Exception as e:
            self.logger.error(f'❌ خطا در تولید HTML: {e}')
            raise

    def _build_html_content(self, current_iran: str) -> str:
        script_dir = Path(__file__).resolve().parent
        template_dirs = [
            script_dir / 'templates',
            script_dir.parent / 'templates',
            Path.cwd() / 'templates',
            Path.cwd() / '.github' / 'templates',
        ]

        for template_dir in template_dirs:
            template_file = template_dir / 'post_template.html'
            if template_file.exists():
                env = Environment(
                    loader=FileSystemLoader(str(template_dir)),
                    autoescape=select_autoescape(['html', 'xml']),
                )

                def hashtagify(text: str) -> Markup:
                    return Markup(
                        re.sub(r'(#\w+)', r'<span class="hashtag">\1</span>', str(text))
                    )

                env.filters['hashtagify'] = hashtagify
                template = env.get_template('post_template.html')
                return template.render(
                    channel=self.channel,
                    posts=self.posts,
                    media_map=self.media_map,
                    current_time=current_iran,
                )

        raise FileNotFoundError('قالب post_template.html پیدا نشد')

    def create_zip(self) -> None:
        zip_path = self.base_dir / f'{self._safe_name}_archive.zip'
        files = [
            self.base_dir / f'{self._safe_name}_posts.json',
            self.base_dir / f'{self._safe_name}_posts.csv',
            self.base_dir / f'{self._safe_name}_posts.html',
        ]
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for fp in files:
                    if fp.exists():
                        zf.write(fp, fp.name)
            self.logger.info(f'📦 ZIP: {zip_path.name}')
        except Exception as e:
            self.logger.warning(f'⚠️ ساخت ZIP ناموفق: {e}')

    def generate(self) -> None:
        """تولید همه خروجی‌ها با ترتیب جدید→قدیم."""
        self.logger.info('🚀 شروع تولید فایل‌های خروجی...')
        self.logger.info(f'📊 تعداد پست‌های ورودی: {self._initial_post_count}')
        self.logger.info(f'📌 append_mode: {self.append_mode}')

        try:
            if self.append_mode:
                merged_posts = self._merge_with_existing_posts()
                self.posts = merged_posts
            else:
                self.logger.info('ℹ️ append_mode غیرفعال است. بدون ادغام ادامه می‌یابد.')

            self._sort_posts_newest_first()

            self.generate_json()
            self.generate_csv()

            original_append_mode = self.append_mode
            if original_append_mode:
                self.append_mode = False
            self.generate_html()
            self.append_mode = original_append_mode

            self.create_zip()

            self.logger.info('✅ تمام فایل‌های خروجی با موفقیت تولید شدند.')
            self.logger.info(f'📊 تعداد نهایی پست‌ها: {len(self.posts)}')
        except Exception as e:
            self.logger.error(f'❌ خطا در تولید خروجی: {e}')
            raise
