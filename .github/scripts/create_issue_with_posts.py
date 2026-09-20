#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create one GitHub Issue per channel from instagram_fetch_manifest.json."""
import os
import json
import requests
from pathlib import Path


def build_body(data: dict) -> str:
    posts = data.get("recent_posts", [])
    username = data.get("target_username", "unknown")
    fetched_at = (data.get("fetched_at") or "")[:10]

    body = f"## 📸 Instagram posts – @{username} – {fetched_at}\n\n"
    body += "To download a post, comment:\n"
    body += "`/download shortcode`  (example: `/download CxYz123`)\n\n"
    body += "| shortcode | caption (preview) |\n"
    body += "|-----------|-------------------|\n"

    for post in posts:
        shortcode = post.get("shortcode", "")
        caption = (post.get("caption") or "")[:80].replace("\n", " ").replace("|", "\\|")
        body += f"| `{shortcode}` | {caption} |\n"

    if not posts:
        body += "\n_No posts returned by the scraper._\n"
    return body


def create_issue(repo: str, token: str, title: str, body: str) -> str:
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "title": title,
        "body": body,
        "labels": ["instagram-download"],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code == 201:
        return resp.json().get("html_url", "")
    raise RuntimeError(f"{resp.status_code} — {resp.text[:500]}")


def main():
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GH_PAT")
    if not token:
        print("❌ GH_PAT not set")
        raise SystemExit(1)
    if not repo:
        print("❌ GITHUB_REPOSITORY not set")
        raise SystemExit(1)

    manifest_path = Path("instagram_fetch_manifest.json")
    if not manifest_path.exists():
        single = Path("instagram_posts.json")
        if not single.exists():
            print("❌ No manifest and no instagram_posts.json")
            raise SystemExit(1)
        data = json.loads(single.read_text(encoding="utf-8"))
        username = data.get("target_username", "unknown")
        fetched_at = (data.get("fetched_at") or "")[:10]
        title = f"📸 Instagram posts - @{username} - {fetched_at}"
        url = create_issue(repo, token, title, build_body(data))
        print(f"✅ Issue created: {url}")
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    channels = manifest.get("channels") or []
    created = 0
    for entry in channels:
        if not entry.get("ok"):
            print(f"⏭️ skip @{entry.get('username')}: {entry.get('error')}")
            continue
        path = Path(entry["file"])
        if not path.exists():
            print(f"⚠️ missing file {path}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        username = data.get("target_username") or entry["username"]
        fetched_at = (data.get("fetched_at") or "")[:10]
        title = f"📸 Instagram posts - @{username} - {fetched_at}"
        try:
            url = create_issue(repo, token, title, build_body(data))
            print(f"✅ @{username}: {url}")
            created += 1
        except Exception as e:
            print(f"❌ @{username}: {e}")

    print(f"🏁 Issues created: {created}")
    if created == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
