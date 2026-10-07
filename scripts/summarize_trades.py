import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "prev_vwap_trades"
OUTPUT_PATH = BASE_DIR / "data" / "prev_vwap_trades" / "summary.csv"

FIELDNAMES = ["symbol", "trades", "pnl_abs", "pnl_pct"]


def summarize_file(input_path):
	with input_path.open("r", newline="") as file:
		reader = csv.DictReader(file)
		trades = [row for row in reader if (row.get("trade_type") or "").strip() not in ("", "SKIP")]

	if not trades:
		return None

	pnl_abs_total = sum(float(row["pnl_abs"]) for row in trades)
	pnl_pct_total = sum(float(row["pnl_pct"]) for row in trades)

	return {
		"symbol": input_path.stem,
		"trades": len(trades),
		"pnl_abs": round(pnl_abs_total, 4),
		"pnl_pct": round(pnl_pct_total, 4),
	}


def main():
	csv_files = sorted(p for p in INPUT_DIR.glob("*.csv") if p.name != "summary.csv")
	total = len(csv_files)

	print(f"Found {total} CSV files")
	print("\nSummarizing files ...\n")

	summaries = []
	for input_path in csv_files:
		summary = summarize_file(input_path)
		if summary is not None:
			summaries.append(summary)

	summaries.sort(key=lambda s: s["pnl_pct"], reverse=True)

	with OUTPUT_PATH.open("w", newline="") as file:
		writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
		writer.writeheader()
		writer.writerows(summaries)

	total_trades = sum(s["trades"] for s in summaries)
	total_pnl_abs = sum(s["pnl_abs"] for s in summaries)
	total_pnl_pct = sum(s["pnl_pct"] for s in summaries)

	relative_output = Path("/") / OUTPUT_PATH.relative_to(BASE_DIR.parent)
	print(f"Symbols with trades: {len(summaries)}/{total}")
	print(f"Total trades: {total_trades}")
	print(f"Total pnl_abs: {round(total_pnl_abs, 4)}")
	print(f"Total pnl_pct: {round(total_pnl_pct, 4)}")
	print(f"\nSummary written to: {relative_output}")


if __name__ == "__main__":
	main()
