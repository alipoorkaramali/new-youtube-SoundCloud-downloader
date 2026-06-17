from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Webhook server is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    url = data.get('url')
    platform = data.get('platform')

    if not url or not platform:
        return jsonify({"error": "Missing 'url' or 'platform'"}), 400

    # برای تست، همینجا پاسخ موفق می‌دهیم
    # بعداً کد کامل trigger_download را اضافه می‌کنیم
    return jsonify({"message": "Workflow triggered successfully"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
