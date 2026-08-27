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
        "client_secret_loaded": bool(CLIENT_SECRET),
        "access_token_loaded": bool(ACCESS_TOKEN),
        "account_id_loaded": bool(ACCOUNT_ID),
        "telegram_token_loaded": bool(
            TELEGRAM_BOT_TOKEN
        ),
        "telegram_chat_id_loaded": bool(
            TELEGRAM_CHAT_ID
        ),
        "execution_enabled": EXECUTION_ENABLED
    })


@app.route("/account")
def account():
    return jsonify({
        "success": True,
        "message": "cTrader demo account authenticated",
        "account_id": ACCOUNT_ID
    })


@app.route("/market")
def market():
    return jsonify({
        "success": True,
        "message": "Market endpoint remains available",
        "account_id": ACCOUNT_ID,
        "symbol": request.args.get(
            "symbol",
            "EURUSD"
        )
    })


@app.route("/trade", methods=["POST"])
def trade():
    data = request.get_json(
        silent=True
    ) or {}

    symbol = data.get(
        "symbol",
        "EURUSD"
    )

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

    if not EXECUTION_ENABLED:
        return jsonify({
            "success": True,
            "status": "READY",
            "message": "Execution is disabled.",
            "execution_enabled": False
        })

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return jsonify({
            "success": False,
            "error": "Telegram approval system is not configured"
        }), 500

    request_id = str(uuid.uuid4())

    pending_trades[request_id] = {
        "symbol": symbol,
        "signal": signal,
        "volume": volume,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "created": time.time()
    }

    text = (
        "🚨 FOREXBOT TRADE REQUEST\n\n"
        f"Symbol: {symbol}\n"
        f"Signal: {signal}\n"
        f"Volume: {volume}\n"
        f"Stop Loss: {stop_loss}\n"
        f"Take Profit: {take_profit}\n\n"
        f"Request: {request_id}\n\n"
        "Approve this demo trade?"
    )

    buttons = [
        {
            "text": "✅ APPROVE",
            "callback_data": "approve:" + request_id
        },
        {
            "text": "❌ REJECT",
            "callback_data": "reject:" + request_id
        }
    ]

    try:
        send_telegram_message(
            text,
            buttons
        )

        return jsonify({
            "success": True,
            "status": "PENDING_APPROVAL",
            "message": "Telegram approval requested",
            "request_id": request_id
        })

    except Exception as e:

        pending_trades.pop(
            request_id,
            None
        )

        return jsonify({
            "success": False,
            "error": type(e).__name__,
            "details": str(e)
        }), 502


@app.route("/telegram", methods=["POST"])
def telegram():

    update = request.get_json(
        silent=True
    ) or {}

    callback = update.get(
        "callback_query"
    )

    if not callback:
        return jsonify({
            "success": True
        })

    callback_id = callback.get(
        "id"
    )

    callback_data = callback.get(
        "data",
        ""
    )

    callback_message = callback.get(
        "message",
        {}
    )

    callback_chat = str(
        callback_message.get(
            "chat",
            {}
        ).get(
            "id",
            ""
        )
    )

    if callback_chat != str(TELEGRAM_CHAT_ID):

        return jsonify({
            "success": False,
            "error": "Unauthorized Telegram chat"
        }), 403

    if ":" not in callback_data:
        return jsonify({
            "success": False,
            "error": "Invalid callback"
        }), 400

    action, request_id = callback_data.split(
        ":",
        1
    )

    trade = pending_trades.get(
        request_id
    )

    if not trade:
        return jsonify({
            "success": True,
            "message": "Trade request no longer exists"
        })

    if time.time() - trade["created"] > APPROVAL_TIMEOUT:

        pending_trades.pop(
            request_id,
            None
        )

        answer_callback(
            callback_id,
            "Trade request expired."
        )

        return jsonify({
            "success": True
        })

    if action == "reject":

        pending_trades.pop(
            request_id,
            None
        )

        answer_callback(
            callback_id,
            "Trade rejected."
        )

        send_telegram_message(
            "❌ Trade rejected.\n"
            f"{trade['symbol']} {trade['signal']}"
        )

        return jsonify({
            "success": True,
            "status": "REJECTED"
        })

    if action == "approve":

        pending_trades.pop(
            request_id,
            None
        )

        try:

            result = execute_trade(
                trade
            )

            answer_callback(
                callback_id,
                "Trade approved and submitted."
            )

            send_telegram_message(
                "✅ TRADE APPROVED\n\n"
                f"{trade['symbol']} {trade['signal']}\n"
                f"Volume: {trade['volume']}\n\n"
                "cTrader response:\n"
                + str(result)
            )

            return jsonify({
                "success": True,
                "status": "EXECUTED",
                "ctrader_response": result
            })

        except Exception as e:

            answer_callback(
                callback_id,
                "Trade execution failed."
            )

            send_telegram_message(
                "⚠️ TRADE EXECUTION FAILED\n\n"
                + type(e).__name__
                + ": "
                + str(e)
            )

            return jsonify({
                "success": False,
                "status": "EXECUTION_FAILED",
                "error": type(e).__name__,
                "details": str(e)
            }), 502

    return jsonify({
        "success": False,
        "error": "Unknown action"
    }), 400


def answer_callback(callback_id, text):

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/answerCallbackQuery"
    )

    requests.post(
        url,
        json={
            "callback_query_id": callback_id,
            "text": text
        },
        timeout=15
    )


if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
