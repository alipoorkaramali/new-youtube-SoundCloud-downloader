import os
import sys
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

# لاگ کردن شروع برنامه
print("🚀 Starting Flask app...", file=sys.stderr)

@app.route('/')
def home():
    try:
        print("✅ Home endpoint called", file=sys.stderr)
        return "✅ Webhook server is running!"
    except Exception as e:
        print(f"❌ Error in home: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return "Internal Server Error", 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("📩 Webhook endpoint called", file=sys.stderr)
        data = request.get_json()
        if not data:
            print("❌ Invalid JSON received", file=sys.stderr)
            return jsonify({"error": "Invalid JSON"}), 400

        url = data.get('url')
        platform = data.get('platform')

        print(f"📥 Received: platform={platform}, url={url}", file=sys.stderr)

        if not url or not platform:
            print("❌ Missing url or platform", file=sys.stderr)
            return jsonify({"error": "Missing 'url' or 'platform'"}), 400

        print("✅ Webhook processed successfully", file=sys.stderr)
        return jsonify({"message": "Workflow triggered successfully"}), 200

    except Exception as e:
        print(f"❌ Error in webhook: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    try:
        port = int(os.environ.get("PORT", 8080))
        print(f"🚀 Starting Flask on port {port}...", file=sys.stderr)
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        print(f"❌ Failed to start: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
