import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "nse" / "csv_transformed"
OUTPUT_DIR = BASE_DIR / "data" / "nse" / "vwap"

def process_file(input_path, output_path):
	with input_path.open("r", newline="") as file:
		reader = csv.DictReader(file)
		rows = [row for row in reader if (row.get("date") or "").strip()]
    
	rows.sort(key=lambda row: row["date"])
    
	output_rows = []
	prev_vwap = ""
	for row in rows:
		vwap = (row.get("vwap") or "").strip()
        
		output_rows.append({
			"date": row["date"],
			"vwap": vwap,
			"prev_vwap": prev_vwap,
		})
        
		prev_vwap = vwap
    
	fieldnames = ["date", "vwap", "prev_vwap"]
    
	with output_path.open("w", newline="") as file:
		writer = csv.DictWriter(file, fieldnames=fieldnames)
		writer.writeheader()
		writer.writerows(output_rows)
    
	return len(output_rows)

def main():
	csv_files = sorted(INPUT_DIR.glob("*.csv"))
	total = len(csv_files)
	width = len(str(total)) if total > 0 else 1
    
	OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
	print(f"Found {total} CSV files")
	relative_input = Path("/") / INPUT_DIR.relative_to(BASE_DIR.parent)
	relative_output = Path("/") / OUTPUT_DIR.relative_to(BASE_DIR.parent)
	print(f"Input directory: {relative_input}")
	print(f"Output directory: {relative_output}")
	print("\nProcessing files ...\n")
    
	success = 0
	for i, input_path in enumerate(csv_files, start=1):
		output_path = OUTPUT_DIR / input_path.name
		label = f"[{i:0{width}}/{total}]  {input_path.stem:<12}"
        
		try:
			row_count = process_file(input_path, output_path)
			print(f"{label}->  {row_count} rows")
			success += 1
		except Exception:
			print(f"{label}->  Error")
    
	print(f"\nSuccessfully processed {success}/{total} CSV files")

if __name__ == "__main__":
	main()
