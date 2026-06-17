import os
import time
from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

@app.route('/trigger', methods=['POST'])
def trigger_download():
    data = request.get_json() or {}
    url = data.get('url')
    platform = data.get('platform', 'youtube')
    download_type = data.get('type', 'video')
    
    if not url:
        return jsonify({"status": "error", "message": "URL is required"}), 400

    print(f"🎯 دریافت دستور دانلود: {url}")
    
    try:
        # اجرای دانلودر اصلی
        cmd = ["python", "downloader.py", url, platform, download_type]
        subprocess.run(cmd, check=True, timeout=1800)  # حداکثر ۳۰ دقیقه
        return jsonify({"status": "success", "message": "دانلود شروع شد"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/')
def home():
    return "Downloader Listener is running..."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Downloader Listener started on port {port}")
    app.run(host='0.0.0.0', port=port)
