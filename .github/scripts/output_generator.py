#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import csv
import zipfile
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

logger = logging.getLogger("TelegramScraper")

class OutputGenerator:
    def __init__(self, base_dir: Path, channel: str, items: List[Dict], media_map: Dict[str, List[str]], template_dir: str = "templates"):
        self.base_dir = base_dir
        self.channel = channel
        self.items = items
        self.media_map = media_map
        self.template_dir = Path(template_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _format_iran_time(iso_str: str) -> str:
        if not iso_str: return "نامشخص"
        try:
            dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
            return (dt + timedelta(hours=3, minutes=30)).strftime('%Y/%m/%d - %H:%M')
        except:
            return iso_str

    def generate_json(self):
        path = self.base_dir / "posts.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.items, f, indent=2, ensure_ascii=False)
        logger.info(f"📄 JSON: {path}")

    def generate_csv(self):
        if not self.items: return
        path = self.base_dir / "posts.csv"
        important = ['id', 'date', 'text', 'url', 'views', 'forwards', 'replies']
        all_keys = set().union(*(item.keys() for item in self.items))
        fieldnames = [f for f in important if f in all_keys]
        for f in ['mentions', 'hashtags', 'outlinks']:
            if f in all_keys: fieldnames.append(f)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for item in self.items:
                row = {k: ', '.join(v) if isinstance(item.get(k), list) else item.get(k, '') for k in fieldnames}
                writer.writerow(row)
        logger.info(f"📊 CSV: {path}")

    def generate_html(self):
        env = Environment(loader=FileSystemLoader(str(self.template_dir)))
        try:
            template = env.get_template("post_template.html")
        except TemplateNotFound:
            logger.error("❌ فایل post_template.html پیدا نشد.")
            return
        for post in self.items:
            if 'date' in post: post['formatted_date'] = self._format_iran_time(post['date'])
        now_iran = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).strftime('%Y/%m/%d - %H:%M')
        html = template.render(channel=self.channel, posts=self.items, media_map=self.media_map, current_time=now_iran)
        path = self.base_dir / "posts.html"
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"🌐 HTML: {path}")

    def create_zip(self, exclude_larger_than_mb: int = 500):
        zip_path = self.base_dir / f"{self.channel}_archive.zip"
        max_bytes = exclude_larger_than_mb * 1024 * 1024
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in self.base_dir.rglob('*'):
                if file_path.is_file() and file_path != zip_path:
                    if file_path.stat().st_size <= max_bytes:
                        zf.write(file_path, file_path.relative_to(self.base_dir))
                    else:
                        logger.info(f"⏩ حذف از ZIP (حجم): {file_path.name}")
        logger.info(f"📦 ZIP: {zip_path}")