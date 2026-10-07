import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "nse" / "csv_transformed"
OUTPUT_DIR = BASE_DIR / "data" / "prev_vwap_trades"

# If |prev_close - prev_vwap| / prev_vwap * 100 <= this, the prior day closed
# too close to its own VWAP and today's trade is skipped.
SKIP_BAND_PERCENT = 0.1

FIELDNAMES = [
	"date",
	"open",
	"high",
	"low",
	"close",
	"prev_close",
	"prev_vwap",
	"pct_diff",
	"trade_type",
	"entry",
	"target",
	"exit",
	"target_hit",
	"pnl_abs",
	"pnl_pct",
]


def load_rows(input_path):
	with input_path.open("r", newline="") as file:
		reader = csv.DictReader(file)
		rows = [row for row in reader if (row.get("date") or "").strip()]
	rows.sort(key=lambda row: row["date"])
	return rows


def process_file(input_path):
	rows = load_rows(input_path)
	output_rows = []

	for i in range(1, len(rows)):
		today = rows[i]
		yesterday = rows[i - 1]

		try:
			prev_close = float(yesterday["close"])
			prev_vwap = float(yesterday["vwap"])
			open_ = float(today["open"])
			high = float(today["high"])
			low = float(today["low"])
			close = float(today["close"])
		except (ValueError, KeyError):
			continue

		if prev_vwap == 0:
			continue

		pct_diff = abs(prev_close - prev_vwap) / prev_vwap * 100

		row_out = {
			"date": today["date"],
			"open": open_,
			"high": high,
			"low": low,
			"close": close,
			"prev_close": prev_close,
			"prev_vwap": prev_vwap,
			"pct_diff": round(pct_diff, 4),
		}

		if pct_diff > SKIP_BAND_PERCENT:
			row_out.update({
				"trade_type": "SKIP",
				"entry": "",
				"target": "",
				"exit": "",
				"target_hit": "",
				"pnl_abs": "",
				"pnl_pct": "",
			})
			output_rows.append(row_out)
			continue

		if open_ < prev_vwap:
			trade_type = "LONG"
		elif open_ > prev_vwap:
			trade_type = "SHORT"
		else:
			# Open is exactly at prev_vwap, no direction to take.
			row_out.update({
				"trade_type": "SKIP",
				"entry": "",
				"target": "",
				"exit": "",
				"target_hit": "",
				"pnl_abs": "",
				"pnl_pct": "",
			})
			output_rows.append(row_out)
			continue

		entry = open_
		target = prev_vwap

		if low <= prev_vwap <= high:
			exit_price = prev_vwap
			target_hit = True
		else:
			exit_price = close
			target_hit = False

		if trade_type == "LONG":
			pnl_abs = exit_price - entry
		else:
			pnl_abs = entry - exit_price
		pnl_pct = (pnl_abs / entry) * 100

		row_out.update({
			"trade_type": trade_type,
			"entry": entry,
			"target": target,
			"exit": exit_price,
			"target_hit": target_hit,
			"pnl_abs": round(pnl_abs, 4),
			"pnl_pct": round(pnl_pct, 4),
		})
		output_rows.append(row_out)

	return output_rows


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
			rows = process_file(input_path)
			with output_path.open("w", newline="") as file:
				writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
				writer.writeheader()
				writer.writerows(rows)
			active = sum(1 for r in rows if r["trade_type"] != "SKIP")
			print(f"{label}->  {active} trades ({len(rows)} rows)")
			success += 1
		except Exception as exc:
			print(f"{label}->  Error: {exc}")

	print(f"\nSuccessfully processed {success}/{total} CSV files")


if __name__ == "__main__":
	main()
