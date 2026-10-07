"""
Look at the exact start_date of every run in data/momentum/momentum_stocks.csv and ask:
"what was happening in the days/weeks BEFORE the trend officially started (per ADX)?"

This is a pre-breakout trigger study -- it only uses data strictly before each run's
start_date (no lookahead), so whatever shows up here is usable as an actual entry
signal (you'd be trading the breakout, not the already-confirmed trend).

For every run, two windows are compared:
  BASELINE window : trading days [-70, -10) before start_date   (the "quiet" period)
  TRIGGER window  : trading days [-10, 0)  before start_date    (the lead-up)
Plus the start_date bar itself (the breakout/entry day).

Features computed per run (all from data up to and including start_date):
  volume_surge_ratio        avg volume   (trigger / baseline)
  turnover_surge_ratio      avg turnover (trigger / baseline)
  deliverable_pct_change    avg deliverable% (trigger) - avg deliverable% (baseline)
  atr_pct_contraction       avg daily range% (trigger) / avg daily range% (baseline)
                            (<1 => volatility squeezed right before the move = coiling)
  pre_run_drift_pct         % price change over the trigger window itself (already
                            moving in the run's direction before ADX confirms it)
  gap_pct                   (open[start] - close[start-1]) / close[start-1] * 100
  breakout_new_high / _low  does start_date's close make a new high/low vs the last
                            70 days (baseline+trigger)?

Reads:  data/momentum/momentum_stocks.csv
        data/nse/csv_transformed/{symbol}.csv
Writes: data/momentum/momentum_triggers.csv          (per-run feature values)
        data/momentum/momentum_triggers_summary.csv  (aggregated stats, up vs down)
"""

from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
PRICE_DIR = BASE_DIR / "data" / "nse" / "csv_transformed"
MOMENTUM_PATH = BASE_DIR / "data" / "momentum" / "momentum_stocks.csv"
OUTPUT_DIR = BASE_DIR / "data" / "momentum"
TRIGGERS_PATH = OUTPUT_DIR / "momentum_triggers.csv"
SUMMARY_PATH = OUTPUT_DIR / "momentum_triggers_summary.csv"

BASELINE_LOOKBACK = 70  # trading days before start_date that make up the full history window
TRIGGER_LOOKBACK = 10   # most recent trading days before start_date (the lead-up)


def load_price_data(symbol: str) -> pd.DataFrame | None:
    path = PRICE_DIR / f"{symbol}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    for col in ["open", "high", "low", "close", "traded_quantity", "turnover", "deliverable_percentage"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    return df


def compute_features(df: pd.DataFrame, idx_start: int, direction: str) -> dict | None:
    if idx_start < BASELINE_LOOKBACK:
        return None

    baseline = df.iloc[idx_start - BASELINE_LOOKBACK : idx_start - TRIGGER_LOOKBACK]
    trigger = df.iloc[idx_start - TRIGGER_LOOKBACK : idx_start]
    start_row = df.iloc[idx_start]
    prev_close = df.iloc[idx_start - 1]["close"]

    if len(baseline) < (BASELINE_LOOKBACK - TRIGGER_LOOKBACK) * 0.8 or len(trigger) < TRIGGER_LOOKBACK * 0.8:
        return None

    baseline_atr_pct = ((baseline["high"] - baseline["low"]) / baseline["close"] * 100).mean()
    trigger_atr_pct = ((trigger["high"] - trigger["low"]) / trigger["close"] * 100).mean()

    history = pd.concat([baseline, trigger])
    history_high = history["high"].max()
    history_low = history["low"].min()

    pre_run_drift_pct = (trigger["close"].iloc[-1] - trigger["close"].iloc[0]) / trigger["close"].iloc[0] * 100

    return {
        "volume_surge_ratio": trigger["traded_quantity"].mean() / baseline["traded_quantity"].mean(),
        "turnover_surge_ratio": trigger["turnover"].mean() / baseline["turnover"].mean(),
        "deliverable_pct_baseline": baseline["deliverable_percentage"].mean(),
        "deliverable_pct_trigger": trigger["deliverable_percentage"].mean(),
        "deliverable_pct_change": trigger["deliverable_percentage"].mean() - baseline["deliverable_percentage"].mean(),
        "atr_pct_baseline": baseline_atr_pct,
        "atr_pct_trigger": trigger_atr_pct,
        "atr_pct_contraction_ratio": trigger_atr_pct / baseline_atr_pct if baseline_atr_pct else np.nan,
        "pre_run_drift_pct": pre_run_drift_pct,
        "gap_pct": (start_row["open"] - prev_close) / prev_close * 100,
        "breakout_new_high": bool(start_row["close"] >= history_high),
        "breakout_new_low": bool(start_row["close"] <= history_low),
        "breakout_in_run_direction": bool(
            (direction == "up" and start_row["close"] >= history_high)
            or (direction == "down" and start_row["close"] <= history_low)
        ),
        "ma_aligned_up": bool(start_row["close"] > start_row["sma20"] > start_row["sma50"]),
        "ma_aligned_down": bool(start_row["close"] < start_row["sma20"] < start_row["sma50"]),
    }


def main():
    momentum_df = pd.read_csv(MOMENTUM_PATH, parse_dates=["start_date", "end_date"])
    print(f"Loaded {len(momentum_df)} momentum runs")

    price_cache: dict[str, pd.DataFrame] = {}
    rows = []

    for i, run in enumerate(momentum_df.itertuples(index=False), start=1):
        symbol = run.symbol
        if symbol not in price_cache:
            price_cache[symbol] = load_price_data(symbol)
        df = price_cache[symbol]
        if df is None:
            continue

        match = df.index[df["date"] == run.start_date]
        if len(match) == 0:
            continue
        idx_start = match[0]

        features = compute_features(df, idx_start, run.direction)
        if features is None:
            continue

        features["symbol"] = symbol
        features["start_date"] = run.start_date.date()
        features["end_date"] = run.end_date.date()
        features["direction"] = run.direction
        features["return_pct"] = run.return_pct
        features["trading_days"] = run.trading_days
        rows.append(features)

    out_df = pd.DataFrame(rows)
    column_order = [
        "symbol", "start_date", "end_date", "direction", "trading_days", "return_pct",
        "volume_surge_ratio", "turnover_surge_ratio",
        "deliverable_pct_baseline", "deliverable_pct_trigger", "deliverable_pct_change",
        "atr_pct_baseline", "atr_pct_trigger", "atr_pct_contraction_ratio",
        "pre_run_drift_pct", "gap_pct",
        "breakout_new_high", "breakout_new_low", "breakout_in_run_direction",
        "ma_aligned_up", "ma_aligned_down",
    ]
    out_df = out_df[column_order]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(TRIGGERS_PATH, index=False)
    print(f"Computed features for {len(out_df)}/{len(momentum_df)} runs -> {TRIGGERS_PATH.relative_to(BASE_DIR.parent)}")

    # --- aggregate summary, split by direction ---
    numeric_cols = [
        "volume_surge_ratio", "turnover_surge_ratio", "deliverable_pct_change",
        "atr_pct_contraction_ratio", "pre_run_drift_pct", "gap_pct",
    ]
    summary_rows = []
    for direction, group in out_df.groupby("direction"):
        row = {"direction": direction, "n_runs": len(group)}
        for col in numeric_cols:
            row[f"{col}_median"] = round(group[col].median(), 3)
            row[f"{col}_mean"] = round(group[col].mean(), 3)
        row["pct_volume_surge_gt_1.3"] = round((group["volume_surge_ratio"] > 1.3).mean() * 100, 1)
        row["pct_volatility_contraction_lt_1"] = round((group["atr_pct_contraction_ratio"] < 1).mean() * 100, 1)
        row["pct_deliverable_rising"] = round((group["deliverable_pct_change"] > 0).mean() * 100, 1)
        row["pct_breakout_in_run_direction"] = round(group["breakout_in_run_direction"].mean() * 100, 1)
        row["pct_small_gap_abs_lt_2"] = round((group["gap_pct"].abs() < 2).mean() * 100, 1)
        ma_col = "ma_aligned_up" if direction == "up" else "ma_aligned_down"
        row["pct_ma_aligned_with_run"] = round(group[ma_col].mean() * 100, 1)
        row["pct_pre_run_drift_same_sign"] = round(
            ((direction == "up") & (group["pre_run_drift_pct"] > 0) | (direction == "down") & (group["pre_run_drift_pct"] < 0)).mean() * 100, 1
        )
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(SUMMARY_PATH, index=False)
    print(f"Wrote summary -> {SUMMARY_PATH.relative_to(BASE_DIR.parent)}")
    print()
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
