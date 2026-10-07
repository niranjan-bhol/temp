import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")

BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN_FILE = "access_token.txt"
TOKEN_DIR = BASE_DIR / "data" / "auth"
TOKEN_PATH = TOKEN_DIR / TOKEN_FILE
OUTPUT_FILE = "instruments.csv"
OUTPUT_DIR = BASE_DIR / "data" / "instruments"
OUTPUT_PATH = OUTPUT_DIR / OUTPUT_FILE

INSTRUMENTS_URL = "https://api.kite.trade/instruments"

def read_access_token():
    with open(TOKEN_PATH, "r") as f:
        return f.read().strip()

def download_instruments():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    token = read_access_token()
    response = requests.get(INSTRUMENTS_URL, headers={
        "Authorization": f"token {API_KEY}:{token}",
        "X-Kite-Version": "3"
    }, timeout=30)
    response.raise_for_status()
    
    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        file.write(response.text)
    
    relative_output = Path("/") / OUTPUT_PATH.relative_to(BASE_DIR.parent)
    print(f"Downloaded instruments to {relative_output}")

def main():
    try:
        download_instruments()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
