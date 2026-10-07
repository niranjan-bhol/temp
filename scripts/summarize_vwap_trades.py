import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "trades"
OUTPUT_PATH = BASE_DIR / "data" / "trades" / "summary.csv"

FIELDNAMES = [
	"symbol",
	"trades",
	"wins",
	"losses",
	"win_rate_pct",
	"avg_pct_return",
	"total_pct_return",
	"avg_abs_return",
	"total_abs_return",
]


def summarize_file(input_path):
	with input_path.open("r", newline="") as file:
		reader = csv.DictReader(file)
		trades = [row for row in reader if (row.get("buy_date") or "").strip()]

	if not trades:
		return None

	pct_returns = [float(row["pct_return"]) for row in trades]
	abs_returns = [float(row["abs_return"]) for row in trades]
	wins = sum(1 for r in pct_returns if r > 0)
	losses = sum(1 for r in pct_returns if r <= 0)
	trade_count = len(trades)

	return {
		"symbol": input_path.stem,
		"trades": trade_count,
		"wins": wins,
		"losses": losses,
		"win_rate_pct": round((wins / trade_count) * 100, 2),
		"avg_pct_return": round(sum(pct_returns) / trade_count, 4),
		"total_pct_return": round(sum(pct_returns), 4),
		"avg_abs_return": round(sum(abs_returns) / trade_count, 4),
		"total_abs_return": round(sum(abs_returns), 4),
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

	summaries.sort(key=lambda s: s["total_pct_return"], reverse=True)

	with OUTPUT_PATH.open("w", newline="") as file:
		writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
		writer.writeheader()
		writer.writerows(summaries)

	total_trades = sum(s["trades"] for s in summaries)
	total_wins = sum(s["wins"] for s in summaries)
	overall_win_rate = round((total_wins / total_trades) * 100, 2) if total_trades else 0
	overall_avg_pct_return = round(sum(s["total_pct_return"] for s in summaries) / total_trades, 4) if total_trades else 0

	relative_output = Path("/") / OUTPUT_PATH.relative_to(BASE_DIR.parent)
	print(f"Symbols with trades: {len(summaries)}/{total}")
	print(f"Total trades: {total_trades}")
	print(f"Overall win rate: {overall_win_rate}%")
	print(f"Overall avg pct return per trade: {overall_avg_pct_return}%")
	print(f"\nSummary written to: {relative_output}")


if __name__ == "__main__":
	main()
