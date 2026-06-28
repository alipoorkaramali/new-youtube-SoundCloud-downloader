#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Config:
    """تنظیمات پروژه — نسخهٔ مستقل از Apify"""
    channel: str                  # نام کانال بدون @
    limit: int                    # تعداد پست‌های مورد نظر
    max_media_mb: int             # حداکثر حجم هر فایل رسانه (مگابایت)
    output_dir: str               # پوشهٔ اصلی خروجی
    profile_dir: str              # پوشهٔ پروفایل مرورگر
    delay_between_posts: float    # فاصلهٔ زمانی (ثانیه) بین بارگذاری پست‌ها
    channel_name: str = ''        # نام نمایشی کانال (اختیاری)
    resume: bool = True           # ادامه خودکار از آخرین نقطه
    start_from: str = ''          # شناسهٔ پست برای شروع دستی (message_id)
    target_url: str = ''          # (جدید) لینک کامل پست برای شروع
    max_scroll_attempts: int = 30 # (جدید) حداکثر تلاش اسکرول

def load_config(path: str = "config.yaml") -> Config:
    """بارگذاری تنظیمات از فایل YAML"""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"❌ فایل تنظیمات {path} یافت نشد!")

    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    # اعتبارسنجی
    if not data.get('channel'):
        raise ValueError("❌ نام کانال در config.yaml تنظیم نشده است.")
    if data.get('limit', 0) <= 0:
        raise ValueError("❌ limit باید بزرگ‌تر از صفر باشد.")
    if data.get('max_media_mb', 0) <= 0:
        raise ValueError("❌ max_media_mb باید بزرگ‌تر از صفر باشد.")
    if not data.get('profile_dir'):
        raise ValueError("❌ پوشهٔ پروفایل (profile_dir) مشخص نشده است.")

    return Config(
        channel=data['channel'].lstrip('@'),
        limit=data['limit'],
        max_media_mb=data['max_media_mb'],
        output_dir=data.get('output_dir', 'Download'),
        profile_dir=data['profile_dir'],
        delay_between_posts=data.get('delay_between_posts', 1.5),
        channel_name=data.get('channel_name', ''),
        resume=data.get('resume', True),
        start_from=data.get('start_from', ''),
        target_url=data.get('target_url', ''),            # جدید
        max_scroll_attempts=data.get('max_scroll_attempts', 30)  # جدید
    )