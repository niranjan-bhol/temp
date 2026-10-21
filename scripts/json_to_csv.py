import csv
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "nse" / "json"
OUTPUT_DIR = BASE_DIR / "data" / "nse" / "csv"
OUTPUT_DIR_PATH = f"{BASE_DIR.name}/{OUTPUT_DIR.relative_to(BASE_DIR)}"

FIELDNAMES = ["date", "open", "high", "low", "close", "volume", "turnover"]

def clear_output_dir():
    if OUTPUT_DIR.exists():
        existing_files = list(OUTPUT_DIR.glob("*.csv"))
        for file_path in existing_files:
            file_path.unlink()
        print(f"Output directory exists : {OUTPUT_DIR_PATH}")
        print(f"\nCleared output directory")
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Created output directory : {OUTPUT_DIR_PATH}")

def parse_date(value):
    return datetime.strptime(value, "%d-%b-%Y").date()

def convert_file(json_path, csv_path):
    with open(json_path) as f:
        payload = json.load(f)

    records = payload.get("data", [])
    rows = []
    for record in records:
        rows.append({
            "date": parse_date(record["EOD_TIMESTAMP"]),
            "open": record["EOD_OPEN_INDEX_VAL"],
            "high": record["EOD_HIGH_INDEX_VAL"],
            "low": record["EOD_LOW_INDEX_VAL"],
            "close": record["EOD_CLOSE_INDEX_VAL"],
            "volume": record["HIT_TRADED_QTY"],
            "turnover": record["HIT_TURN_OVER"],
        })

    rows.sort(key=lambda row: row["date"])

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)

def main():
    json_files = sorted(INPUT_DIR.glob("*.json"))
    total = len(json_files)
    width = len(str(total))

    if total == 0:
        print(f"No JSON files found in {INPUT_DIR}")
        return

    clear_output_dir()
    print(f"\nConverting {total} files to CSV ...\n")

    success = 0
    for index, json_path in enumerate(json_files, start=1):
        label = f"[{index:0{width}}/{total}]  {json_path.stem:<32}"
        csv_path = OUTPUT_DIR / f"{json_path.stem}.csv"
        try:
            count = convert_file(json_path, csv_path)
            print(f"{label}->  {count:>5} rows")
            success += 1
        except Exception:
            print(f"{label}->  ERROR")

    print()
    print(f"Converted {success}/{total} files")
    print(f"Saved to : {OUTPUT_DIR_PATH}")

if __name__ == "__main__":
    main()
