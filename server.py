from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify(status="online", service="ForexBot cTrader Relay", version="1.1")

@app.route("/health")
def health():
    return jsonify(status="healthy")

@app.route("/credentials")
def credentials():
    import os
    return jsonify(
        client_id_loaded=bool(os.getenv("CTRADER_CLIENT_ID")),
        client_secret_loaded=bool(os.getenv("CTRADER_CLIENT_SECRET")),
        access_token_loaded=bool(os.getenv("CTRADER_ACCESS_TOKEN"))
    )

@app.route("/account")
def account():
    return jsonify(success=True, message="cTrader relay is ready")

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
