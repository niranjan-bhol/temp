import os
import json
import argparse
import requests
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")

BASE_DIR = Path(__file__).resolve().parent.parent
ACCESS_TOKEN_FILE = "access_token.txt"
TOKEN_PATH = BASE_DIR / "data" / "auth" / ACCESS_TOKEN_FILE
SYMBOLS_FILE = "symbols.json"
SYMBOLS_PATH = BASE_DIR / "data" / "symbols" / SYMBOLS_FILE
OUTPUT_DIR = BASE_DIR / "data" / "historical" / "json"

INPUT_FILE = "symbols.json"
INPUT_PATH = BASE_DIR / "data" / "symbols" / INPUT_FILE

API_BASE_URL = "https://api.kite.trade/instruments/historical"

START_DATE = "2021-01-01"

INTERVAL_CHOICES = [
    "minute", "3minute", "5minute", "10minute",
    "15minute", "30minute", "60minute", "day"
]

MAX_DAYS = {
    "minute": 60,
    "3minute": 100,
    "5minute": 100,
    "10minute": 100,
    "15minute": 200,
    "30minute": 200,
    "60minute": 400,
    "day": 2000
}

def load_access_token():
    with open(TOKEN_PATH, "r") as f:
        return f.read().strip()

def load_symbols():
    with open(SYMBOLS_PATH, "r") as f:
        return json.load(f)

def setup_output_directory():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    for file in OUTPUT_DIR.glob("*.json"):
        file.unlink()

def parse_arguments():
    parser = argparse.ArgumentParser(description='Fetch historical data from Kite API')
    parser.add_argument('--interval', type=str, required=True,
                        choices=INTERVAL_CHOICES,
                        help='Candle interval')
    
    args = parser.parse_args()
    
    return args.interval

def generate_date_chunks(start_date_str, end_date_str, max_days):
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    
    chunk_delta = timedelta(days=max_days)
    chunks = []
    current_start = start_date
    
    while current_start <= end_date:
        current_end = min(current_start + chunk_delta - timedelta(days=1), end_date)
        
        chunks.append((
            current_start.strftime("%Y-%m-%d"),
            current_end.strftime("%Y-%m-%d")
        ))
        
        current_start = current_end + timedelta(days=1)
    
    return chunks

def fetch_historical_data(instrument_token, interval, from_date, to_date, access_token):
    url = f"{API_BASE_URL}/{instrument_token}/{interval}"
    
    headers = {
        "X-Kite-Version": "3",
        "Authorization": f"token {API_KEY}:{access_token}"
    }
    
    params = {
        "from": from_date,
        "to": to_date,
        "continuous": 0,
        "oi": 1
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error: {e}")
        return None

def merge_candle_data(chunks_data):
    all_candles = []
    
    for chunk_data in chunks_data:
        if chunk_data and chunk_data.get("status") == "success":
            candles = chunk_data.get("data", {}).get("candles", [])
            all_candles.extend(candles)
    
    unique_candles = {}
    for candle in all_candles:
        timestamp = candle[0]
        unique_candles[timestamp] = candle
    
    sorted_candles = sorted(unique_candles.values(), key=lambda x: x[0])
    
    return {
        "status": "success",
        "data": {
            "candles": sorted_candles
        }
    }

def process_symbol(symbol_name, instrument_token, interval, access_token, idx, total):
    print(f"\n[{idx}/{total}] {symbol_name}")
    print(f"  Instrument : {instrument_token}")
    
    end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"  Date range : {START_DATE} to {end_date}")
    
    date_chunks = generate_date_chunks(START_DATE, end_date, MAX_DAYS[interval])
    
    print(f"  Fetching data in {len(date_chunks)} chunks")
    
    chunks_data = []
    for chunk_idx, (chunk_from, chunk_to) in enumerate(date_chunks, 1):
        print(f"    Chunk {chunk_idx}/{len(date_chunks)}: {chunk_from} to {chunk_to}", end=" ")
        
        data = fetch_historical_data(
            instrument_token, interval,
            f"{chunk_from} 00:00:00", f"{chunk_to} 23:59:59",
            access_token
        )
        
        if data:
            candle_count = len(data.get("data", {}).get("candles", []))
            print(f"({candle_count:,} candles)")
            chunks_data.append(data)
    
    if len(chunks_data) > 1:
        print("  Merging chunks")
        final_data = merge_candle_data(chunks_data)
    elif len(chunks_data) == 1:
        final_data = chunks_data[0]
    else:
        print("  No data fetched")
        return False
    
    output_file = OUTPUT_DIR / f"{symbol_name}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_data, f, indent=2)
    
    total_candles = len(final_data.get("data", {}).get("candles", []))
    print(f"  Saved : {total_candles:,} total candles to {symbol_name}.json")
    
    return True

def main():
    try:
        access_token = load_access_token()
        symbols = load_symbols()
        
        interval = parse_arguments()
        
        setup_output_directory()
        
        relative_output = Path("/") / OUTPUT_DIR.relative_to(BASE_DIR.parent)
        print(f"Output directory: {relative_output}")
        
        success_count = 0
        total_symbols = len(symbols)
        
        for idx, (symbol_name, instrument_token) in enumerate(symbols.items(), 1):
            if process_symbol(symbol_name, instrument_token, interval, access_token, idx, total_symbols):
                success_count += 1
        
        print(f"\nSuccessfully downloaded data for {success_count}/{total_symbols} symbols")
    
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
