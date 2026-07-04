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

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
    print("⚠️ BeautifulSoup نصب نیست. برای حالت append_mode لطفاً نصب کنید: pip install beautifulsoup4")


class OutputGenerator:
    # ... (بقیه متدها مانند قبل) ...

    def _merge_with_existing_posts(self) -> list:
        """
        اگر append_mode فعال باشد، ابتدا فایل JSON قبلی را می‌خواند.
        اگر JSON وجود نداشت، از HTML به‌عنوان پشتیبان استفاده می‌کند.
        سپس با self.posts ادغام کرده، تکراری‌ها را حذف و بر اساس msg_id (نزولی) مرتب می‌کند.
        """
        if not self.append_mode:
            return self.posts

        safe_name = self._sanitize_filename(self.channel)
        json_path = self.base_dir / f"{safe_name}_posts.json"
        html_path = self.base_dir / f"{safe_name}_posts.html"

        existing_posts = []

        # ۱. اول JSON را امتحان کن
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    existing_posts = json.load(f)
                self.logger.info(f"📄 {len(existing_posts)} پست از فایل JSON قبلی بارگذاری شد: {json_path}")
            except Exception as e:
                self.logger.warning(f"⚠️ خطا در خواندن JSON: {e}. تلاش برای خواندن HTML...")
                existing_posts = []

        # ۲. اگر JSON موجود نبود یا خطا داشت، از HTML استفاده کن
        if not existing_posts and html_path.exists():
            self.logger.info(f"📄 تلاش برای خواندن پست‌ها از فایل HTML: {html_path}")
            if BeautifulSoup is None:
                self.logger.warning("⚠️ BeautifulSoup نصب نیست، نمی‌توان HTML را خواند.")
            else:
                try:
                    with open(html_path, 'r', encoding='utf-8') as f:
                        soup = BeautifulSoup(f, 'html.parser')

                    for div in soup.find_all('div', class_='post'):
                        msg_id = div.get('data-msg-id')
                        if msg_id:
                            text_div = div.find('div', class_='text')
                            date_div = div.find('div', class_='date')
                            existing_posts.append({
                                'id': msg_id,
                                'text': text_div.get_text(strip=True) if text_div else '',
                                'date': date_div.get_text(strip=True) if date_div else ''
                            })
                    self.logger.info(f"📄 {len(existing_posts)} پست از فایل HTML قبلی استخراج شد.")
                except Exception as e:
                    self.logger.warning(f"⚠️ خطا در خواندن HTML: {e}")

        # اگر هیچ پستی پیدا نشد، فقط پست‌های جدید را برگردان
        if not existing_posts:
            self.logger.info("ℹ️ هیچ پست قبلی یافت نشد. فقط پست‌های جدید ذخیره می‌شوند.")
            return self.posts

        # ترکیب با پست‌های جدید
        all_posts = existing_posts + self.posts
        seen = set()
        unique_posts = []
        for post in all_posts:
            if post['id'] not in seen:
                seen.add(post['id'])
                unique_posts.append(post)

        # مرتب‌سازی نزولی بر اساس id (جدیدترین = بزرگترین عدد)
        unique_posts.sort(key=lambda x: int(x['id']), reverse=True)
        self.logger.info(f"🔄 append_mode: {len(existing_posts)} پست قبلی + {len(self.posts)} پست جدید = {len(unique_posts)} پست کل (پس از حذف تکراری‌ها)")
        return unique_posts

    # ... (بقیه متدها) ...
