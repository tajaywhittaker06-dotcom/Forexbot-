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


def send_message(ws, payload_type, payload):
    message = {
        "clientMsgId": str(uuid.uuid4()),
        "payloadType": payload_type,
        "payload": payload
    }

    ws.send(json.dumps(message))
    return json.loads(ws.recv())


def get_market_data(symbol, count):
    ws = None

    try:
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

        # Get symbol information
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

        symbols = result.get(
            "payload",
            {}
        ).get(
            "symbol",
            []
        )

        symbol_id = None

        for item in symbols:
            if item.get("symbolName") == symbol:
                symbol_id = item.get("symbolId")
                break

        if symbol_id is None:
            raise RuntimeError(
                f"Symbol not found: {symbol}"
            )

        # Request M1 trendbars
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

        payload = result.get(
            "payload",
            {}
        )

        bars = payload.get(
            "trendbar",
            []
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

            # cTrader trendbar prices are relative/integer
            # values and need to be converted to EURUSD prices.
            open_price = open_price / PRICE_SCALE
            high_price = high_price / PRICE_SCALE
            low_price = low / PRICE_SCALE
            close_price = close_price / PRICE_SCALE

            candles.append({
                "time": bar.get(
                    "utcTimestampInMinutes",
                    0
                ),
                "open": open_price,
                "high": high_price,
                "low": low_price,
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


@app.route("/")
def home():

    return jsonify({
        "service": "ForexBot cTrader Relay",
        "status": "online",
        "version": "2.7"
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

    if count < 1:
        return jsonify({
            "success": False,
            "error": "count must be greater than 0"
        }), 400

    if count > 500:
        count = 500

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

    # Execution remains disabled for now.
    # This endpoint only validates the request.
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
