from flask import Flask, request, jsonify
import requests
import os
import hashlib

app = Flask(__name__)

# ===== تنظیمات =====
REPO_OWNER = "alipoorkaramali"
REPO_NAME = "new-youtube-SoundCloud-downloader"
WORKFLOW_FILE = "Multi-Platform Downloader-auto🔐.yml"  # یا نام جدید

TOKEN = os.environ.get("CROSS_REPO_PAT") or os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    raise Exception("❌ توکن GitHub تنظیم نشده است!")

# ===== تابع فعال‌سازی workflow (دقیقاً مشابه check_and_trigger) =====
def trigger_download(video_url: str, platform: str):
    workflow_id = requests.utils.quote(WORKFLOW_FILE, safe='')
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{workflow_id}/dispatches"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "ref": "main",
        "inputs": {
            "platform": platform,
            "url": video_url,
            "format": "audio",
            "folder": "audio_downloads"
        }
    }
    resp = requests.post(url, headers=headers, json=payload)
    return resp.status_code == 204

# ===== Endpoint وب‌هوک =====
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    url = data.get('url')
    platform = data.get('platform')  # 'youtube' یا 'soundcloud'

    if not url or not platform:
        return jsonify({"error": "Missing 'url' or 'platform'"}), 400

    print(f"📩 درخواست جدید دریافت شد: {platform} - {url}")

    success = trigger_download(url, platform)
    if success:
        return jsonify({"message": "Workflow triggered successfully"}), 200
    else:
        return jsonify({"error": "Failed to trigger workflow"}), 500

# ===== برای اجرا روی Railway =====
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
