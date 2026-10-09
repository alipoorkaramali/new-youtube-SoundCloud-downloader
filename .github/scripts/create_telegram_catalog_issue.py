#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-channel Telegram catalog Issues (≤50 posts each) + index + meta."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

ISSUE_PREFIX = "📱 Telegram Catalog – @"
HUB_TITLE = "📱 Telegram Catalog – Channels"
INDEX_PATH = Path("State/telegram_catalog_index.json")
META_PATH = Path("State/telegram_catalog_meta.json")
DOWNLOADS_ROOT = Path("Download/telegram_downloads")
KEEP_PER_CHANNEL = 50
BODY_MAX = 65000


def iran_now_str() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).strftime(
        "%Y-%m-%d %H:%M"
    )


def issue_title_for(channel: str) -> str:
    return f"{ISSUE_PREFIX}{channel}"


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
            p.name
            for p in DOWNLOADS_ROOT.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
    return channels


def build_index() -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], List[Tuple[str, List[Dict]]]]:
    """index[channel][str(n)] = post meta; n is 1..≤50 per channel."""
    index: Dict[str, Dict[str, Dict[str, Any]]] = {}
    groups: List[Tuple[str, List[Dict]]] = []
    for ch in channel_list():
        posts = load_channel_posts(ch)
        if not posts:
            continue
        groups.append((ch, posts))
        ch_idx: Dict[str, Dict[str, Any]] = {}
        for i, p in enumerate(posts, start=1):
            pid = str(p.get("id") or p.get("message_id") or "")
            url = (p.get("url") or "").strip() or f"https://t.me/{ch}/{pid}"
            text = (p.get("text") or p.get("caption") or "").strip()
            date = str(p.get("date") or p.get("published") or "")[:19]
            ch_idx[str(i)] = {
                "channel": ch,
                "id": pid,
                "url": url,
                "text": text,
                "date": date,
                "n": i,
            }
        index[ch] = ch_idx
    return index, groups


def build_channel_body(channel: str, posts: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append(f"# 📱 Telegram Catalog – @{channel}")
    lines.append("")
    lines.append(f"**Generated (Iran):** {iran_now_str()}")
    lines.append(f"**Channel:** @{channel}")
    lines.append(f"**Items (max {KEEP_PER_CHANNEL}):** {len(posts)}")
    lines.append("")
    lines.append("### 📥 How to download")
    lines.append("")
    lines.append("On **this** issue, comment:")
    lines.append("")
    lines.append("```")
    lines.append("/download <number|t.me-url> [audio|video] [mega|repo]")
    lines.append("```")
    lines.append("")
    lines.append("| Option | Meaning |")
    lines.append("|--------|---------|")
    lines.append("| `video` (default) | Full media |")
    lines.append("| `audio` | Extract mp3 from videos |")
    lines.append("| `repo` (default) | Save in this repo |")
    lines.append("| `mega` | Upload to Mega.nz |")
    lines.append("")
    lines.append("**Examples**")
    lines.append("- `/download 5`")
    lines.append(f"- `/download https://t.me/{channel}/12345 audio mega`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"### 📢 @{channel}")
    lines.append("")

    for i, p in enumerate(posts, start=1):
        pid = str(p.get("id") or p.get("message_id") or "")
        raw = (p.get("text") or p.get("caption") or "").strip()
        date = str(p.get("date") or "")[:16]
        post_url = (p.get("url") or "").strip() or f"https://t.me/{channel}/{pid}"
        header = f"### {i}. [@{channel}/{pid}]({post_url})"
        if date:
            header += f" · `{date}`"
        lines.append(header)
        lines.append("")
        if raw:
            for ln in raw.splitlines() or [raw]:
                lines.append(f"> {ln}" if ln.strip() else ">")
        else:
            lines.append("> _(no caption)_")
        lines.append("")
        lines.append(f"`/download {i}`")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"*Only this channel · max {KEEP_PER_CHANNEL} posts · see hub issue for other channels.*"
    )
    body = "\n".join(lines)
    if len(body) > BODY_MAX:
        body = (
            body[: BODY_MAX - 120]
            + "\n\n---\n\n*…truncated; open HTML archive for full captions.*"
        )
        print(f"⚠️ body @{channel} truncated to {BODY_MAX}")
    return body


def build_hub_body(channel_issues: Dict[str, Dict[str, Any]], index: Dict[str, Dict]) -> str:
    lines: List[str] = []
    lines.append("# 📱 Telegram Catalog – Channels")
    lines.append("")
    lines.append(f"**Generated (Iran):** {iran_now_str()}")
    lines.append("")
    lines.append(
        "Each channel has its **own issue** (≤50 posts). Open the channel issue to browse and `/download`."
    )
    lines.append("")
    lines.append("| Channel | Items | Issue |")
    lines.append("|---------|------:|-------|")
    for ch in sorted(channel_issues.keys(), key=str.lower):
        info = channel_issues[ch]
        n = len(index.get(ch) or {})
        num = info.get("issue_number") or ""
        url = info.get("issue_url") or ""
        link = f"[#{num}]({url})" if url else f"#{num}"
        lines.append(f"| @{ch} | {n} | {link} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Updated after each Telegram scrape run.*")
    return "\n".join(lines)


def api_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def list_open_issues(repo: str, token: str) -> List[Dict[str, Any]]:
    headers = api_headers(token)
    out: List[Dict[str, Any]] = []
    page = 1
    while page <= 10:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/issues",
            headers=headers,
            params={"state": "open", "per_page": 100, "page": page},
            timeout=60,
        )
        if r.status_code != 200:
            print(f"list issues {r.status_code}: {r.text[:200]}")
            break
        batch = r.json()
        if not batch:
            break
        for it in batch:
            if "pull_request" in it:
                continue
            out.append(it)
        if len(batch) < 100:
            break
        page += 1
    return out


def find_issue_by_title(issues: List[Dict[str, Any]], title: str) -> Optional[Dict[str, Any]]:
    for it in issues:
        if (it.get("title") or "") == title:
            return it
    return None


def create_or_update_issue(
    repo: str, token: str, title: str, body: str, existing: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    headers = api_headers(token)
    if existing:
        num = existing["number"]
        r = requests.patch(
            f"https://api.github.com/repos/{repo}/issues/{num}",
            headers=headers,
            json={"title": title, "body": body, "state": "open"},
            timeout=90,
        )
        if r.status_code == 200:
            data = r.json()
            print(f"✅ Issue updated #{num} · {title}")
            return data
        raise RuntimeError(f"update #{num} {r.status_code} {r.text[:300]}")
    r = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers=headers,
        json={"title": title, "body": body},
        timeout=90,
    )
    if r.status_code == 201:
        data = r.json()
        print(f"✅ Issue created #{data.get('number')} · {title}")
        return data
    raise RuntimeError(f"create {r.status_code} {r.text[:300]}")


def close_legacy_monolith(repo: str, token: str, issues: List[Dict[str, Any]]) -> None:
    """Close old single-catalog issue if present."""
    legacy_titles = {
        "📱 Telegram Catalog – Download",
        "Telegram Catalog – Download",
    }
    headers = api_headers(token)
    for it in issues:
        t = it.get("title") or ""
        if t in legacy_titles:
            num = it["number"]
            note = (
                "This issue is **deprecated**.\n\n"
                "Catalog is now **one issue per channel** (≤50 posts).\n\n"
                f"See **{HUB_TITLE}** for the channel list."
            )
            requests.patch(
                f"https://api.github.com/repos/{repo}/issues/{num}",
                headers=headers,
                json={"state": "closed", "body": note, "title": t + " (deprecated)"},
                timeout=60,
            )
            print(f"🔒 closed legacy issue #{num}")


def write_meta(
    repo: str,
    channel_issues: Dict[str, Dict[str, Any]],
    hub: Optional[Dict[str, Any]],
) -> None:
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    meta: Dict[str, Any] = {
        "github_repo": repo,
        "mode": "per_channel",
        "keep_per_channel": KEEP_PER_CHANNEL,
        "hub_title": HUB_TITLE,
        "hub_issue_number": int((hub or {}).get("number") or 0),
        "hub_issue_url": (hub or {}).get("html_url") or "",
        "channels": channel_issues,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if channel_issues:
        first = next(iter(channel_issues.values()))
        meta["issue_number"] = first.get("issue_number")
        meta["issue_url"] = first.get("issue_url")
        meta["issue_title"] = first.get("issue_title")
    META_PATH.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"📝 meta → {META_PATH}")


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
    INDEX_PATH.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    total = sum(len(v) for v in index.values())
    print(f"📇 index channels={len(index)} items={total} → {INDEX_PATH}")

    issues = list_open_issues(repo, token)
    close_legacy_monolith(repo, token, issues)
    issues = list_open_issues(repo, token)

    channel_issues: Dict[str, Dict[str, Any]] = {}
    for ch, posts in groups:
        title = issue_title_for(ch)
        body = build_channel_body(ch, posts)
        existing = find_issue_by_title(issues, title)
        issue = create_or_update_issue(repo, token, title, body, existing)
        channel_issues[ch] = {
            "issue_number": int(issue.get("number") or 0),
            "issue_url": issue.get("html_url") or "",
            "issue_title": title,
            "items": len(posts),
        }
        if not existing:
            issues.append(issue)

    hub_existing = find_issue_by_title(issues, HUB_TITLE)
    hub_body = build_hub_body(channel_issues, index)
    hub = create_or_update_issue(repo, token, HUB_TITLE, hub_body, hub_existing)

    write_meta(repo, channel_issues, hub)
    print(f"🔗 hub {hub.get('html_url')}")
    for ch, info in channel_issues.items():
        print(f"   @{ch} → #{info['issue_number']} ({info['items']} items)")


if __name__ == "__main__":
    main()
