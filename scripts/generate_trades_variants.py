"""
Generates 6 variant backtests of the prev-day-VWAP-touch strategy, each
isolating ONE improvement idea on top of the baseline logic in
generate_trades.py, so they can be compared against the baseline in
data/prev_vwap_trades/summary.csv.

Baseline recap (generate_trades.py):
  - Entry filter: |prev_close - prev_vwap| / prev_vwap * 100 <= 0.1  (else SKIP)
  - Direction: open < prev_vwap -> LONG, open > prev_vwap -> SHORT
  - Exit: prev_vwap if low <= prev_vwap <= high, else today's close

Variants (each changes exactly one thing vs baseline):
  1. stop_loss_1pct     - add a 1% stop-loss; if the adverse side (stop) is
                          within today's low..high range it takes priority
                          over the target (conservative/worst-case fill
                          assumption, since only OHLC -- not tick order --
                          is available).
  2. no_pct_diff_filter - remove the 0.1% entry filter entirely; trade every
                          day where open != prev_vwap.
  3. atr_filter         - replace the 0.1% filter with a volatility-relative
                          one: |open - prev_vwap| <= 0.5 * ATR(14) (ATR
                          computed using only data up to and including
                          yesterday -- no lookahead).
  4. short_only         - identical to baseline except LONG setups are
                          skipped (SHORT side only).
  5. turnover_filter_5cr- identical to baseline plus an added liquidity
                          filter: trailing 20-day average turnover (as of
                          yesterday) must be >= 5 crore.
  6. partial_exit       - identical to baseline on hit days. On days where
                          the target is NOT hit, checks whether price at
                          least reached the midpoint between entry and
                          target; if so, half the position is assumed to
                          exit at that midpoint and half at the close
                          (instead of the full position riding to close),
                          to cap the loss-tail on misses.
"""
import csv
from pathlib import Path
from statistics import mean

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "nse" / "csv_transformed"
OUTPUT_ROOT = BASE_DIR / "data" / "prev_vwap_trades_variants"

PCT_DIFF_THRESHOLD = 0.1  # percent, same as baseline
ATR_WINDOW = 14
ATR_MULTIPLIER = 0.5
TURNOVER_WINDOW = 20
STOP_LOSS_PERCENT = 1.0
PARTIAL_FRACTION = 0.5

FIELDNAMES = [
	"date", "trade_type", "entry", "target", "exit",
	"target_hit", "stop_hit", "pnl_abs", "pnl_pct",
]

VARIANTS = {
	"stop_loss_1pct": {"exit_mode": "stop_loss"},
	"no_pct_diff_filter": {"filter_mode": "none"},
	"atr_filter": {"filter_mode": "atr"},
	"short_only": {"side_filter": "SHORT"},
	"turnover_filter_5cr": {"min_avg_turnover_cr": 5.0},
	"partial_exit": {"exit_mode": "partial"},
}


def load_rows(input_path):
	with input_path.open("r", newline="") as file:
		reader = csv.DictReader(file)
		rows = [row for row in reader if (row.get("date") or "").strip()]
	rows.sort(key=lambda row: row["date"])

	parsed = []
	for row in rows:
		try:
			parsed.append({
				"date": row["date"],
				"open": float(row["open"]),
				"high": float(row["high"]),
				"low": float(row["low"]),
				"close": float(row["close"]),
				"vwap": float(row["vwap"]),
				"turnover": float(row["turnover"]) if (row.get("turnover") or "").strip() else None,
			})
		except (ValueError, KeyError):
			parsed.append(None)
	return parsed


def compute_true_ranges(rows):
	"""trs[i] = true range of day i using close of day i-1. trs[0] = None."""
	trs = [None] * len(rows)
	for i in range(1, len(rows)):
		if rows[i] is None or rows[i - 1] is None:
			continue
		high, low = rows[i]["high"], rows[i]["low"]
		prev_close = rows[i - 1]["close"]
		trs[i] = max(high - low, abs(high - prev_close), abs(low - prev_close))
	return trs


def compute_atr_series(trs, window=ATR_WINDOW):
	"""atr[i] = mean of the `window` most recent TRs ending at i (inclusive)."""
	atr = [None] * len(trs)
	for i in range(len(trs)):
		if i - window + 1 < 1:
			continue
		window_vals = trs[i - window + 1:i + 1]
		if any(v is None for v in window_vals):
			continue
		atr[i] = mean(window_vals)
	return atr


def compute_turnover_avg_series(rows, window=TURNOVER_WINDOW):
	"""avg_turnover_cr[i] = trailing `window`-day avg turnover (in crore) ending at i (inclusive)."""
	avg_cr = [None] * len(rows)
	for i in range(len(rows)):
		if i - window + 1 < 0:
			continue
		window_rows = rows[i - window + 1:i + 1]
		values = [r["turnover"] for r in window_rows if r is not None and r["turnover"] is not None]
		if len(values) < window:
			continue
		avg_cr[i] = mean(values) / 1e7
	return avg_cr


def passes_entry_filter(params, open_, prev_vwap, pct_diff, atr_yesterday):
	filter_mode = params.get("filter_mode", "pct_diff")
	if filter_mode == "none":
		return True
	if filter_mode == "atr":
		if atr_yesterday is None:
			return False
		return abs(open_ - prev_vwap) <= ATR_MULTIPLIER * atr_yesterday
	# default: pct_diff
	return pct_diff <= PCT_DIFF_THRESHOLD


def process_file(rows, params):
	trs = compute_true_ranges(rows)
	atr_series = compute_atr_series(trs)
	turnover_avg_series = compute_turnover_avg_series(rows)

	side_filter = params.get("side_filter", "BOTH")
	exit_mode = params.get("exit_mode", "baseline")
	min_avg_turnover_cr = params.get("min_avg_turnover_cr")

	output_rows = []

	for i in range(1, len(rows)):
		today = rows[i]
		yesterday = rows[i - 1]
		if today is None or yesterday is None:
			continue

		prev_close = yesterday["close"]
		prev_vwap = yesterday["vwap"]
		if prev_vwap == 0:
			continue

		open_, high, low, close = today["open"], today["high"], today["low"], today["close"]
		pct_diff = abs(prev_close - prev_vwap) / prev_vwap * 100
		atr_yesterday = atr_series[i - 1]

		if not passes_entry_filter(params, open_, prev_vwap, pct_diff, atr_yesterday):
			continue

		if min_avg_turnover_cr is not None:
			avg_turnover_cr = turnover_avg_series[i - 1]
			if avg_turnover_cr is None or avg_turnover_cr < min_avg_turnover_cr:
				continue

		if open_ < prev_vwap:
			trade_type = "LONG"
		elif open_ > prev_vwap:
			trade_type = "SHORT"
		else:
			continue

		if side_filter != "BOTH" and trade_type != side_filter:
			continue

		entry = open_
		target = prev_vwap
		target_in_range = low <= target <= high

		stop_hit = False
		if exit_mode == "stop_loss":
			if trade_type == "LONG":
				stop_price = entry * (1 - STOP_LOSS_PERCENT / 100)
				stop_in_range = low <= stop_price <= high
			else:
				stop_price = entry * (1 + STOP_LOSS_PERCENT / 100)
				stop_in_range = low <= stop_price <= high

			# Worst-case ordering assumption: if both stop and target fall
			# within today's range, we can't know which was touched first
			# from OHLC alone, so the stop (conservative/protective side)
			# is assumed to trigger first.
			if stop_in_range:
				exit_price = stop_price
				target_hit = False
				stop_hit = True
			elif target_in_range:
				exit_price = target
				target_hit = True
			else:
				exit_price = close
				target_hit = False

			pnl_abs = (exit_price - entry) if trade_type == "LONG" else (entry - exit_price)
			pnl_pct = pnl_abs / entry * 100

		elif exit_mode == "partial":
			if target_in_range:
				exit_price = target
				target_hit = True
				pnl_abs = (exit_price - entry) if trade_type == "LONG" else (entry - exit_price)
			else:
				target_hit = False
				mid = (entry + target) / 2
				mid_in_range = (low <= mid <= high) if trade_type == "LONG" else (low <= mid <= high)
				if mid_in_range:
					half_pnl = (mid - entry) if trade_type == "LONG" else (entry - mid)
					half_pnl_close = (close - entry) if trade_type == "LONG" else (entry - close)
					pnl_abs = PARTIAL_FRACTION * half_pnl + (1 - PARTIAL_FRACTION) * half_pnl_close
					exit_price = PARTIAL_FRACTION * mid + (1 - PARTIAL_FRACTION) * close
				else:
					exit_price = close
					pnl_abs = (exit_price - entry) if trade_type == "LONG" else (entry - exit_price)
			pnl_pct = pnl_abs / entry * 100

		else:  # baseline exit logic
			if target_in_range:
				exit_price = target
				target_hit = True
			else:
				exit_price = close
				target_hit = False
			pnl_abs = (exit_price - entry) if trade_type == "LONG" else (entry - exit_price)
			pnl_pct = pnl_abs / entry * 100

		output_rows.append({
			"date": today["date"],
			"trade_type": trade_type,
			"entry": round(entry, 4),
			"target": round(target, 4),
			"exit": round(exit_price, 4),
			"target_hit": target_hit,
			"stop_hit": stop_hit,
			"pnl_abs": round(pnl_abs, 4),
			"pnl_pct": round(pnl_pct, 4),
		})

	return output_rows


def main():
	csv_files = sorted(INPUT_DIR.glob("*.csv"))
	total = len(csv_files)
	width = len(str(total)) if total > 0 else 1

	for variant_name, params in VARIANTS.items():
		output_dir = OUTPUT_ROOT / variant_name
		output_dir.mkdir(parents=True, exist_ok=True)

		print(f"=== Variant: {variant_name} ===")
		success = 0
		variant_trades = 0
		for i, input_path in enumerate(csv_files, start=1):
			output_path = output_dir / input_path.name
			label = f"[{i:0{width}}/{total}]  {input_path.stem:<12}"
			try:
				rows = load_rows(input_path)
				trades = process_file(rows, params)
				with output_path.open("w", newline="") as file:
					writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
					writer.writeheader()
					writer.writerows(trades)
				variant_trades += len(trades)
				success += 1
			except Exception as exc:
				print(f"{label}->  Error: {exc}")

		print(f"Processed {success}/{total} symbols, {variant_trades} total trades\n")


if __name__ == "__main__":
	main()
