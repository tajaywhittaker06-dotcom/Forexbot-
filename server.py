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


def connect_ctrader():
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

    # Application authentication
    app_result = send_message(
        ws,
        2100,
        {
            "clientId": CLIENT_ID,
            "clientSecret": CLIENT_SECRET
        }
    )

    if app_result.get("errorCode"):
        ws.close()
        raise RuntimeError(
            "Application authentication failed: "
            + str(app_result)
        )

    # Account authentication
    account_result = send_message(
        ws,
        2102,
        {
            "accessToken": ACCESS_TOKEN
        }
    )

    return ws, account_result


@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "service": "ForexBot cTrader Relay",
        "version": "2.0"
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
        ws, result = connect_ctrader()

        return jsonify({
            "success": True,
            "message": "cTrader authentication successful",
            "ctrader_response": result
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
