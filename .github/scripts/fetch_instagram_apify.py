#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch Instagram posts via Apify for one or many usernames.

Optimization: probe latest post (1 item). If shortcode matches State, skip full Apify pull.
"""
import os
import json
import re
from pathlib import Path
from datetime import datetime

try:
    from apify_client import ApifyClient
except ImportError:
    print("❌ apify-client not installed")
    raise SystemExit(1)


def load_usernames():
    raw = (os.environ.get("USERNAMES_INPUT") or "").strip()
    if raw:
        parts = re.split(r"[\s,;]+", raw)
        users = [p.lstrip("@").strip() for p in parts if p.strip() and not p.strip().startswith("#")]
        return list(dict.fromkeys(users))

    channels_file = Path(os.environ.get("CHANNELS_FILE", "config/instagram_channels.txt"))
    if not channels_file.exists():
        print(f"❌ No usernames input and file missing: {channels_file}")
        raise SystemExit(1)

    users = []
    for line in channels_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        users.append(line.lstrip("@").strip())
    users = list(dict.fromkeys([u for u in users if u]))
    if not users:
        print(f"❌ No usernames in {channels_file}")
        raise SystemExit(1)
    return users


def maybe_save_to_channels_file(usernames: list) -> None:
    flag = (os.environ.get("ADD_TO_LIST") or "").strip().lower()
    if flag not in ("true", "1", "yes"):
        return
    raw_input = (os.environ.get("USERNAMES_INPUT") or "").strip()
    if not raw_input:
        print("ℹ️ add_to_list ignored (no usernames input — already using the file list)")
        return

    channels_file = Path(os.environ.get("CHANNELS_FILE", "config/instagram_channels.txt"))
    channels_file.parent.mkdir(parents=True, exist_ok=True)

    existing = []
    if channels_file.exists():
        for line in channels_file.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            existing.append(s.lstrip("@").strip())

    existing_set = {u.lower() for u in existing}
    added = []
    for u in usernames:
        if u.lower() not in existing_set:
            existing.append(u)
            existing_set.add(u.lower())
            added.append(u)

    lines = [
        "# Instagram channels to fetch (one username per line)",
        "# Lines starting with # are ignored",
        '# Override at runtime via workflow input "usernames" (comma-separated)',
        "#",
        "",
    ]
    lines.extend(existing)
    channels_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if added:
        print(f"📌 Added to {channels_file}: {', '.join('@' + a for a in added)}")
    else:
        print(f"ℹ️ All usernames already in {channels_file}")


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"channels": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"channels": {}}
        data.setdefault("channels", {})
        return data
    except Exception:
        return {"channels": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def pick_token(token1, token2, counter_file: Path):
    counter = 0
    if counter_file.exists():
        try:
            counter = int(counter_file.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            counter = 0

    if token2:
        if counter % 2 == 0:
            token, account = token1, 1
        else:
            token, account = token2, 2
        counter_file.parent.mkdir(parents=True, exist_ok=True)
        counter_file.write_text(str(counter + 1), encoding="utf-8")
        print(f"🔄 Using Apify account #{account} (round-robin, counter={counter})")
        return token, account

    print("ℹ️ Only one Apify token available")
    return token1, 1


def fetch_posts(client: ApifyClient, username: str, post_count: int) -> list:
    actor_id = "khadinakbar/instagram-posts-scraper"
    run_input = {
        "instagramUsernames": [username],
        "maxPostsPerTarget": post_count,
        "includeRecentComments": True,
        "proxyConfiguration": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        },
    }
    run = client.actor(actor_id).call(run_input=run_input)
    print(f"   ✅ Actor run: {run['id']} (requested={post_count})")
    posts = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        posts.append(item)
        if len(posts) >= post_count:
            break
    return posts


def latest_shortcode(posts: list) -> str:
    if not posts:
        return ""
    return str(posts[0].get("shortcode") or "").strip()


def main():
    token1 = os.environ.get("APIFY_API_TOKEN")
    token2 = os.environ.get("APIFY_API_TOKEN_2") or None
    if not token1:
        print("❌ APIFY_API_TOKEN is not set")
        raise SystemExit(1)

    force = (os.environ.get("FORCE_REFRESH") or "").strip().lower() in ("true", "1", "yes")

    try:
        post_count = int(os.environ.get("POST_COUNT", "10"))
        if post_count not in (5, 10, 15, 20):
            post_count = 10
    except ValueError:
        post_count = 10

    counter_file = Path(os.environ.get("TOKEN_COUNTER_FILE", "State/apify_token_counter.txt"))
    state_file = Path(os.environ.get("STATE_FILE", "State/instagram_channel_state.json"))
    out_dir = Path("instagram_data")
    out_dir.mkdir(parents=True, exist_ok=True)

    usernames = load_usernames()
    maybe_save_to_channels_file(usernames)
    state = load_state(state_file)

    print(f"📋 Channels ({len(usernames)}): {', '.join('@' + u for u in usernames)}")
    print(f"📊 Posts per channel: {post_count} | force_refresh={force}")

    manifest = {
        "fetched_at": datetime.now().isoformat(),
        "post_count": post_count,
        "channels": [],
    }

    for username in usernames:
        print(f"\n🔍 @{username} ...")
        entry = {
            "username": username,
            "ok": False,
            "file": None,
            "fetched_posts": 0,
            "error": None,
            "skipped_unchanged": False,
            "issue_update": False,
        }
        ch_state = state["channels"].get(username) or {}
        known = str(ch_state.get("last_shortcode") or "").strip()

        try:
            token, _ = pick_token(token1, token2, counter_file)
            client = ApifyClient(token)

            if not force and known:
                print(f"   🔎 Probe latest post (known last={known}) ...")
                probe = fetch_posts(client, username, 1)
                probe_sc = latest_shortcode(probe)
                if probe_sc and probe_sc == known:
                    print(f"   ⏭️ Unchanged (latest still {probe_sc}) — skip full Apify pull & issue")
                    entry.update({
                        "ok": True,
                        "skipped_unchanged": True,
                        "issue_update": False,
                        "fetched_posts": 0,
                        "file": ch_state.get("last_file"),
                    })
                    manifest["channels"].append(entry)
                    continue
                print(f"   🆕 New content detected (probe={probe_sc or 'n/a'} ≠ known={known})")
                token, _ = pick_token(token1, token2, counter_file)
                client = ApifyClient(token)
            elif force:
                print("   ⚡ force_refresh — full fetch")

            posts = fetch_posts(client, username, post_count)
            sc = latest_shortcode(posts)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            rel = f"instagram_data/{username}_{ts}.json"
            result = {
                "target_username": username,
                "requested_posts": post_count,
                "fetched_posts": len(posts),
                "fetched_at": datetime.now().isoformat(),
                "recent_posts": posts,
            }
            Path(rel).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            Path("instagram_posts.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            state["channels"][username] = {
                "last_shortcode": sc,
                "last_fetched_at": result["fetched_at"],
                "last_file": rel,
                "recent_shortcodes": [str(p.get("shortcode") or "") for p in posts[:20]],
            }

            entry.update({
                "ok": True,
                "file": rel,
                "fetched_posts": len(posts),
                "issue_update": True,
            })
            print(f"   💾 {len(posts)} posts → {rel} (latest={sc})")
        except Exception as e:
            entry["error"] = str(e)
            print(f"   ❌ @{username}: {e}")

        manifest["channels"].append(entry)

    save_state(state_file, state)
    Path("instagram_fetch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ok_n = sum(1 for c in manifest["channels"] if c["ok"])
    upd_n = sum(1 for c in manifest["channels"] if c.get("issue_update"))
    skip_n = sum(1 for c in manifest["channels"] if c.get("skipped_unchanged"))
    print(f"\n🏁 OK={ok_n}/{len(usernames)} | issue updates={upd_n} | unchanged skips={skip_n}")
    if ok_n == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
