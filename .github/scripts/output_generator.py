#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ماژول تولید خروجی‌های چندگانه برای اسکرپر تلگرام
---------------------------------------------
JSON / CSV / HTML / ZIP

- همیشه با آرشیو قبلی ادغام می‌شود
- مرتب‌سازی از جدید به قدیم (id نزولی)
- پنجره ثابت: فقط N پست جدیدتر نگه داشته می‌شود (پیش‌فرض ۵۰)
  → پست جدید اضافه، به همان تعداد قدیمی‌تر حذف
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

# تعداد ثابت پست در خروجی آرشیو (پنجره لغزان)
DEFAULT_KEEP_LATEST = 50


class OutputGenerator:
    """تولیدکننده خروجی‌های چندفرمتی برای آرشیو تلگرام."""

    def __init__(
        self,
        base_dir: Path,
        channel: str,
        posts: list,
        media_map: dict,
        debug_mode: bool = False,
        append_mode: bool = False,
        keep_latest: int = DEFAULT_KEEP_LATEST,
    ):
        self.base_dir = Path(base_dir)
        self.channel = channel
        self.posts = list(posts or [])
        self.media_map = media_map or {}
        self.debug_mode = debug_mode
        # همیشه ادغام با قبلی انجام می‌شود تا آرشیو پاک نشود
        self.append_mode = True
        self.keep_latest = max(1, int(keep_latest or DEFAULT_KEEP_LATEST))
        self.logger = logging.getLogger("TelegramScraper")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._safe_name = self._sanitize_filename(self.channel)
        self._initial_post_count = len(self.posts)

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        name = (name or "channel").strip().lstrip("@")
        return re.sub(r"[^\w\-]", "_", name) or "channel"

    def _validate_post_structure(self, post: Dict) -> bool:
        return isinstance(post, dict) and bool(post.get("id"))

    def _extract_posts_from_html(self, html_path: Path) -> List[Dict]:
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f, "html.parser")
            existing_posts = []
            for div in soup.select("[data-msg-id], .post"):
                msg_id = div.get("data-msg-id")
                if not msg_id:
                    # fallback: #number in .post-number
                    num = div.select_one(".post-number")
                    continue
                text_el = div.select_one(".post-text, .text, p")
                text = text_el.get_text("\n", strip=True) if text_el else ""
                post_data = {
                    "id": str(msg_id).strip(),
                    "text": text,
                    "url": f"https://t.me/{self._safe_name}/{msg_id}",
                }
                if self._validate_post_structure(post_data):
                    existing_posts.append(post_data)
            return existing_posts
        except Exception as e:
            self.logger.warning(f"⚠️ خواندن HTML قبلی ناموفق: {e}")
            return []

    def _merge_with_existing_posts(self) -> list:
        """ادغام پست‌های جدید با آرشیو قبلی + حذف تکراری."""
        json_path = self.base_dir / f"{self._safe_name}_posts.json"
        html_path = self.base_dir / f"{self._safe_name}_posts.html"
        existing_posts: List[Dict] = []

        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for post in data:
                        if self._validate_post_structure(post):
                            existing_posts.append(post)
                self.logger.info(
                    f"📄 {len(existing_posts)} پست از JSON قبلی: {json_path.name}"
                )
            except Exception as e:
                self.logger.warning(f"⚠️ خواندن JSON قبلی ناموفق: {e}")
                existing_posts = []

        if not existing_posts and html_path.exists():
            html_posts = self._extract_posts_from_html(html_path)
            if html_posts:
                existing_posts = html_posts
                self.logger.info(f"📄 {len(existing_posts)} پست از HTML قبلی.")

        if not existing_posts:
            self.logger.info("ℹ️ آرشیو قبلی خالی — فقط پست‌های این اجرا")
            return list(self.posts)

        all_posts = existing_posts + list(self.posts)
        seen_ids = set()
        unique_posts = []
        duplicate_count = 0
        for post in all_posts:
            post_id = str(post.get("id") or "")
            if not post_id:
                continue
            if post_id not in seen_ids:
                seen_ids.add(post_id)
                unique_posts.append(post)
            else:
                duplicate_count += 1

        self.logger.info(
            f"🔄 ادغام: {len(existing_posts)} قبلی + {len(self.posts)} جدید = "
            f"{len(unique_posts)} یکتا (حذف {duplicate_count} تکراری)"
        )
        return unique_posts

    def _sort_posts_newest_first(self) -> None:
        if not self.posts:
            return
        try:
            self.posts.sort(key=lambda x: int(x.get("id", 0) or 0), reverse=True)
        except (ValueError, TypeError):
            self.posts.sort(key=lambda x: str(x.get("id", "0")), reverse=True)

    def _apply_rolling_window(self) -> None:
        """فقط keep_latest پست جدیدتر را نگه دار (قدیمی‌ترها حذف)."""
        self._sort_posts_newest_first()
        before = len(self.posts)
        if before > self.keep_latest:
            dropped = before - self.keep_latest
            self.posts = self.posts[: self.keep_latest]
            self.logger.info(
                f"🪟 پنجره {self.keep_latest}تایی: {before} → {len(self.posts)} "
                f"(حذف {dropped} پست قدیمی‌تر)"
            )
        else:
            self.logger.info(
                f"🪟 پنجره {self.keep_latest}تایی: {before} پست (کمتر از سقف)"
            )
        if self.posts:
            self.logger.info(
                f"🔃 ترتیب: جدید→قدیم (اول={self.posts[0].get('id')}, "
                f"آخر={self.posts[-1].get('id')})"
            )

    def generate_json(self) -> None:
        json_path = self.base_dir / f"{self._safe_name}_posts.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.posts, f, indent=2, ensure_ascii=False)
        self.logger.info(f"📄 JSON: {json_path.name} ({len(self.posts)} پست)")

    def generate_csv(self) -> None:
        csv_path = self.base_dir / f"{self._safe_name}_posts.csv"
        if not self.posts:
            return
        fieldnames = ["id", "date", "text", "url", "views", "forwards", "replies"]
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for post in self.posts:
                writer.writerow({k: post.get(k, "") for k in fieldnames})
        self.logger.info(f"📄 CSV: {csv_path.name}")

    def generate_html(self) -> None:
        self._sort_posts_newest_first()
        html_path = self.base_dir / f"{self._safe_name}_posts.html"
        current_iran = (
            datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
        ).strftime("%Y/%m/%d - %H:%M")
        html_content = self._build_html_content(current_iran)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        self.logger.info(f"🌐 HTML: {html_path.name} ({len(self.posts)} پست)")

    def _build_html_content(self, current_iran: str) -> str:
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
                env = Environment(
                    loader=FileSystemLoader(str(template_dir)),
                    autoescape=select_autoescape(["html", "xml"]),
                )

                def hashtagify(text: str) -> Markup:
                    return Markup(
                        re.sub(r"(#\w+)", r'<span class="hashtag">\1</span>', str(text))
                    )

                env.filters["hashtagify"] = hashtagify
                template = env.get_template("post_template.html")
                return template.render(
                    channel=self.channel,
                    posts=self.posts,
                    media_map=self.media_map,
                    current_time=current_iran,
                )
        raise FileNotFoundError("قالب post_template.html پیدا نشد")

    def create_zip(self) -> None:
        zip_path = self.base_dir / f"{self._safe_name}_archive.zip"
        files = [
            self.base_dir / f"{self._safe_name}_posts.json",
            self.base_dir / f"{self._safe_name}_posts.csv",
            self.base_dir / f"{self._safe_name}_posts.html",
        ]
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp in files:
                    if fp.exists():
                        zf.write(fp, fp.name)
            self.logger.info(f"📦 ZIP: {zip_path.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ ساخت ZIP ناموفق: {e}")

    def run_all(self) -> None:
        """ادغام با قبلی → مرتب‌سازی → پنجره ۵۰تایی → نوشتن خروجی."""
        self.logger.info("🚀 شروع تولید فایل‌های خروجی...")
        self.logger.info(f"📊 پست‌های این اجرا: {self._initial_post_count}")
        self.logger.info(f"🪟 keep_latest={self.keep_latest}")

        try:
            # همیشه با آرشیو قبلی ادغام کن (حتی اگر append_mode ورودی False بود)
            self.posts = self._merge_with_existing_posts()

            # جدیدترها بالا، فقط N تای اول
            self._apply_rolling_window()

            self.generate_json()
            self.generate_csv()
            self.generate_html()
            self.create_zip()

            self.logger.info("✅ خروجی‌ها آماده شد.")
            self.logger.info(f"📊 تعداد نهایی در آرشیو: {len(self.posts)}")
        except Exception as e:
            self.logger.error(f"❌ خطا در تولید خروجی: {e}")
            raise
