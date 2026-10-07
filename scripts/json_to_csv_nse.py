import csv
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "nse" / "json"
OUTPUT_DIR = BASE_DIR / "data" / "nse" / "csv"
OUTPUT_CA_DIR = BASE_DIR / "data" / "nse" / "csv_ca"

def read_json(path):
    with open(path, "r") as f:
        return json.load(f)

def parse_date(record):
    try:
        return datetime.strptime(record.get("mTIMESTAMP", ""), "%d-%b-%Y")
    except (ValueError, TypeError):
        return datetime.min

def save_csv(data, path):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not data or "data" not in data or not data["data"]:
        return 0
    
    records = data["data"]
    sorted_records = sorted(records, key=parse_date)
    
    all_fieldnames = set()
    for record in sorted_records:
        all_fieldnames.update(record.keys())
    
    all_fieldnames.discard("CA")
    fieldnames = sorted(all_fieldnames)
    
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted_records)
    
    return len(sorted_records)

def save_ca_csv(data, path, symbol):
    if not data or "data" not in data or not data["data"]:
        return 0
    
    ca_records = []
    for record in data["data"]:
        if "CA" in record and record["CA"]:
            timestamp = record.get("mTIMESTAMP", "")
            for ca in record["CA"]:
                ca_with_date = {"mTIMESTAMP": timestamp, **ca}
                ca_records.append(ca_with_date)
    
    if not ca_records:
        return 0
    
    OUTPUT_CA_DIR.mkdir(parents=True, exist_ok=True)
    
    all_fieldnames = set()
    for record in ca_records:
        all_fieldnames.update(record.keys())
    fieldnames = sorted(all_fieldnames)
    
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ca_records)
    
    return len(ca_records)

def main():
    json_files = sorted(INPUT_DIR.glob("*.json"))
    total = len(json_files)
    width = len(str(total))
    
    print(f"Found {total} JSON files")
    relative_path = Path("/") / OUTPUT_DIR.relative_to(BASE_DIR.parent)
    relative_ca_path = Path("/") / OUTPUT_CA_DIR.relative_to(BASE_DIR.parent)
    print(f"Main output directory: {relative_path}")
    print(f"CA output directory: {relative_ca_path}")
    print(f"\nConverting data ...\n")
    
    success = 0
    ca_count = 0
    
    for i, json_path in enumerate(json_files, start=1):
        symbol = json_path.stem
        csv_path = OUTPUT_DIR / f"{symbol}.csv"
        ca_csv_path = OUTPUT_CA_DIR / f"{symbol}.csv"
        label = f"[{i:0{width}}/{total}]  {symbol:<12}"
        
        try:
            data = read_json(json_path)
            rows = save_csv(data, csv_path)
            ca_rows = save_ca_csv(data, ca_csv_path, symbol)
            
            if ca_rows > 0:
                print(f"{label}->  {rows} rows  ({ca_rows} CA)")
                ca_count += 1
            else:
                print(f"{label}->  {rows} rows")
            success += 1
        except Exception:
            print(f"{label}->  Error")
    
    print(f"\nSuccessfully converted {success}/{total} JSON files to CSV")
    if ca_count > 0:
        print(f"Successfully extracted corporate actions for {ca_count} symbols")

if __name__ == "__main__":
    main()
