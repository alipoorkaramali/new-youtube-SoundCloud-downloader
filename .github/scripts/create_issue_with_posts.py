import os
import json
import requests
from pathlib import Path

def main():
    repo = os.environ.get('GITHUB_REPOSITORY')
    token = os.environ.get('GH_PAT')
    if not token:
        print("❌ GH_PAT not set")
        exit(1)

    json_file = Path("instagram_posts.json")
    if not json_file.exists():
        print("❌ instagram_posts.json not found")
        exit(1)

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    posts = data.get('recent_posts', [])
    if not posts:
        print("No posts to show")
        exit(0)

    username = data.get('target_username', 'unknown')
    fetched_at = data.get('fetched_at', '')[:10]

    # ساخت بدنه ایشو
    body = f"## 📸 پست‌های اینستاگرام – @{username} – {fetched_at}\n\n"
    body += "برای دانلود هر پست، **shortcode** آن را در یک کامنت جدید بنویسید:\n"
    body += "`/download shortcode`  (مثال: `/download CxYz123`)\n\n"
    body += "| shortcode | کپشن (بخشی) |\n"
    body += "|-----------|--------------|\n"

    for post in posts:
        shortcode = post.get('shortcode', '')
        caption = post.get('caption', '')[:80].replace('\n', ' ').replace('|', '\\|')
        body += f"| `{shortcode}` | {caption} |\n"

    # ایجاد ایشو
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "title": f"📸 پست‌های اینستاگرام - @{username} - {fetched_at}",
        "body": body,
        "labels": ["instagram-download"]
    }
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code == 201:
        print(f"✅ Issue created: {resp.json()['html_url']}")
    else:
        print(f"❌ Failed to create issue: {resp.status_code} - {resp.text}")
        exit(1)

if __name__ == '__main__':
    main()
