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

# SAFETY SWITCH
# Keep this FALSE while testing.
EXECUTION_ENABLED = (
    os.getenv("CTRADER_EXECUTION_ENABLED", "false").lower()
    == "true"
)

PRICE_SCALE = 100000


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
            "Application authentication failed: "
            + str(result)
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
            "Account authentication failed: "
            + str(result)
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
                "Market data request failed: "
                + str(result)
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

            # cTrader trendbars use:
            # open = low + deltaOpen
            # close = low + deltaClose
            # high = low + deltaHigh

            open_raw = (
                low_raw
                + bar.get("deltaOpen", 0)
            )

            close_raw = (
                low_raw
                + bar.get("deltaClose", 0)
            )

            high_raw = (
                low_raw
                + bar.get("deltaHigh", 0)
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
    stop
