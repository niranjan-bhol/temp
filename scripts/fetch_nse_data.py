import json
import re
import time
import requests
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = BASE_DIR / "data" / "symbol" / "symbol.txt"
OUTPUT_DIR = BASE_DIR / "data" / "nse" / "json"
OUTPUT_DIR_PATH = f"{BASE_DIR.name}/{OUTPUT_DIR.relative_to(BASE_DIR)}"

START_DATE = date(2000, 1, 1)
END_DATE = date(2026, 9, 30)  # None = up to yesterday, or set e.g. date(2025, 12, 31)
CHUNK_DAYS = 90
CHUNK_RETRIES = 3
SYMBOL_RETRIES = 3
CHUNK_SLEEP = 0.3
MAX_WORKERS = 10
SESSION_REFRESH_EVERY = 50

API_URL = "https://www.nseindia.com/api/historicalOR/indicesHistory"

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "referer": "https://www.nseindia.com/reports-indices-historical-index-data",
    "user-agent": (
        "Mozilla/5.0 (Linux; Android 16; Pixel 10) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/155.0.0.0 Mobile Safari/537.36"
    )
}

def read_symbols(path):
    if not path.exists():
        raise FileNotFoundError(f"Symbol file not found")
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]

def sanitize_filename(symbol):
    return re.sub(r"[^A-Za-z0-9]+", "_", symbol).strip("_")

def clear_output_dir():
    if OUTPUT_DIR.exists():
        existing_files = list(OUTPUT_DIR.glob("*.json"))
        for file_path in existing_files:
            file_path.unlink()
        print(f"Output directory exists : {OUTPUT_DIR_PATH}")
        print(f"\nCleared output directory")
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Created output directory : {OUTPUT_DIR_PATH}")

def get_session(max_retries=3):
    for attempt in range(max_retries):
        try:
            session = requests.Session()
            session.headers.update(HEADERS)
            session.get("https://www.nseindia.com", timeout=10).raise_for_status()
            time.sleep(1)
            return session
        except requests.RequestException:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)

def date_chunks(start, end, days):
    chunks = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=days - 1), end)
        chunks.append((current.strftime("%d-%m-%Y"), chunk_end.strftime("%d-%m-%Y")))
        current = chunk_end + timedelta(days=1)
    return chunks

def fetch_chunk(session, params, chunk_retries):
    for attempt in range(chunk_retries):
        try:
            if attempt > 0:
                session = get_session()
            response = session.get(API_URL, params=params, timeout=15)
            response.raise_for_status()
            payload = response.json()
            if "data" not in payload:
                raise ValueError()
            return session, payload["data"]
        except (requests.RequestException, ValueError):
            if attempt == chunk_retries - 1:
                raise
            time.sleep(2 ** attempt)

def fetch_symbol(session, symbol, chunk_retries=CHUNK_RETRIES):
    all_records = []
    end_date = END_DATE or (date.today() - timedelta(days=1))
    for chunk_num, (from_date, to_date) in enumerate(date_chunks(START_DATE, end_date, CHUNK_DAYS), start=1):
        params = {
            "indexType": symbol,
            "from": from_date,
            "to": to_date,
        }

        if chunk_num % SESSION_REFRESH_EVERY == 0:
            session = get_session()

        session, records = fetch_chunk(session, params, chunk_retries)
        all_records.extend(records)

        time.sleep(CHUNK_SLEEP)
    return session, {"data": all_records}

def save_json(data, path):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

print_lock = threading.Lock()
progress = {"success": 0, "next_to_print": 1, "buffer": {}}

def emit(index, message):
    with print_lock:
        progress["buffer"][index] = message
        while progress["next_to_print"] in progress["buffer"]:
            print(progress["buffer"].pop(progress["next_to_print"]))
            progress["next_to_print"] += 1

def process_symbol(index, symbol, total, width, session):
    label = f"[{index:0{width}}/{total}]  {symbol:<32}"
    output_path = OUTPUT_DIR / f"{sanitize_filename(symbol)}.json"

    for attempt in range(SYMBOL_RETRIES):
        try:
            if attempt > 0:
                session = get_session()
            session, data = fetch_symbol(session, symbol)
            save_json(data, output_path)
            count = len(data.get("data", []))
            suffix = " (retry)" if attempt > 0 else ""
            emit(index, f"{label}->  {count:>5} records{suffix}")
            with print_lock:
                progress["success"] += 1
            return session
        except Exception:
            pass

    emit(index, f"{label}->  ERROR")
    return session

def worker(task_queue, total, width):
    session = get_session()
    symbols_done = 0

    while True:
        try:
            index, symbol = task_queue.get_nowait()
        except queue.Empty:
            return
        try:
            if symbols_done > 0 and symbols_done % SESSION_REFRESH_EVERY == 0:
                session = get_session()
            session = process_symbol(index, symbol, total, width, session)
            symbols_done += 1
        finally:
            task_queue.task_done()

def main():
    symbols = read_symbols(INPUT_PATH)
    total = len(symbols)
    width = len(str(total))

    clear_output_dir()
    print(f"\nDownloading data for {total} symbols using {MAX_WORKERS} parallel workers ...\n")

    try:
        get_session()
    except requests.RequestException:
        print("Failed to connect to NSE")
        return

    task_queue = queue.Queue()
    for i, symbol in enumerate(symbols, start=1):
        task_queue.put((i, symbol))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(worker, task_queue, total, width)
            for _ in range(MAX_WORKERS)
        ]
        for future in futures:
            future.result()

    success = progress["success"]
    print()
    print(f"Downloaded data for {success}/{total} symbols")
    print(f"Saved to : {OUTPUT_DIR_PATH}")

if __name__ == "__main__":
    main()
