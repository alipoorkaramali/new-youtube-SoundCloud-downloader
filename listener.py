from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# فقط یک تابع home داریم
@app.route('/')
def home():
    return "✅ Webhook server is running!"

# Webhook endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    url = data.get('url')
    platform = data.get('platform')

    if not url or not platform:
        return jsonify({"error": "Missing 'url' or 'platform'"}), 400

    # فعلاً برای تست، همینجا پاسخ موفق بده
    # بعداً کد trigger_download رو اضافه کن
    return jsonify({"message": "Workflow triggered successfully"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
