#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create or UPDATE one GitHub Issue per Instagram channel (no delete needed)."""
import os
import json
import re
import requests
from pathlib import Path


def format_caption(raw: str) -> str:
    """Flatten whitespace for markdown table cell; keep full caption (no truncate)."""
    text = (raw or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("|", "\\|")
    return text


def build_body(data: dict) -> str:
    posts = data.get("recent_posts", [])
    username = data.get("target_username", "unknown")
    fetched_at = (data.get("fetched_at") or "")[:19].replace("T", " ")

    body = f"## 📸 Instagram posts – @{username}\n\n"
    body += f"_Updated: {fetched_at}_\n\n"
    body += "To download a post, comment:\n"
    body += "`/download shortcode`  (example: `/download CxYz123`)\n\n"
    body += "| # | shortcode | caption |\n"
    body += "|---|-----------|---------|\n"

    for i, post in enumerate(posts, 1):
        shortcode = post.get("shortcode", "")
        caption = format_caption(post.get("caption") or "")
        body += f"| {i} | `{shortcode}` | {caption} |\n"

    if not posts:
        body += "\n_No posts returned by the scraper._\n"
    return body


def api_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _title_matches(title: str, username: str) -> bool:
    t = (title or "").lower()
    u = username.lower()
    if f"@{u}" not in t:
        return False
    # Instagram / اینستاگرام markers (English or Persian titles from older runs)
    return (
        "instagram" in t
        or "اینستاگرام" in (title or "")
        or "posts" in t
        or "پست" in (title or "")
    )


def find_matching_open_issues(repo: str, token: str, username: str) -> list:
    """Return all open issue numbers matching this channel (newest first)."""
    headers = api_headers(token)
    found = {}

    # 1) Search API
    q = f'repo:{repo} is:issue is:open "@{username}" in:title'
    try:
        r = requests.get(
            "https://api.github.com/search/issues",
            headers=headers,
            params={"q": q, "per_page": 20},
            timeout=60,
        )
        if r.status_code == 200:
            for it in r.json().get("items") or []:
                if _title_matches(it.get("title") or "", username):
                    found[int(it["number"])] = it
        else:
            print(f"   search API: {r.status_code}")
    except Exception as e:
        print(f"   search error: {e}")

    # 2) List open issues (paginated lightly)
    try:
        r2 = requests.get(
            f"https://api.github.com/repos/{repo}/issues",
            headers=headers,
            params={"state": "open", "per_page": 100},
            timeout=60,
        )
        if r2.status_code == 200:
            for it in r2.json():
                if it.get("pull_request"):
                    continue
                if _title_matches(it.get("title") or "", username):
                    found[int(it["number"])] = it
        else:
            print(f"   list issues: {r2.status_code} {r2.text[:120]}")
    except Exception as e:
        print(f"   list error: {e}")

    # newest number first
    return sorted(found.keys(), reverse=True)


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
    # Label might not exist yet — retry without labels
    if resp.status_code == 422:
        payload.pop("labels", None)
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
    }
    resp = requests.patch(url, headers=api_headers(token), json=payload, timeout=60)
    if resp.status_code == 200:
        # try attach label (ignore failure if label missing)
        try:
            requests.post(
                f"https://api.github.com/repos/{repo}/issues/{number}/labels",
                headers=api_headers(token),
                json={"labels": ["instagram-download"]},
                timeout=30,
            )
        except Exception:
            pass
        return resp.json().get("html_url", f"https://github.com/{repo}/issues/{number}")
    raise RuntimeError(f"update #{number} {resp.status_code} — {resp.text[:400]}")


def close_issue(repo: str, token: str, number: int) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{number}"
    resp = requests.patch(
        url,
        headers=api_headers(token),
        json={
            "state": "closed",
            "state_reason": "not_planned",
        },
        timeout=60,
    )
    if resp.status_code == 200:
        print(f"  🔒 closed duplicate #{number}")
    else:
        print(f"  ⚠️ close #{number}: {resp.status_code}")


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

        matches = find_matching_open_issues(repo, token, username)
        print(f"🔎 @{username}: open matches={matches}")

        try:
            if matches:
                keep = matches[0]  # newest
                url = update_issue(repo, token, keep, title, body)
                print(f"♻️ @{username}: updated #{keep} → {url}")
                updated += 1
                for dup in matches[1:]:
                    close_issue(repo, token, dup)
            else:
                url = create_issue(repo, token, title, body)
                print(f"✅ @{username}: created → {url}")
                created += 1
        except Exception as e:
            print(f"❌ @{username}: {e}")

    print(f"🏁 created={created} | updated={updated} | unchanged_skipped={skipped}")


if __name__ == "__main__":
    main()
