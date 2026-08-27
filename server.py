import os
import json
import uuid
import time
import websocket

from flask import Flask, jsonify, request

app = Flask(__name__)

CTRADER_HOST = "wss://demo.ctraderapi.com:5036"

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")


def send_message(ws, payload_type, payload):
    message = {
        "clientMsgId": str(uuid.uuid4()),
        "payloadType": payload_type,
        "payload": payload
    }

    ws.send(json.dumps(message))

    return json.loads(ws.recv())


def connect_and_authenticate():
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
        ws.close()
        raise RuntimeError(
            "Application authentication failed: "
            + str(result)
        )

    # Get accounts
    result = send_message(
        ws,
        2149,
        {
            "accessToken": ACCESS_TOKEN
        }
    )

    if result.get("payloadType") != 2150:
        ws.close()
        raise RuntimeError(
            "Account list request failed: "
            + str(result)
        )

    accounts = result.get("payload", {}).get(
        "ctidTraderAccount",
        []
    )

    if not accounts:
        ws.close()
        raise RuntimeError("No cTrader accounts found")

    account_id = accounts[0]["ctidTraderAccountId"]

    # Authenticate account
    result = send_message(
        ws,
        2102,
        {
            "ctidTraderAccountId": account_id,
            "accessToken": ACCESS_TOKEN
        }
    )

    if result.get("payloadType") != 2103:
        ws.close()
        raise RuntimeError(
            "Account authentication failed: "
            + str(result)
        )

    return ws, account_id


def find_symbol(ws, account_id, symbol_name):
    result = send_message(
        ws,
        2114,
        {
            "ctidTraderAccountId": account_id,
            "includeArchivedSymbols": False
        }
    )

    if result.get("payloadType") != 2115:
        raise RuntimeError(
            "Symbol list request failed: "
            + str(result)
        )

    symbols = result.get("payload", {}).get(
        "symbol",
        []
    )

    target = symbol_name.upper()

    for symbol in symbols:
        name = str(symbol.get("symbolName", "")).upper()

        if name == target:
            return symbol

    for symbol in symbols:
        name = str(symbol.get("symbolName", "")).upper()

        if target in name or name in target:
            return symbol

    raise RuntimeError(
        "Symbol not found: " + symbol_name
    )


def get_trendbars(
    ws,
    account_id,
    symbol_id,
    count=200
):
    now_ms = int(time.time() * 1000)

    result = send_message(
        ws,
        2137,
        {
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_id,
            "period": 1,
            "count": count,
            "toTimestamp": now_ms
        }
    )

    if result.get("payloadType") != 2138:
        raise RuntimeError(
            "Trendbar request failed: "
            + str(result)
        )

    trendbars = result.get("payload", {}).get(
        "trendbar",
        []
    )

    candles = []

    for bar in trendbars:
        low_raw = bar.get("low", 0)

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
            ) * 60,
            "open": round(open_raw / 100000, 5),
            "high": round(high_raw / 100000, 5),
            "low": round(low_raw / 100000, 5),
            "close": round(close_raw / 100000, 5),
            "volume": bar.get("volume", 0)
        })

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "service": "ForexBot cTrader Relay",
        "version": "2.4"
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
        "access_token_loaded": bool(ACCESS_TOKEN)
    })


@app.route("/account")
def account():
    ws = None

    try:
        ws, account_id = connect_and_authenticate()

        return jsonify({
            "success": True,
            "message": "cTrader account authenticated",
            "account_id": account_id
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": type(e).__name__,
            "details": str(e)
        }), 502

    finally:
        if ws:
            ws.close()


@app.route("/market")
def market():
    ws = None

    try:
        symbol_name = request.args.get(
            "symbol",
            "EURUSD"
        )

        count = int(
            request.args.get(
                "count",
                "200"
            )
        )

        count = max(10, min(count, 500))

        ws, account_id = connect_and_authenticate()

        symbol = find_symbol(
            ws,
            account_id,
            symbol_name
        )

        symbol_id = symbol.get("symbolId")

        candles = get_trendbars(
            ws,
            account_id,
            symbol_id,
            count
        )

        if not candles:
            raise RuntimeError(
                "No trendbars returned"
            )

        return jsonify({
            "success": True,
            "account_id": account_id,
            "symbol": symbol.get(
                "symbolName",
                symbol_name
            ),
            "symbol_id": symbol_id,
            "period": "M1",
            "count": len(candles),
            "candles": candles
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": type(e).__name__,
            "details": str(e)
        }), 502

    finally:
        if ws:
            ws.close()


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
