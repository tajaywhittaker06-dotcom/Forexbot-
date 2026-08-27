import os
import json
import uuid
import websocket

from flask import Flask, jsonify

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
    response = ws.recv()

    return json.loads(response)


def connect():
    if not CLIENT_ID:
        raise RuntimeError("CTRADER_CLIENT_ID is missing")

    if not CLIENT_SECRET:
        raise RuntimeError("CTRADER_CLIENT_SECRET is missing")

    if not ACCESS_TOKEN:
        raise RuntimeError("CTRADER_ACCESS_TOKEN is missing")

    ws = websocket.create_connection(
        CTRADER_HOST,
        timeout=15
    )

    # 1. Authenticate the application
    app_auth = send_message(
        ws,
        2100,
        {
            "clientId": CLIENT_ID,
            "clientSecret": CLIENT_SECRET
        }
    )

    if app_auth.get("payload", {}).get("errorCode"):
        ws.close()
        raise RuntimeError(
            "Application authentication failed: "
            + str(app_auth)
        )

    # 2. Request accounts belonging to this access token
    accounts = send_message(
        ws,
        2149,
        {
            "accessToken": ACCESS_TOKEN
        }
    )

    return ws, accounts


@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "service": "ForexBot cTrader Relay",
        "version": "2.1"
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
        ws, result = connect()

        payload = result.get("payload", {})

        if result.get("payloadType") != 2141:
            return jsonify({
                "success": False,
                "stage": "account_list",
                "ctrader_response": result
            }), 502

        accounts = payload.get("ctidTraderAccount")

        if not accounts:
            return jsonify({
                "success": False,
                "message": "No cTrader accounts were returned.",
                "ctrader_response": result
            }), 502

        # Only return safe account information.
        safe_accounts = []

        for account in accounts:
            safe_accounts.append({
                "ctidTraderAccountId": account.get(
                    "ctidTraderAccountId"
                ),
                "isLive": account.get("isLive"),
                "brokerTitleShort": account.get(
                    "brokerTitleShort"
                ),
                "traderLogin": account.get(
                    "traderLogin"
                )
            })

        return jsonify({
            "success": True,
            "message": "cTrader accounts found",
            "accounts": safe_accounts
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": type(e).__name__,
            "details": str(e)
        }), 502

    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port
    )
