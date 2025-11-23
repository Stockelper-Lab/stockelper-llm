import os
from dotenv import load_dotenv
from typing import Dict, Any, List
import requests

load_dotenv(override=True)

APP_KEY = os.getenv("APP_KEY")
APP_SECRET = os.getenv("APP_SECRET")


def get_access_token() -> Dict[str, Any]:
    url = "https://openapivts.koreainvestment.com:29443/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
    }
    try:
        response = requests.post(url, headers=headers, json=body)
        return response.json()["access_token"]
    except Exception as e:
        print(response.text)


if __name__ == "__main__":
    print(get_access_token())
