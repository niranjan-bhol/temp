import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "b"
TREND_DIR = BASE_DIR / "data" / "nse" / "csv_transformed"
OUTPUT_DIR = BASE_DIR / "data" / "trades"

SIGNAL_COLUMNS = [str(n) for n in range(1, 11)]
ENTRY_THRESHOLD = 8
EXIT_THRESHOLD = 8

# False-signal filter (reduce whipsaw entries): only enter when close > SMA20 > SMA50,
# the strongest validated up-trend factor from this repo's momentum research
# (momentum_triggers_summary.csv). A persistence filter (requiring the entry
# condition to hold for N consecutive days) was also tested but made results
# worse (delayed entries buy into an already-extended move at a worse price),
# so it was dropped.
SMA_SHORT = 20
SMA_LONG = 50

FIELDNAMES = ["buy_date", "sell_date", "buy", "sell", "abs_return", "pct_return"]


def positive_count(row):
	count = 0
	for col in SIGNAL_COLUMNS:
		value = (row.get(col) or "").strip()
		if value == "1":
			count += 1
	return count


def load_trend_data(symbol):
	"""Build date -> (close, sma20, sma50) using close prices from csv_transformed."""
	trend_path = TREND_DIR / f"{symbol}.csv"
	if not trend_path.exists():
		return {}

	with trend_path.open("r", newline="") as file:
		reader = csv.DictReader(file)
		rows = [row for row in reader if (row.get("date") or "").strip()]

	rows.sort(key=lambda row: row["date"])

	closes = []
	trend_data = {}
	for row in rows:
		close_str = (row.get("close") or "").strip()
		close = float(close_str) if close_str else None
		closes.append(close)

		sma20 = None
		sma50 = None
		if close is not None:
			if len(closes) >= SMA_SHORT:
				window = [c for c in closes[-SMA_SHORT:] if c is not None]
				if len(window) == SMA_SHORT:
					sma20 = sum(window) / SMA_SHORT
			if len(closes) >= SMA_LONG:
				window = [c for c in closes[-SMA_LONG:] if c is not None]
				if len(window) == SMA_LONG:
					sma50 = sum(window) / SMA_LONG

		trend_data[row["date"]] = (close, sma20, sma50)

	return trend_data


def is_uptrend(trend_data, date):
	close, sma20, sma50 = trend_data.get(date, (None, None, None))
	if close is None or sma20 is None or sma50 is None:
		return False
	return close > sma20 > sma50


def process_file(input_path, trend_data):
	with input_path.open("r", newline="") as file:
		reader = csv.DictReader(file)
		rows = [row for row in reader if (row.get("date") or "").strip()]

	rows.sort(key=lambda row: row["date"])

	trades = []
	position = None  # (buy_date, buy_vwap)

	for row in rows:
		vwap = (row.get("vwap") or "").strip()
		if not vwap:
			continue
		count = positive_count(row)
		date = row["date"]

		if position is None and count >= ENTRY_THRESHOLD and is_uptrend(trend_data, date):
			position = (date, float(vwap))
		elif position is not None and count < EXIT_THRESHOLD:
			buy_date, buy_vwap = position
			sell_date, sell_vwap = date, float(vwap)
			abs_return = sell_vwap - buy_vwap
			pct_return = (abs_return / buy_vwap) * 100
			trades.append({
				"buy_date": buy_date,
				"sell_date": sell_date,
				"buy": buy_vwap,
				"sell": sell_vwap,
				"abs_return": round(abs_return, 4),
				"pct_return": round(pct_return, 4),
			})
			position = None

	return trades


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
			trend_data = load_trend_data(input_path.stem)
			trades = process_file(input_path, trend_data)
			with output_path.open("w", newline="") as file:
				writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
				writer.writeheader()
				writer.writerows(trades)
			print(f"{label}->  {len(trades)} trades")
			success += 1
		except Exception as exc:
			print(f"{label}->  Error: {exc}")

	print(f"\nSuccessfully processed {success}/{total} CSV files")


if __name__ == "__main__":
	main()
