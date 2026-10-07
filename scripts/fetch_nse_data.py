import json
import time
import requests
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = "symbols.json"
INPUT_PATH = BASE_DIR / "data" / "symbols" / INPUT_FILE
OUTPUT_DIR = BASE_DIR / "data" / "nse" / "json"

START_DATE = date(2021, 1, 1)
CHUNK_DAYS = 90

API_URL = (
    "https://www.nseindia.com/api/historicalOR/generateSecurityWiseHistoricalData"
    "?from={from_date}&to={to_date}&symbol={symbol}&type=priceVolumeDeliverable&series=EQ"
)

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "referer": "https://www.nseindia.com/report-detail/eq_security",
    "user-agent": (
        "Mozilla/5.0 (Linux; Android 15; Pixel 9) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Mobile Safari/537.36"
    )
}

def read_symbols(path):
    with open(path) as f:
        data = json.load(f)
        return [symbol.strip() for symbol in data.keys() if symbol and symbol.strip()]

def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get("https://www.nseindia.com", timeout=10)
    time.sleep(1)
    return session

def date_chunks(start, end, days):
    chunks = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=days - 1), end)
        chunks.append((current.strftime("%d-%m-%Y"), chunk_end.strftime("%d-%m-%Y")))
        current = chunk_end + timedelta(days=1)
    return chunks

def fetch_symbol(session, symbol, max_retries=3):
    all_records = []
    end_date = date.today() - timedelta(days=1)
    for from_date, to_date in date_chunks(START_DATE, end_date, CHUNK_DAYS):
        url = API_URL.format(symbol=symbol, from_date=from_date, to_date=to_date)
        
        for attempt in range(max_retries):
            try:
                response = session.get(url, timeout=15)
                response.raise_for_status()
                records = response.json().get("data", [])
                all_records.extend(records)
                break
            except (requests.HTTPError, requests.ConnectionError, ValueError) as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise
        
        time.sleep(0.5)
    return {"data": all_records}

def save_json(data, path):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def main():
    try:
        symbols = read_symbols(INPUT_PATH)
        total = len(symbols)
        width = len(str(total))
        
        print(f"Found {total} symbols") 
        relative_path = Path("/") / OUTPUT_DIR.relative_to(BASE_DIR.parent)
        print(f"Output directory: {relative_path}")
        print(f"\nDownloading data ...\n")
        
        session = get_session()
        success = 0
        
        for i, symbol in enumerate(symbols, start=1):
            if i % 50 == 1 and i > 1:
                print(f"\nRefreshing session ...\n")
                session = get_session()
            
            output_path = OUTPUT_DIR / f"{symbol}.json"
            label = f"[{i:0{width}}/{total}]  {symbol:<12}"
            
            try:
                data = fetch_symbol(session, symbol)
                save_json(data, output_path)
                count = len(data.get("data", []))
                print(f"{label}->  {count} records")
                success += 1
            except Exception:
                try:
                    session = get_session()
                    data = fetch_symbol(session, symbol)
                    save_json(data, output_path)
                    count = len(data.get("data", []))
                    print(f"{label}->  {count} records (retry)")
                    success += 1
                except Exception:
                    print(f"{label}->  Error")
            
            time.sleep(1)
        
        print(f"\nSuccessfully downloaded and saved data for {success}/{total} symbols")
    
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")

if __name__ == "__main__":
    main()
