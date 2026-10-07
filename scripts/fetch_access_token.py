import os
import pyotp
import requests
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from kiteconnect import KiteConnect
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
TOTP_KEY = os.getenv("TOTP_KEY")
USER_ID = os.getenv("USER_ID")
USER_PASSWORD = os.getenv("USER_PASSWORD")

ACCESS_TOKEN_FILE = "access_token.txt"
BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN_DIR = BASE_DIR / "data" / "auth"
TOKEN_PATH = TOKEN_DIR / ACCESS_TOKEN_FILE

LOGIN_URL = "https://kite.zerodha.com/api/login"
TWOFA_URL = "https://kite.zerodha.com/api/twofa"

AUTH_URL = (
    "https://kite.zerodha.com/connect/login?" +
    urlencode({
        "v": "3",
        "api_key": API_KEY,
    })
)

MAX_REDIRECTS = 10

def get_request_token(session):
    login_res = session.post(LOGIN_URL, data={
        "user_id": USER_ID,
        "password": USER_PASSWORD
    }, timeout=30).json()
    
    session.post(TWOFA_URL, data={
        "request_id": login_res["data"]["request_id"],
        "twofa_value": pyotp.TOTP(TOTP_KEY).now(),
        "user_id": login_res["data"]["user_id"]
    }, timeout=30)
    
    res = session.get(AUTH_URL, allow_redirects=False, timeout=30)
    
    for _ in range(MAX_REDIRECTS):
        location = res.headers.get('Location', '')
        if 'request_token' in location:
            break
        if not location:
            raise RuntimeError("Login redirect chain broke before a request_token was issued")
        res = session.get(location, allow_redirects=False, timeout=30)
    else:
        raise RuntimeError(f"Did not receive request_token within {MAX_REDIRECTS} redirects")
    
    return parse_qs(urlparse(res.headers['Location']).query)['request_token'][0]

def get_access_token(request_token):
    kite = KiteConnect(api_key=API_KEY)
    return kite.generate_session(request_token, api_secret=API_SECRET)["access_token"]

def save_access_token(token):
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        f.write(token)

def login():
    session = requests.Session()
    request_token = get_request_token(session)
    access_token = get_access_token(request_token)
    save_access_token(access_token)
    return access_token

def main():
    try:
        login()
        relative_path = Path("/") / TOKEN_PATH.relative_to(BASE_DIR.parent)
        print(f"Access token fetched and stored successfully at {relative_path}")
    except Exception as e:
        print(f"Error | {e}")

if __name__ == "__main__":
    main()
