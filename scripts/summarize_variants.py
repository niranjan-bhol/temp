"""
Aggregates the baseline strategy (data/prev_vwap_trades/) and all variant
backtests (data/prev_vwap_trades_variants/<variant>/) into a single
comparison table: data/prev_vwap_trades_variants/comparison.csv
"""
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BASELINE_DIR = BASE_DIR / "data" / "prev_vwap_trades"
VARIANTS_ROOT = BASE_DIR / "data" / "prev_vwap_trades_variants"
OUTPUT_PATH = VARIANTS_ROOT / "comparison.csv"

FIELDNAMES = [
	"variant", "trades", "win_rate_pct", "avg_pnl_pct",
	"total_pnl_pct", "total_pnl_abs", "worst_1pct_pnl_pct",
]


def load_trades(csv_path, trade_type_col="trade_type"):
	with csv_path.open("r", newline="") as file:
		reader = csv.DictReader(file)
		return [row for row in reader if (row.get(trade_type_col) or "").strip() in ("LONG", "SHORT")]


def summarize_variant(variant_dir):
	pnl_pcts = []
	pnl_abs_total = 0.0
	wins = 0

	for csv_path in sorted(variant_dir.glob("*.csv")):
		if csv_path.name == "summary.csv":
			continue
		trades = load_trades(csv_path)
		for row in trades:
			pnl_pct = float(row["pnl_pct"])
			pnl_abs = float(row["pnl_abs"])
			pnl_pcts.append(pnl_pct)
			pnl_abs_total += pnl_abs
			if pnl_pct > 0:
				wins += 1

	if not pnl_pcts:
		return None

	total_trades = len(pnl_pcts)
	pnl_pcts_sorted = sorted(pnl_pcts)
	worst_1pct_idx = max(0, int(total_trades * 0.01) - 1)

	return {
		"trades": total_trades,
		"win_rate_pct": round(wins / total_trades * 100, 2),
		"avg_pnl_pct": round(sum(pnl_pcts) / total_trades, 4),
		"total_pnl_pct": round(sum(pnl_pcts), 4),
		"total_pnl_abs": round(pnl_abs_total, 4),
		"worst_1pct_pnl_pct": round(pnl_pcts_sorted[worst_1pct_idx], 4),
	}


def main():
	results = []

	baseline_summary = summarize_variant(BASELINE_DIR)
	if baseline_summary is not None:
		results.append({"variant": "baseline", **baseline_summary})

	variant_dirs = sorted(p for p in VARIANTS_ROOT.iterdir() if p.is_dir())
	for variant_dir in variant_dirs:
		summary = summarize_variant(variant_dir)
		if summary is not None:
			results.append({"variant": variant_dir.name, **summary})

	results.sort(key=lambda r: r["avg_pnl_pct"], reverse=True)

	OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
	with OUTPUT_PATH.open("w", newline="") as file:
		writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
		writer.writeheader()
		writer.writerows(results)

	print(f"{'variant':<22}{'trades':>8}{'win_rate%':>12}{'avg_pnl%':>12}{'total_pnl%':>13}{'total_pnl_abs':>16}{'worst1%_pnl%':>15}")
	for r in results:
		print(f"{r['variant']:<22}{r['trades']:>8}{r['win_rate_pct']:>12}{r['avg_pnl_pct']:>12}{r['total_pnl_pct']:>13}{r['total_pnl_abs']:>16}{r['worst_1pct_pnl_pct']:>15}")

	relative_output = Path("/") / OUTPUT_PATH.relative_to(BASE_DIR.parent)
	print(f"\nComparison written to: {relative_output}")


if __name__ == "__main__":
	main()
