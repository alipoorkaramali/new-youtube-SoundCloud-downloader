#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Telegram catalog index + create/update a single GitHub Issue.

Similar to YouTube/SoundCloud catalog in news-watcher:
  Title: 📱 Telegram Catalog – Download
  Comment: /download <number>

Index: State/telegram_catalog_index.json
  { "1": {"channel": "bbcpersian", "id": "123", "url": "https://t.me/...", "text": "...", "date": "..."}, ... }
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

ISSUE_TITLE = "📱 Telegram Catalog – Download"
INDEX_PATH = Path("State/telegram_catalog_index.json")
DOWNLOADS_ROOT = Path("Download/telegram_downloads")
KEEP_PER_CHANNEL = 50


def iran_now_str() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).strftime(
        "%Y-%m-%d %H:%M"
    )


def load_channel_posts(channel: str) -> List[Dict[str, Any]]:
    base = DOWNLOADS_ROOT / channel
    jp = base / f"{channel}_posts.json"
    posts: List[Dict[str, Any]] = []
    if jp.exists():
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for p in data:
                    if isinstance(p, dict) and (p.get("id") or p.get("message_id")):
                        posts.append(p)
        except Exception as e:
            print(f"⚠️ read {jp}: {e}")
    # newest first
    def sort_key(p: dict) -> int:
        try:
            return int(p.get("id") or p.get("message_id") or 0)
        except ValueError:
            return 0

    posts.sort(key=sort_key, reverse=True)
    return posts[:KEEP_PER_CHANNEL]


def channel_list() -> List[str]:
    state_path = Path("State/telegram_news_state.json")
    channels: List[str] = []
    if state_path.exists():
        try:
            d = json.loads(state_path.read_text(encoding="utf-8"))
            channels = list(d.get("channel_list") or [])
        except Exception:
            channels = []
    if not channels and DOWNLOADS_ROOT.exists():
        channels = sorted(
            p.name for p in DOWNLOADS_ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")
        )
    return channels


def build_index() -> Tuple[Dict[str, Dict[str, Any]], List[Tuple[str, List[Dict]]]]:
    """Return index dict and ordered (channel, posts) for body."""
    index: Dict[str, Dict[str, Any]] = {}
    groups: List[Tuple[str, List[Dict]]] = []
    n = 0
    for ch in channel_list():
        posts = load_channel_posts(ch)
        if not posts:
            continue
        groups.append((ch, posts))
        for p in posts:
            n += 1
            pid = str(p.get("id") or p.get("message_id") or "")
            url = (p.get("url") or "").strip() or f"https://t.me/{ch}/{pid}"
            text = (p.get("text") or "").replace("\r", " ").replace("\n", " ")
            text = re.sub(r"\s+", " ", text).strip()
            date = str(p.get("date") or p.get("published") or "")[:19]
            index[str(n)] = {
                "channel": ch,
                "id": pid,
                "url": url,
                "text": text[:500],
                "date": date,
            }
    return index, groups


def build_issue_body(index: Dict[str, Dict[str, Any]], groups: List[Tuple[str, List[Dict]]]) -> str:
    lines: List[str] = []
    lines.append("# 📱 Telegram Catalog – Download")
    lines.append("")
    lines.append(f"**Generated (Iran):** {iran_now_str()}")
    lines.append(f"**Total items:** {len(index)}")
    lines.append("")
    lines.append("### 📥 How to download")
    lines.append("")
    lines.append("Comment on this issue:")
    lines.append("")
    lines.append("```")
    lines.append("/download <number>")
    lines.append("```")
    lines.append("")
    lines.append("Example: `/download 3`")
    lines.append("")
    lines.append("Media is fetched with the Telegram scraper (Playwright) and saved under")
    lines.append("`Download/telegram_downloads/<channel>/`.")
    lines.append("")
    lines.append("---")
    lines.append("")

    n = 0
    for ch, posts in groups:
        lines.append(f"### 📢 @{ch}")
        lines.append("")
        for p in posts:
            n += 1
            pid = str(p.get("id") or p.get("message_id") or "")
            text = (p.get("text") or "").replace("\r", " ").replace("\n", " ")
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 160:
                text = text[:157] + "…"
            date = str(p.get("date") or "")[:16]
            lines.append(f"{n}. {text or '(no text)'}")
            meta = f"   id=`{pid}`"
            if date:
                meta += f" · {date}"
            lines.append(meta)
            lines.append("")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Updated after each Telegram scrape run.*")
    return "\n".join(lines)


def api_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def find_issue(repo: str, token: str) -> Any:
    headers = api_headers(token)
    url = f"https://api.github.com/repos/{repo}/issues"
    try:
        r = requests.get(url, headers=headers, params={"state": "open", "per_page": 100}, timeout=60)
        if r.status_code == 200:
            for it in r.json():
                if it.get("pull_request"):
                    continue
                if (it.get("title") or "") == ISSUE_TITLE:
                    return it
    except Exception as e:
        print(f"list issues error: {e}")
    return None


def create_or_update_issue(repo: str, token: str, body: str) -> str:
    headers = api_headers(token)
    existing = find_issue(repo, token)
    if existing:
        num = existing["number"]
        r = requests.patch(
            f"https://api.github.com/repos/{repo}/issues/{num}",
            headers=headers,
            json={"title": ISSUE_TITLE, "body": body, "state": "open"},
            timeout=60,
        )
        if r.status_code == 200:
            print(f"✅ Issue updated #{num}")
            return r.json().get("html_url", "")
        raise RuntimeError(f"update #{num} {r.status_code} {r.text[:300]}")
    r = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers=headers,
        json={"title": ISSUE_TITLE, "body": body},
        timeout=60,
    )
    if r.status_code == 201:
        print(f"✅ Issue created #{r.json().get('number')}")
        return r.json().get("html_url", "")
    raise RuntimeError(f"create {r.status_code} {r.text[:300]}")


def main() -> None:
    repo = os.environ.get("GITHUB_REPOSITORY") or ""
    token = (
        os.environ.get("GH_PAT")
        or os.environ.get("GH_PAT1")
        or os.environ.get("GITHUB_TOKEN")
        or ""
    )
    if not repo:
        raise SystemExit("GITHUB_REPOSITORY not set")
    if not token:
        raise SystemExit("No token (GH_PAT / GITHUB_TOKEN)")

    index, groups = build_index()
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"📇 index entries: {len(index)} → {INDEX_PATH}")

    body = build_issue_body(index, groups)
    url = create_or_update_issue(repo, token, body)
    print(f"🔗 {url}")


if __name__ == "__main__":
    main()
