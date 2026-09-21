#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch Instagram posts via Apify for one or many usernames.

Actor: apify/instagram-post-scraper (official Apify)
Works with any number of APIFY_API_TOKEN accounts via round-robin.

Always fetches the last N posts (default 10). Pinned posts stay first in the
feed, so a 1-post probe is unreliable. We compare the full shortcode list to
State and only skip the GitHub Issue update when nothing changed.
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

# Official Apify actor — username[] + resultsLimit; field shortCode in output
ACTOR_ID = "apify/instagram-post-scraper"


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


def maybe_save_to_channels_file(usernames):
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


def load_state(path):
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


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_apify_tokens():
    """Collect APIFY_API_TOKEN, APIFY_API_TOKEN_2, _3, ... (any non-empty)."""
    tokens = []
    t1 = (os.environ.get("APIFY_API_TOKEN") or "").strip()
    if t1:
        tokens.append(t1)
    for i in range(2, 21):
        t = (os.environ.get(f"APIFY_API_TOKEN_{i}") or "").strip()
        if t:
            tokens.append(t)
    return tokens


def pick_token(tokens, counter_file):
    """Round-robin across all available Apify tokens."""
    if not tokens:
        print("❌ No Apify tokens found (set APIFY_API_TOKEN and optionally APIFY_API_TOKEN_2, _3, ...)")
        raise SystemExit(1)

    counter = 0
    if counter_file.exists():
        try:
            counter = int(counter_file.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            counter = 0

    idx = counter % len(tokens)
    account = idx + 1
    token = tokens[idx]
    counter_file.parent.mkdir(parents=True, exist_ok=True)
    counter_file.write_text(str(counter + 1), encoding="utf-8")
    print(f"🔄 Using Apify account #{account}/{len(tokens)} (round-robin, counter={counter})")
    return token, account


def extract_shortcode(item):
    """Normalize shortcode from official actor output (shortCode)."""
    for key in ("shortCode", "shortcode", "code"):
        v = item.get(key)
        if v:
            return str(v).strip()
    url = str(item.get("url") or item.get("inputUrl") or "")
    m = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else ""


def normalize_post(item):
    """Stable shape for Issue table + state (shortcode + caption)."""
    sc = extract_shortcode(item)
    out = dict(item)
    out["shortcode"] = sc
    if out.get("caption") is None:
        out["caption"] = ""
    return out


def fetch_posts(client, username, post_count):
    run_input = {
        "username": [username],
        "resultsLimit": max(1, int(post_count)),
        "dataDetailLevel": "basicData",
    }
    run = client.actor(ACTOR_ID).call(run_input=run_input)
    print(f"   ✅ Actor run: {run['id']} ({ACTOR_ID}, requested={post_count})")
    posts = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        posts.append(normalize_post(item))
        if len(posts) >= post_count:
            break
    return posts


def shortcode_list(posts):
    return [str(p.get("shortcode") or "").strip() for p in posts if p.get("shortcode")]


def main():
    tokens = load_apify_tokens()
    if not tokens:
        print("❌ APIFY_API_TOKEN is not set (and no APIFY_API_TOKEN_2/3/...)")
        raise SystemExit(1)
    print(f"🔑 Apify tokens loaded: {len(tokens)}")

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
    print(f"🤖 Actor: {ACTOR_ID}")

    manifest = {
        "fetched_at": datetime.now().isoformat(),
        "post_count": post_count,
        "actor": ACTOR_ID,
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
        known_list = [str(x).strip() for x in (ch_state.get("recent_shortcodes") or []) if str(x).strip()]

        try:
            token, _ = pick_token(tokens, counter_file)
            client = ApifyClient(token)

            # Always fetch last N posts (pinned-safe)
            posts = fetch_posts(client, username, post_count)
            codes = shortcode_list(posts)
            sc = codes[0] if codes else ""

            unchanged = (
                not force
                and bool(codes)
                and bool(known_list)
                and codes == known_list[: len(codes)]
            )

            if unchanged:
                print(f"   ⏭️ Shortcode list unchanged ({len(codes)} posts) — skip Issue update")
                entry.update({
                    "ok": True,
                    "skipped_unchanged": True,
                    "issue_update": False,
                    "fetched_posts": len(posts),
                    "file": ch_state.get("last_file"),
                })
                # still refresh last_fetched_at lightly in state? keep old file path
                state["channels"][username] = {
                    **ch_state,
                    "last_shortcode": sc or ch_state.get("last_shortcode", ""),
                    "last_fetched_at": datetime.now().isoformat(),
                    "recent_shortcodes": codes or known_list,
                }
                manifest["channels"].append(entry)
                continue

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            rel = f"instagram_data/{username}_{ts}.json"
            result = {
                "target_username": username,
                "requested_posts": post_count,
                "fetched_posts": len(posts),
                "fetched_at": datetime.now().isoformat(),
                "actor": ACTOR_ID,
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
                "recent_shortcodes": codes[:20],
            }

            entry.update({
                "ok": True,
                "file": rel,
                "fetched_posts": len(posts),
                "issue_update": bool(posts),
            })
            if not posts:
                print(f"   ⚠️ 0 posts returned for @{username}")
            else:
                print(f"   💾 {len(posts)} posts → {rel} (first={sc})")
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
