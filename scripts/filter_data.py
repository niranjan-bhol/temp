import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "historical" / "csv"
OUTPUT_DIR = BASE_DIR / "data" / "historical" / "filtered"

TARGET_TIMES = ["09:15", "15:18", "15:28"]
FALLBACK_DIRECTION = {"09:15": "next", "15:18": "previous", "15:28": "previous"}

def get_time_prefix(time_str):
	return time_str.replace(":", "")

def extract_date_and_time(timestamp):
	date_part, time_part = timestamp.split("T", 1)
	hhmm = time_part[:5]
	return date_part, hhmm

def empty_output_row(date_value):
	row = {"date": date_value}
	for time_str in TARGET_TIMES:
		prefix = get_time_prefix(time_str)
		row[f"{prefix}_open"] = ""
		row[f"{prefix}_high"] = ""
		row[f"{prefix}_low"] = ""
		row[f"{prefix}_close"] = ""
		row[f"{prefix}_volume"] = ""
	row["session_high"] = ""
	row["session_low"] = ""
	row["day_high"] = ""
	row["day_low"] = ""
	return row

def compute_session_high_low(sorted_rows):
	session_high = None
	session_low = None
    
	for hhmm, values in sorted_rows:
		if not ("09:15" <= hhmm <= "15:18"):
			continue
        
		high = float(values["high"])
		low = float(values["low"])
        
		session_high = high if session_high is None else max(session_high, high)
		session_low = low if session_low is None else min(session_low, low)
    
	return session_high, session_low

def compute_day_high_low(sorted_rows):
	day_high = None
	day_low = None
    
	for hhmm, values in sorted_rows:
		if not ("09:15" <= hhmm <= "15:28"):
					continue
		
		high = float(values["high"])
		low = float(values["low"])
        
		day_high = high if day_high is None else max(day_high, high)
		day_low = low if day_low is None else min(day_low, low)
    
	return day_high, day_low

def find_row_for_time(sorted_rows, target_time, direction):
	exact_match = next((r for hhmm, r in sorted_rows if hhmm == target_time), None)
	if exact_match is not None:
		return exact_match
    
	if direction == "next":
		candidates = [r for hhmm, r in sorted_rows if hhmm > target_time]
		return candidates[0] if candidates else None
    
	candidates = [r for hhmm, r in sorted_rows if hhmm < target_time]
	return candidates[-1] if candidates else None

def process_file(input_path, output_path):
	rows_by_date = {}
    
	with input_path.open("r", newline="") as file:
		reader = csv.DictReader(file)
		for row in reader:
			timestamp = (row.get("timestamp") or "").strip()
			if not timestamp:
				continue
            
			try:
				date_value, hhmm = extract_date_and_time(timestamp)
			except ValueError:
				continue
            
			values = {
				"open": (row.get("open") or "").strip(),
				"high": (row.get("high") or "").strip(),
				"low": (row.get("low") or "").strip(),
				"close": (row.get("close") or "").strip(),
				"volume": (row.get("volume") or "").strip(),
			}
            
			rows_by_date.setdefault(date_value, []).append((hhmm, values))
    
	output_rows = []
	for date_value in sorted(rows_by_date.keys()):
		sorted_rows = sorted(rows_by_date[date_value], key=lambda item: item[0])
		output_row = empty_output_row(date_value)
        
		for target_time in TARGET_TIMES:
			prefix = get_time_prefix(target_time)
			direction = FALLBACK_DIRECTION[target_time]
			values = find_row_for_time(sorted_rows, target_time, direction)
            
			if values is not None:
				output_row[f"{prefix}_open"] = values["open"]
				output_row[f"{prefix}_high"] = values["high"]
				output_row[f"{prefix}_low"] = values["low"]
				output_row[f"{prefix}_close"] = values["close"]
				output_row[f"{prefix}_volume"] = values["volume"]
        
		session_high, session_low = compute_session_high_low(sorted_rows)
		output_row["session_high"] = session_high if session_high is not None else ""
		output_row["session_low"] = session_low if session_low is not None else ""
        
		day_high, day_low = compute_day_high_low(sorted_rows)
		output_row["day_high"] = day_high if day_high is not None else ""
		output_row["day_low"] = day_low if day_low is not None else ""
        
		output_rows.append(output_row)
    
	fieldnames = [
		"date",
		"0915_open", "0915_high", "0915_low", "0915_close", "0915_volume",
		"1518_open", "1518_high", "1518_low", "1518_close", "1518_volume",
		"1528_open", "1528_high", "1528_low", "1528_close", "1528_volume",
		"session_high", "session_low",
		"day_high", "day_low",
	]
    
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
