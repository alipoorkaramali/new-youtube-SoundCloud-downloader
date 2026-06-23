#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import yaml
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Config:
    apify_token: str
    channel: str
    limit: int
    max_media_mb: int
    session_file: str
    output_dir: str
    rate_limit: float

def _expand_env_vars(value: str) -> str:
    """جایگزینی ${VAR} با مقادیر متغیرهای محیطی"""
    pattern = re.compile(r'\$\{(\w+)\}')
    return pattern.sub(lambda m: os.environ.get(m.group(1), ''), value)

def load_config(path: str = "config.yaml") -> Config:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"❌ فایل تنظیمات {path} یافت نشد!")

    with open(config_path, 'r', encoding='utf-8') as f:
        raw_data = yaml.safe_load(f)

    data = {}
    for key, value in raw_data.items():
        if isinstance(value, str):
            data[key] = _expand_env_vars(value)
        else:
            data[key] = value

    if not data.get('apify_token') or data['apify_token'] == "${APIFY_TOKEN}":
        raise ValueError("❌ توکن Apify تنظیم نشده است.")
    if not data.get('channel'):
        raise ValueError("❌ نام کانال تنظیم نشده است.")

    return Config(**data)