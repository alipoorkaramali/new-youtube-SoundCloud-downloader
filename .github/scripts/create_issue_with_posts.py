#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create or UPDATE one GitHub Issue per Instagram channel (no delete needed)."""
import os
import json
import requests
from pathlib import Path


def build_body(data: dict) -> str:
    posts = data.get("recent_posts", [])
    username = data.get("target_username", "unknown")
    fetched_at = (data.get("fetched_at") or "")[:19].replace("T", " ")

    body = f"## 📸 Instagram posts – @{username}\n\n"
    body += f"_Updated: {fetched_at}_\n\n"
    body += "To download a post, comment:\n"
    body += "`/download shortcode`  (example: `/download CxYz123`)\n\n"
    body += "| # | shortcode | caption (preview) |\n"
    body += "|---|-----------|-------------------|\n"

    for i, post in enumerate(posts, 1):
        shortcode = post.get("shortcode", "")
        caption = (post.get("caption") or "")[:80].replace("\n", " ").replace("|", "\\|")
        body += f"| {i} | `{shortcode}` | {caption} |\n"

    if not posts:
        body += "\n_No posts returned by the scraper._\n"
    return body


def api_headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def find_existing_issue(repo: str, token: str, username: str):
    """Find open issue for this channel (prefer label + @username in title)."""
    headers = api_headers(token)
    q = f'repo:{repo} is:issue is:open label:instagram-download "@{username}" in:title'
    r = requests.get(
        "https://api.github.com/search/issues",
        headers=headers,
        params={"q": q, "per_page": 5},
        timeout=60,
    )
    if r.status_code == 200:
        items = r.json().get("items") or []
        for it in items:
            title = it.get("title") or ""
            if f"@{username}" in title:
                return it.get("number")

    r2 = requests.get(
        f"https://api.github.com/repos/{repo}/issues",
        headers=headers,
        params={"state": "open", "labels": "instagram-download", "per_page": 50},
        timeout=60,
    )
    if r2.status_code == 200:
        for it in r2.json():
            if it.get("pull_request"):
                continue
            title = it.get("title") or ""
            if f"@{username}" in title and "Instagram" in title:
                return it.get("number")

    r3 = requests.get(
        f"https://api.github.com/repos/{repo}/issues",
        headers=headers,
        params={"state": "open", "per_page": 50},
        timeout=60,
    )
    if r3.status_code == 200:
        for it in r3.json():
            if it.get("pull_request"):
                continue
            title = it.get("title") or ""
            if f"@{username}" in title and ("Instagram" in title or "اینستاگرام" in title):
                return it.get("number")
    return None


def create_issue(repo: str, token: str, title: str, body: str) -> str:
    url = f"https://api.github.com/repos/{repo}/issues"
    payload = {
        "title": title,
        "body": body,
        "labels": ["instagram-download"],
    }
    resp = requests.post(url, headers=api_headers(token), json=payload, timeout=60)
    if resp.status_code == 201:
        return resp.json().get("html_url", "")
    raise RuntimeError(f"create {resp.status_code} — {resp.text[:400]}")


def update_issue(repo: str, token: str, number: int, title: str, body: str) -> str:
    url = f"https://api.github.com/repos/{repo}/issues/{number}"
    payload = {
        "title": title,
        "body": body,
        "state": "open",
        "labels": ["instagram-download"],
    }
    resp = requests.patch(url, headers=api_headers(token), json=payload, timeout=60)
    if resp.status_code == 200:
        return resp.json().get("html_url", f"https://github.com/{repo}/issues/{number}")
    raise RuntimeError(f"update #{number} {resp.status_code} — {resp.text[:400]}")


def main():
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GH_PAT")
    if not token:
        print("❌ GH_PAT / ISSUES_DELETE_PAT not set")
        raise SystemExit(1)
    if not repo:
        print("❌ GITHUB_REPOSITORY not set")
        raise SystemExit(1)

    manifest_path = Path("instagram_fetch_manifest.json")
    if not manifest_path.exists():
        print("ℹ️ No manifest — nothing to do")
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    channels = manifest.get("channels") or []
    created = 0
    updated = 0
    skipped = 0

    for entry in channels:
        if entry.get("skipped_unchanged"):
            print(f"⏭️ @{entry.get('username')}: unchanged — leave issue as-is")
            skipped += 1
            continue
        if not entry.get("ok") or not entry.get("issue_update"):
            if entry.get("error"):
                print(f"⏭️ skip @{entry.get('username')}: {entry.get('error')}")
            continue

        path = Path(entry["file"])
        if not path.exists():
            print(f"⚠️ missing file {path}")
            continue

        data = json.loads(path.read_text(encoding="utf-8"))
        username = data.get("target_username") or entry["username"]
        title = f"📸 Instagram posts - @{username}"
        body = build_body(data)

        existing = find_existing_issue(repo, token, username)
        try:
            if existing:
                url = update_issue(repo, token, int(existing), title, body)
                print(f"♻️ @{username}: updated #{existing} → {url}")
                updated += 1
            else:
                url = create_issue(repo, token, title, body)
                print(f"✅ @{username}: created → {url}")
                created += 1
        except Exception as e:
            print(f"❌ @{username}: {e}")

    print(f"🏁 created={created} | updated={updated} | unchanged_skipped={skipped}")


if __name__ == "__main__":
    main()
