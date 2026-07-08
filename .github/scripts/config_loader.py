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
    resume: bool = True           # ادامه از آخرین نقطه در اجرای مجدد
    start_link: str = ''          # لینک پست برای شروع دستی
    save_screenshots: bool = True # اگر False باشد، اسکرین‌شات‌ها ذخیره نمی‌شوند
    scroll_direction: str = 'up'   # جهت اسکرول (up یا down)
    timeout_seconds: int = 0           # 0 = نامحدود (از مقدار پیش‌فرض در کد استفاده می‌شود)
    auto_extend_timeout: bool = True   # تمدید خودکار زمان در صورت ادامهٔ موفق اسکرپینگ

def load_config(path: str = "config.yaml") -> Config:
    """بارگذاری تنظیمات از فایل YAML"""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"❌ فایل تنظیمات {path} یافت نشد!")

    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    # اعتبارسنجی
    # اگر start_link وجود نداشته باشد، channel الزامی است
    if not data.get('channel') and not data.get('start_link'):
        raise ValueError("❌ یا نام کانال (channel) یا لینک شروع (start_link) باید در config.yaml تنظیم شود.")
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
        start_link=data.get('start_link', ''),
        save_screenshots=data.get('save_screenshots', True),
        scroll_direction=data.get('scroll_direction', 'up'),
        timeout_seconds=data.get('timeout_seconds', 0),
        auto_extend_timeout=data.get('auto_extend_timeout', True)
    )
