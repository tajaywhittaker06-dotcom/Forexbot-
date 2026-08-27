import os
import json
import uuid
import time
import requests
import websocket

from flask import Flask, jsonify, request

app = Flask(__name__)

# ============================================================
# cTRADER SETTINGS
# ============================================================

CTRADER_HOST = "wss://demo.ctraderapi.com:5036"

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")

ACCOUNT_ID = int(
    os.getenv("CTRADER_ACCOUNT_ID", "0")
)

EXECUTION_ENABLED = (
    os.getenv(
        "CTRADER_EXECUTION_ENABLED",
        "false"
    ).lower() == "true"
)

# ============================================================
# TELEGRAM SETTINGS
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

APPROVAL_TIMEOUT = 120

# cTrader volume mapping for this EURUSD account:
# 100000 cTrader units = 0.01 lot
# 1000000 cTrader units = 0.10 lot
# 10000000 cTrader units = 1.00 lot
CTRADER_VOLUME_PER_LOT = 10000000

pending_trades = {}


# ============================================================
# LOT SIZE HELPER
# ============================================================

def volume_to_lots(volume):
    """
    Convert cTrader volume units to displayed lot size.

    For this account:
    100000 units = 0.01 lot
    """

    try:
        volume = int(volume)
    except (TypeError, ValueError):
        return 0.0

    return volume / CTRADER_VOLUME_PER_LOT


# ============================================================
# cTRADER MESSAGE HELPER
# ============================================================

def send_message(ws, payload_type, payload):

    message = {
        "clientMsgId": str(uuid.uuid4()),
        "payloadType": payload_type,
        "payload": payload
    }

    ws.send(json.dumps(message))

    response = ws.recv()

    return json.loads(response)


# ============================================================
# cTRADER AUTHENTICATION
# ============================================================

def authenticate():

    ws = websocket.create_connection(
        CTRADER_HOST,
        timeout=15
    )

    # Application authentication
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
            "Application authentication failed: "
            + str(result)
        )

    # Account authentication
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
            "Account authentication failed: "
            + str(result)
        )

    return ws


# ============================================================
# FIND cTRADER SYMBOL ID
# ============================================================

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
            "Symbol request failed: "
            + str(result)
        )

    symbols = (
        result.get("payload", {})
        .get("symbol", [])
    )

    for item in symbols:

        if item.get("symbolName") == symbol:

            return item.get("symbolId")

    raise RuntimeError(
        f"Symbol not found: {symbol}"
    )


# ============================================================
# MARKET DATA
# ============================================================

def get_market_data(symbol, count):

    ws = None

    try:

        ws = authenticate()

        symbol_id = find_symbol_id(
            ws,
            symbol
        )

        result = send_message(
            ws,
            2137,
            {
                "ctidTraderAccountId": ACCOUNT_ID,
                "symbolId": symbol_id,
                "period": "M1",
                "count": count
            }
        )

        if result.get("payloadType") != 2138:

            raise RuntimeError(
                "Market data request failed: "
                + str(result)
            )

        bars = (
            result.get("payload", {})
            .get("trendbar", [])
        )

        candles = []

        for bar in bars:

            low = bar.get("low")

            if low is None:
                continue

            open_price = bar.get(
                "open",
                low
            )

            close_price = bar.get(
                "close",
                low
            )

            high_price = bar.get(
                "high",
                close_price
            )

            candles.append({
                "time": bar.get(
                    "utcTimestampInMinutes",
                    0
                ),
                "open": open_price,
                "high": high_price,
                "low": low,
                "close": close_price,
                "volume": bar.get(
                    "volume",
                    0
                )
            })

        if not candles:

            raise RuntimeError(
                "No candles returned"
            )

        prices = [
            candle["close"]
            for candle in candles
        ]

        return {
            "success": True,
            "account_id": ACCOUNT_ID,
            "symbol": symbol,
            "symbol_id": symbol_id,
            "period": "M1",
            "count": len(candles),
            "candles": candles,
            "prices": prices
        }

    finally:

        if ws:

            try:
                ws.close()
            except Exception:
                pass


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def send_telegram_message(
    text,
    buttons=None
):

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
            "Telegram error: "
            + str(data)
        )

    return data


# ============================================================
# EXECUTE TRADE
# ============================================================

def execute_trade(trade):

    ws = None

    try:

        ws = authenticate()

        symbol_id = find_symbol_id(
            ws,
            trade["symbol"]
        )

        # BUY = 1
        # SELL = 2

        if trade["signal"] == "BUY":

            trade_side = 1

        else:

            trade_side = 2

        volume = int(
            trade["volume"]
        )

        if volume <= 0:

            raise ValueError(
                "Volume must be greater than zero"
            )

        # ----------------------------------------------------
        # MARKET ORDER
        # ----------------------------------------------------

        payload = {
            "ctidTraderAccountId": ACCOUNT_ID,
            "symbolId": symbol_id,
            "orderType": 1,
            "tradeSide": trade_side,
            "volume": volume,
            "label": "ForexBot_v3.2",
            "comment": "Telegram approved demo trade"
        }

        # ----------------------------------------------------
        # STOP LOSS
        # ----------------------------------------------------

        if trade.get("stop_loss") is not None:

            payload["stopLoss"] = float(
                trade["stop_loss"]
            )

        # ----------------------------------------------------
        # TAKE PROFIT
        # ----------------------------------------------------

        if trade.get("take_profit") is not None:

            payload["takeProfit"] = float(
                trade["take_profit"]
            )

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


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return jsonify({
        "service": "ForexBot cTrader Relay",
        "status": "online",
        "version": "3.3",
        "execution_enabled": EXECUTION_ENABLED,
        "telegram_enabled": bool(
            TELEGRAM_BOT_TOKEN
            and TELEGRAM_CHAT_ID
        )
    })


# ============================================================
# HEALTH
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "healthy"
    })


# ============================================================
# CREDENTIAL CHECK
# ============================================================

@app.route("/credentials")
def credentials():

    return jsonify({

        "client_id_loaded": bool(
            CLIENT_ID
        ),

        "client_secret_loaded": bool(
            CLIENT_SECRET
        ),

        "access_token_loaded": bool(
            ACCESS_TOKEN
        ),

        "account_id_loaded": bool(
            ACCOUNT_ID
        ),

        "telegram_token_loaded": bool(
            TELEGRAM_BOT_TOKEN
        ),

        "telegram_chat_id_loaded": bool(
            TELEGRAM_CHAT_ID
        ),

        "execution_enabled":
            EXECUTION_ENABLED
    })


# ============================================================
# ACCOUNT
# ============================================================

@app.route("/account")
def account():

    try:

        ws = authenticate()

        ws.close()

        return jsonify({
            "success": True,
            "message":
                "cTrader demo account authenticated",
            "account_id": ACCOUNT_ID
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": type(e).__name__,
            "details": str(e)
        }), 502


# ============================================================
# MARKET
# ============================================================

@app.route("/market")
def market():

    symbol = request.args.get(
        "symbol",
        "EURUSD"
    )

    try:

        count = int(
            request.args.get(
                "count",
                "250"
            )
        )

    except ValueError:

        return jsonify({
            "success": False,
            "error":
                "count must be an integer"
        }), 400

    if count < 1:
        count = 1

    if count > 1000:
        count = 1000

    try:

        result = get_market_data(
            symbol,
            count
        )

        return jsonify(result)

    except Exception as e:

        return jsonify({
            "success": False,
            "error": type(e).__name__,
            "details": str(e)
        }), 502


# ============================================================
# TRADE REQUEST
# ============================================================

@app.route(
    "/trade",
    methods=["POST"]
)
def trade():

    data = request.get_json(
        silent=True
    ) or {}

    symbol = data.get(
        "symbol",
        "EURUSD"
    )

    signal = data.get(
        "signal"
    )

    volume = data.get(
        "volume"
    )

    stop_loss = data.get(
        "stop_loss"
    )

    take_profit = data.get(
        "take_profit"
    )

    # --------------------------------------------------------
    # VALIDATE SIGNAL
    # --------------------------------------------------------

    if signal not in (
        "BUY",
        "SELL"
    ):

        return jsonify({
            "success": False,
            "error":
                "Signal must be BUY or SELL"
        }), 400

    # --------------------------------------------------------
    # VALIDATE VOLUME
    # --------------------------------------------------------

    if volume is None:

        return jsonify({
            "success": False,
            "error":
                "Volume is required"
        }), 400

    try:

        volume = int(volume)

    except (TypeError, ValueError):

        return jsonify({
            "success": False,
            "error":
                "Volume must be an integer"
        }), 400

    if volume <= 0:

        return jsonify({
            "success": False,
            "error":
                "Volume must be greater than zero"
        }), 400

    # --------------------------------------------------------
    # EXECUTION CHECK
    # --------------------------------------------------------

    if not EXECUTION_ENABLED:

        return jsonify({
            "success": True,
            "status": "READY",
            "message":
                "Execution is disabled.",
            "execution_enabled": False
        })

    # --------------------------------------------------------
    # TELEGRAM CHECK
    # --------------------------------------------------------

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        return jsonify({
            "success": False,
            "error":
                "Telegram approval system is not configured"
        }), 500

    # --------------------------------------------------------
    # CREATE REQUEST
    # --------------------------------------------------------

    request_id = str(
        uuid.uuid4()
    )

    pending_trades[request_id] = {

        "symbol": symbol,

        "signal": signal,

        "volume": volume,

        "stop_loss": stop_loss,

        "take_profit": take_profit,

        "created": time.time()
    }

    # --------------------------------------------------------
    # CALCULATE LOT SIZE
    # --------------------------------------------------------

    lot_size = volume_to_lots(
        volume
    )

    # --------------------------------------------------------
    # TELEGRAM NOTIFICATION
    # --------------------------------------------------------

    text = (

        "🚨 FOREXBOT TRADE REQUEST\n\n"

        f"Symbol: {symbol}\n"

        f"Signal: {signal}\n"

        f"Volume: {volume}\n"

        f"Lot Size: {lot_size:.2f}\n"

        f"Stop Loss: {stop_loss}\n"

        f"Take Profit: {take_profit}\n\n"

        f"Request: {request_id}\n\n"

        "Approve this demo trade?"
    )

    buttons = [

        {
            "text": "✅ APPROVE",
            "callback_data":
                "approve:" + request_id
        },

        {
            "text": "❌ REJECT",
            "callback_data":
                "reject:" + request_id
        }
    ]

    try:

        send_telegram_message(
            text,
            buttons
        )

        return jsonify({

            "success": True,

            "status":
                "PENDING_APPROVAL",

            "message":
                "Telegram approval requested",

            "request_id":
                request_id,

            "volume":
                volume,

            "lot_size":
                lot_size
        })

    except Exception as e:

        pending_trades.pop(
            request_id,
            None
        )

        return jsonify({

            "success": False,

            "error":
                type(e).__name__,

            "details":
                str(e)
        }), 502


# ============================================================
# TELEGRAM WEBHOOK
# ============================================================

@app.route(
    "/telegram",
    methods=["POST"]
)
def telegram():

    update = request.get_json(
        silent=True
    ) or {}

    callback = update.get(
        "callback_query"
    )

    # Normal Telegram messages
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

    # --------------------------------------------------------
    # SECURITY CHECK
    # --------------------------------------------------------

    if callback_chat != str(
        TELEGRAM_CHAT_ID
    ):

        return jsonify({

            "success": False,

            "error":
                "Unauthorized Telegram chat"

        }), 403

    if ":" not in callback_data:

        return jsonify({

            "success": False,

            "error":
                "Invalid callback"

        }), 400

    action, request_id = (
        callback_data.split(
            ":",
            1
        )
    )

    trade = pending_trades.get(
        request_id
    )

    if not trade:

        answer_callback(

            callback_id,

            "Trade request no longer exists."
        )

        return jsonify({

            "success": True,

            "message":
                "Trade request no longer exists"
        })

    # --------------------------------------------------------
    # TIMEOUT
    # --------------------------------------------------------

    if (
        time.time()
        - trade["created"]
        > APPROVAL_TIMEOUT
    ):

        pending_trades.pop(
            request_id,
            None
        )

        answer_callback(

            callback_id,

            "Trade request expired."
        )

        send_telegram_message(

            "⏱️ TRADE REQUEST EXPIRED\n\n"

            f"{trade['symbol']} "
            f"{trade['signal']}"
        )

        return jsonify({
            "success": True,
            "status": "EXPIRED"
        })

    # --------------------------------------------------------
    # REJECT
    # --------------------------------------------------------

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

            "❌ TRADE REJECTED\n\n"

            f"{trade['symbol']} "
            f"{trade['signal']}\n"

            f"Volume: "
            f"{trade['volume']}\n"

            f"Lot Size: "
            f"{volume_to_lots(trade['volume']):.2f}"
        )

        return jsonify({

            "success": True,

            "status":
                "REJECTED"
        })

    # --------------------------------------------------------
    # APPROVE
    # --------------------------------------------------------

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

                f"{trade['symbol']} "
                f"{trade['signal']}\n"

                f"Volume: "
                f"{trade['volume']}\n"

                f"Lot Size: "
                f"{volume_to_lots(trade['volume']):.2f}\n\n"

                f"Stop Loss: "
                f"{trade['stop_loss']}\n"

                f"Take Profit: "
                f"{trade['take_profit']}\n\n"

                "cTrader response:\n"

                + str(result)
            )

            return jsonify({

                "success": True,

                "status":
                    "EXECUTED",

                "ctrader_response":
                    result
            })

        except Exception as e:

            answer_callback(

                callback_id,

                "Trade execution failed."
            )

            try:

                send_telegram_message(

                    "⚠️ TRADE EXECUTION FAILED\n\n"

                    + type(e).__name__

                    + ": "

                    + str(e)
                )

            except Exception:
                pass

            return jsonify({

                "success": False,

                "status":
                    "EXECUTION_FAILED",

                "error":
                    type(e).__name__,

                "details":
                    str(e)

            }), 502

    # --------------------------------------------------------
    # UNKNOWN ACTION
    # --------------------------------------------------------

    return jsonify({

        "success": False,

        "error":
            "Unknown action"

    }), 400


# ============================================================
# TELEGRAM CALLBACK ANSWER
# ============================================================

def answer_callback(
    callback_id,
    text
):

    if not TELEGRAM_BOT_TOKEN:
        return

    url = (

        "https://api.telegram.org/bot"

        + TELEGRAM_BOT_TOKEN

        + "/answerCallbackQuery"
    )

    try:

        requests.post(

            url,

            json={

                "callback_query_id":
                    callback_id,

                "text":
                    text

            },

            timeout=15
        )

    except Exception:
        pass


# ============================================================
# START SERVER
# ============================================================

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
