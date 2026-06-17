from flask import Flask, request, jsonify
import os
import sys
from waitress import serve

app = Flask(__name__)

@app.before_request
def log_request():
    print(f"📥 Received: {request.method} {request.path}", file=sys.stderr)

@app.route('/')
def home():
    return "✅ Webhook server is running!"

@app.route('/ping')
@app.route('/health')
@app.route('/healthz')
def health():
    return "pong", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    url = data.get('url')
    platform = data.get('platform')

    if not url or not platform:
        return jsonify({"error": "Missing 'url' or 'platform'"}), 400

    return jsonify({"message": "Workflow triggered successfully"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Starting Waitress on port {port}...", file=sys.stderr)
    serve(app, host='0.0.0.0', port=port, threads=4)
