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
        raise RuntimeError(
            "Application authentication failed: "
            + str(result)
        )

    # Get accounts associated with access token
    result = send_message(
        ws,
        2149,
        {
            "accessToken": ACCESS_TOKEN
        }
    )

    if result.get("payloadType") != 2150:
        raise RuntimeError(
            "Account list request failed: "
            + str(result)
        )

    accounts = result.get("payload", {}).get(
        "ctidTraderAccount", []
    )

    if not accounts:
        raise RuntimeError("No cTrader accounts found")

    account_id = accounts[0]["ctidTraderAccountId"]

    # Authenticate the selected account
    result = send_message(
        ws,
        2102,
        {
            "ctidTraderAccountId": account_id,
            "accessToken": ACCESS_TOKEN
        }
    )

    if result.get("payloadType") != 2103:
        raise RuntimeError(
            "Account authentication failed: "
            + str(result)
        )

    return ws, account_id


@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "service": "ForexBot cTrader Relay",
        "version": "2.2"
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
            try:
                ws.close()
            except Exception:
                pass


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
