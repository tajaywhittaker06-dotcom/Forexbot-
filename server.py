import os
import json
import uuid
import websocket

from flask import Flask, jsonify, request

app = Flask(__name__)

CTRADER_HOST = "wss://demo.ctraderapi.com:5036"

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = int(os.getenv("CTRADER_ACCOUNT_ID", "0"))

PRICE_SCALE = 100000

EXECUTION_ENABLED = (
    os.getenv("CTRADER_EXECUTION_ENABLED", "false").lower() == "true"
)


def send_message(ws, payload_type, payload):
    message = {
        "clientMsgId": str(uuid.uuid4()),
        "payloadType": payload_type,
        "payload": payload
    }

    ws.send(json.dumps(message))
    return json.loads(ws.recv())


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
            "Application authentication failed: " + str(result)
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
            "Account authentication failed: " + str(result)
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
            "Symbol request failed: " + str(result)
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
                "Market data request failed: " + str(result)
            )

        bars = result.get(
            "payload",
            {}
        ).get(
            "trendbar",
            []
        )

        candles = []

        for bar in bars:
            low_raw = bar.get("low")

            if low_raw is None:
                continue

            open_raw = low_raw + bar.get(
                "deltaOpen",
                0
            )

            close_raw = low_raw + bar.get(
                "deltaClose",
                0
            )

            high_raw = low_raw + bar.get(
                "deltaHigh",
                0
            )

            candles.append({
                "time": bar.get(
                    "utcTimestampInMinutes",
                    0
                ),
                "open": open_raw / PRICE_SCALE,
                "high": high_raw / PRICE_SCALE,
                "low": low_raw / PRICE_SCALE,
                "close": close_raw / PRICE_SCALE,
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


def place_demo_order(
    symbol,
    signal,
    volume,
    stop_loss,
    take_profit
):
    ws = None

    try:
        ws = authenticate()

        symbol_id = find_symbol_id(
            ws,
            symbol
        )

        if signal == "BUY":
            trade_side = 1
        elif signal == "SELL":
            trade_side = 2
        else:
            raise ValueError(
                "Signal must be BUY or SELL"
            )

        protocol_volume = int(volume)

        if protocol_volume <= 0:
            raise ValueError(
                "Volume must be greater than zero"
            )

        payload = {
            "ctidTraderAccountId": ACCOUNT_ID,
            "symbolId": symbol_id,
            "orderType": 1,
            "tradeSide": trade_side,
            "volume": protocol_volume,
            "label": "ForexBot_v3.2",
            "comment": "ForexBot demo trade"
        }

        result = send_message(
            ws,
            2106,
            payload
        )

        return {
            "success": True,
            "account_id": ACCOUNT_ID,
            "symbol": symbol,
            "symbol_id": symbol_id,
            "signal": signal,
            "volume": protocol_volume,
            "ctrader_response": result
        }

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
        "version": "3.0",
        "execution_enabled": EXECUTION_ENABLED
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
            "error": "count must be an integer"
        }), 400

    count = max(1, min(count, 500))

    try:
        return jsonify(
            get_market_data(
                symbol,
                count
            )
        )

    except Exception as e:
        return jsonify({
            "success": False,
            "error": type(e).__name__,
            "details": str(e)
        }), 502


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
            "execution_enabled": False,
            "account_id": ACCOUNT_ID,
            "symbol": symbol,
            "signal": signal,
            "volume": volume,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "request_id": str(uuid.uuid4())
        })

    try:
        result = place_demo_order(
            symbol,
            signal,
            volume,
            stop_loss,
            take_profit
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "success": False,
            "error": type(e).__name__,
            "details": str(e)
        }), 502


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
