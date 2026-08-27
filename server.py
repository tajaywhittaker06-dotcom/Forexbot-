import os
import json
import time
import uuid
import requests
from flask import Flask, jsonify

app = Flask(__name__)

CTRADER_HOST = "https://demo.ctraderapi.com:5036"

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")


@app.route("/")
def home():
    return jsonify({
        "service": "ForexBot cTrader Relay",
        "status": "online",
        "version": "1.1"
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
    if not CLIENT_ID or not CLIENT_SECRET or not ACCESS_TOKEN:
        return jsonify({
            "success": False,
            "error": "Missing cTrader credentials"
        }), 500

    try:
        # Authenticate the application first.
        app_auth = {
            "clientMsgId": str(uuid.uuid4()),
            "payloadType": 2100,
            "payload": {
                "clientId": CLIENT_ID,
                "clientSecret": CLIENT_SECRET
            }
        }

        response = requests.post(
            CTRADER_HOST,
            json=app_auth,
            timeout=15
        )

        if response.status_code != 200:
            return jsonify({
                "success": False,
                "stage": "application_auth",
                "status_code": response.status_code,
                "response": response.text[:1000]
            }), 502

        auth_result = response.json()

        # Authenticate the trading account.
        account_auth = {
            "clientMsgId": str(uuid.uuid4()),
            "payloadType": 2102,
            "payload": {
                "accessToken": ACCESS_TOKEN
            }
        }

        response = requests.post(
            CTRADER_HOST,
            json=account_auth,
            timeout=15
        )

        if response.status_code != 200:
            return jsonify({
                "success": False,
                "stage": "account_auth",
                "status_code": response.status_code,
                "response": response.text[:1000]
            }), 502

        result = response.json()

        return jsonify({
            "success": True,
            "message": "cTrader account authentication request completed",
            "response": result
        })

    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "error": "Could not reach cTrader API",
            "details": str(e)
        }), 502

    except Exception as e:
        return jsonify({
            "success": False,
            "error": type(e).__name__,
            "details": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
