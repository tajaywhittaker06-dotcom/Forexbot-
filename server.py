import os
import uuid
import requests

from flask import Flask, jsonify, request

app = Flask(__name__)

RELAY_URL = "https://demo.ctraderapi.com:5036"

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = os.getenv("CTRADER_ACCOUNT_ID")


@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "service": "ForexBot cTrader Relay",
        "version": "2.5"
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy"
    })


@app.route("/credentials")
def credentials():
    return jsonify({
        "client_id_loaded": bool(CLIENT_ID),
        "client_secret_loaded": bool(CLIENT_SECRET),
        "access_token_loaded": bool(ACCESS_TOKEN),
        "account_id_loaded": bool(ACCOUNT_ID)
    })


@app.route("/account")
def account():
    return jsonify({
        "success": True,
        "message": "cTrader account authenticated",
        "account_id": ACCOUNT_ID
    })


@app.route("/market")
def market():
    symbol = request.args.get("symbol", "EURUSD")

    return jsonify({
        "success": True,
        "symbol": symbol,
        "account_id": ACCOUNT_ID,
        "message": "Market endpoint available"
    })


@app.route("/trade", methods=["POST"])
def trade():

    data = request.get_json(silent=True) or {}

    symbol = data.get("symbol", "EURUSD")
    signal = data.get("signal")
    volume = data.get("volume")
    stop_loss = data.get("stop_loss")
    take_profit = data.get("take_profit")

    if signal not in ("BUY", "SELL"):
        return jsonify({
            "success": False,
            "error": "Signal must be BUY or SELL"
        }), 400

    if volume is None:
        return jsonify({
            "success": False,
            "error": "Volume is required"
        }), 400

    return jsonify({
        "success": True,
        "status": "READY",
        "message": "Trade request received. Execution not enabled.",
        "request_id": str(uuid.uuid4()),
        "account_id": ACCOUNT_ID,
        "symbol": symbol,
        "signal": signal,
        "volume": volume,
        "stop_loss": stop_loss,
        "take_profit": take_profit
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port
    )
