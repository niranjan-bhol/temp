import csv
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "historical" / "json"
OUTPUT_DIR = BASE_DIR / "data" / "historical" / "csv"

def convert_json_to_csv():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    relative_output = Path("/") / OUTPUT_DIR.relative_to(BASE_DIR.parent)
    print(f"Output directory: {relative_output}\n")
    
    json_files = list(INPUT_DIR.glob("*.json"))
    
    if not json_files:
        print(f"No JSON files found in {INPUT_DIR.relative_to(BASE_DIR)}")
        return
    
    print(f"Found {len(json_files)} JSON files\n")
    
    success_count = 0
    
    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            candles = data.get("data", {}).get("candles", [])
            
            if not candles:
                print(f"{json_file.name}: No candle data found")
                continue
            
            csv_filename = json_file.stem + ".csv"
            csv_file = OUTPUT_DIR / csv_filename
            
            with open(csv_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                
                writer.writerow([
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "open_interest"
                ])
                
                for candle in candles:
                    writer.writerow(candle)
            
            print(f"{json_file.name} -> {csv_filename} ({len(candles):,} rows)")
            success_count += 1
        
        except Exception as e:
            print(f"{json_file.name}: Error - {e}")
    
    print(f"\nSuccessfully converted JSON data for {success_count}/{len(json_files)} symbols to CSV")

def main():
    convert_json_to_csv()

if __name__ == "__main__":
    main()
