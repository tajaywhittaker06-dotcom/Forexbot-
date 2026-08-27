import os
import uuid
import time
import requests
import websocket

from flask import Flask, jsonify, request

app = Flask(__name__)

CTRADER_HOST = "wss://demo.ctraderapi.com:5036"

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = int(os.getenv("CTRADER_ACCOUNT_ID", "0"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PRICE_SCALE = 100000

EXECUTION_ENABLED = (
    os.getenv("CTRADER_EXECUTION_ENABLED", "false").lower()
    == "true"
)

APPROVAL_TIMEOUT = 120

pending_trades = {}


def send_message(ws, payload_type, payload):
    message = {
        "clientMsgId": str(uuid.uuid4()),
        "payloadType": payload_type,
        "payload": payload
    }

    ws.send(__import__("json").dumps(message))
    return __import__("json").loads(ws.recv())


def authenticate():
    ws = websocket.create_connection(
        CTRADER_HOST,
        timeout=15
    )

    result = send_message(
        ws,
        2100,
        {
            "clientId": CLIENT_ID,
            "clientSecret": CLIENT_SECRET
        }
    )

    if result.get("payloadType") != 2101:
        raise RuntimeError(
            "Application authentication failed"
        )

    result = send_message(
        ws,
        2102,
        {
            "ctidTraderAccountId": ACCOUNT_ID,
            "accessToken": ACCESS_TOKEN
        }
    )

    if result.get("payloadType") != 2103:
        raise RuntimeError(
            "Account authentication failed"
        )

    return ws


def find_symbol_id(ws, symbol):
    result = send_message(
        ws,
        2114,
        {
            "ctidTraderAccountId": ACCOUNT_ID
        }
    )

    if result.get("payloadType") != 2115:
        raise RuntimeError(
            "Symbol request failed"
        )

    symbols = result.get(
        "payload",
        {}
    ).get(
        "symbol",
        []
    )

    for item in symbols:
        if item.get("symbolName") == symbol:
            return item.get("symbolId")

    raise RuntimeError(
        f"Symbol not found: {symbol}"
    )


def send_telegram_message(text, buttons=None):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing"
        )

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }

    if buttons:
        payload["reply_markup"] = {
            "inline_keyboard": [
                buttons
            ]
        }

    response = requests.post(
        url,
        json=payload,
        timeout=15
    )

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(
            "Telegram error: " + str(data)
        )

    return data


def execute_trade(trade):
    ws = None

    try:
        ws = authenticate()

        symbol_id = find_symbol_id(
            ws,
            trade["symbol"]
        )

        if trade["signal"] == "BUY":
            trade_side = 1
        else:
            trade_side = 2

        volume = int(trade["volume"])

        if volume <= 0:
            raise ValueError(
                "Volume must be greater than zero"
            )

        payload = {
            "ctidTraderAccountId": ACCOUNT_ID,
            "symbolId": symbol_id,
            "orderType": 1,
            "tradeSide": trade_side,
            "volume": volume,
            "label": "ForexBot_v3.2",
            "comment": "Telegram approved demo trade"
        }

        result = send_message(
            ws,
            2106,
            payload
        )

        return result

    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass


@app.route("/")
def home():
    return jsonify({
        "service": "ForexBot cTrader Relay",
        "status": "online",
        "version": "3.1",
        "execution_enabled": EXECUTION_ENABLED,
        "telegram_enabled": bool(
            TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
        )
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
        "client_secret_loaded":
