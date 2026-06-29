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

    scraper = TelegramChannelScraper(config)
    try:
        await scraper.run()
    except Exception as e:
        logging.getLogger("Main").critical(f"❌ خطای مرگبار: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    setup_early_logging()
    asyncio.run(main())
