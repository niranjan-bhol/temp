import csv
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "nse" / "csv"
OUTPUT_DIR = BASE_DIR / "data" / "nse" / "csv_transformed"

COLUMN_MAPPING = {
    "mTIMESTAMP": "date",
    "CH_OPENING_PRICE": "open",
    "CH_TRADE_HIGH_PRICE": "high",
    "CH_TRADE_LOW_PRICE": "low",
    "CH_CLOSING_PRICE": "close",
    "VWAP": "vwap",
    "CH_TOT_TRADED_QTY": "traded_quantity",
    "COP_DELIV_QTY": "deliverable_quantity",
    "COP_DELIV_PERC": "deliverable_percentage",
    "CH_TOT_TRADED_VAL": "turnover",
    "CH_TOTAL_TRADES": "trades"
}

def transform_date(date_str):
    try:
        dt = datetime.strptime(date_str, "%d-%b-%Y")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return date_str

def transform_csv(input_path, output_path):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(input_path, "r") as f_in:
        reader = csv.DictReader(f_in)
        rows = list(reader)
    
    if not rows:
        return 0
    
    transformed_rows = []
    for row in rows:
        transformed_row = {}
        for old_col, new_col in COLUMN_MAPPING.items():
            value = row.get(old_col, "")
            if new_col == "date":
                value = transform_date(value)
            transformed_row[new_col] = value
        transformed_rows.append(transformed_row)
    
    with open(output_path, "w", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=COLUMN_MAPPING.values())
        writer.writeheader()
        writer.writerows(transformed_rows)
    
    return len(transformed_rows)

def main():
    csv_files = sorted(INPUT_DIR.glob("*.csv"))
    total = len(csv_files)
    width = len(str(total))
    
    print(f"Found {total} CSV files")
    relative_path = Path("/") / OUTPUT_DIR.relative_to(BASE_DIR.parent)
    print(f"Output directory: {relative_path}")
    print(f"\nTransforming data ...\n")
    
    success = 0
    
    for i, csv_path in enumerate(csv_files, start=1):
        symbol = csv_path.stem
        output_path = OUTPUT_DIR / f"{symbol}.csv"
        label = f"[{i:0{width}}/{total}]  {symbol:<12}"
        
        try:
            rows = transform_csv(csv_path, output_path)
            print(f"{label}->  {rows} rows")
            success += 1
        except Exception:
            print(f"{label}->  Error")
    
    print(f"\nSuccessfully transformed {success}/{total} CSV files")

if __name__ == "__main__":
    main()
