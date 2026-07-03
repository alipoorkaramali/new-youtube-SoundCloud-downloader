#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import asyncio
import argparse
import logging
from pathlib import Path

# ⚡️ این سه خط مشکل import را حل می‌کند
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_loader import load_config
from scraper import TelegramChannelScraper

# import debug_scraper فقط در صورت نیاز (برای جلوگیری از خطای import در صورت نبود فایل)
try:
    from debug_scraper import DebugTelegramChannelScraper
except ImportError:
    DebugTelegramChannelScraper = None


def setup_early_logging():
    """راه‌اندازی لاگ‌گیری اولیه تا پیش از تنظیم کامل"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()]
    )


async def main():
    parser = argparse.ArgumentParser(
        description="Telegram Channel Scraper - نسخهٔ مستقل (بدون Apify)"
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="مسیر فایل تنظیمات (نسبی به محل اجرا یا مطلق)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="فعال‌سازی حالت دیباگ (override تنظیمات config)"
    )
    parser.add_argument(
        "--direction",
        choices=["up", "down"],
        help="جهت اسکرول: up (قدیمی‌تر) یا down (جدیدتر) – override تنظیمات config"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="تعداد پست‌ها – override تنظیمات config"
    )
    parser.add_argument(
        "--start-link",
        help="لینک شروع – override تنظیمات config"
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    if not config_path.exists():
        print(f"❌ فایل تنظیمات یافت نشد: {config_path}")
        sys.exit(1)

    try:
        config = load_config(str(config_path))
    except Exception as e:
        print(f"❌ خطا در بارگذاری تنظیمات: {e}")
        sys.exit(1)

    # ─── اعمال override از خط فرمان ────────────────────
    if args.debug:
        config.debug_mode = True
        print("🐞 حالت دیباگ از خط فرمان فعال شد.")
    
    if args.direction:
        config.scroll_direction = args.direction
        print(f"🧭 جهت اسکرول از خط فرمان: {args.direction}")
    
    if args.limit:
        config.limit = args.limit
        print(f"📊 تعداد پست‌ها از خط فرمان: {args.limit}")
    
    if args.start_link:
        config.start_link = args.start_link
        print(f"🔗 لینک شروع از خط فرمان: {args.start_link}")

    # ─── انتخاب اسکرپر مناسب ────────────────────────────
    logger = logging.getLogger("Main")
    
    if config.debug_mode and DebugTelegramChannelScraper is not None:
        logger.info("🐞 حالت دیباگ فعال است – استفاده از DebugTelegramChannelScraper")
        scraper = DebugTelegramChannelScraper(config, debug_screenshots=True)
    elif config.debug_mode and DebugTelegramChannelScraper is None:
        logger.warning("⚠️ فایل debug_scraper.py یافت نشد. استفاده از اسکرپر معمولی.")
        scraper = TelegramChannelScraper(config)
    else:
        scraper = TelegramChannelScraper(config)

    # ─── اجرا با تایم‌اوت ──────────────────────────────
    timeout = getattr(config, 'timeout_seconds', 2100)
    try:
        await asyncio.wait_for(scraper.run(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(f"⏰ اسکریپت پس از {timeout} ثانیه متوقف شد (تایم‌اوت).")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"❌ خطای مرگبار: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    setup_early_logging()
    asyncio.run(main())
