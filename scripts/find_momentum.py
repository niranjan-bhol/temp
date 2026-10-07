"""
Find "pure momentum" stretches in daily OHLCV data.

Reads:  data/nse/csv_transformed/{symbol}.csv   (date, open, high, low, close, vwap,
                                                  traded_quantity, deliverable_quantity,
                                                  deliverable_percentage, turnover, trades)
        data/nse/csv_ca/{symbol}.csv            (corporate actions, used to reject runs
                                                  that straddle a bonus/split/rights/demerger
                                                  so an unadjusted price gap is never
                                                  mistaken for real momentum)

Writes: data/momentum/momentum_stocks.csv       (symbol, start_date, end_date, direction,
                                                  trading_days, return_pct, avg_adx,
                                                  avg_turnover_cr)

Method
------
1. ADX / +DI / -DI (Wilder's smoothing, period 14) are computed per symbol. ADX is the
   standard technical-analysis measure of trend *strength* regardless of direction, and
   +DI/-DI give the *direction*. A day only counts as "trending" when ADX is above
   ADX_THRESHOLD and one directional indicator clearly dominates the other -- this is
   what keeps choppy / sideways / mean-reverting noise out of the results.
2. Consecutive trending days with the same direction are merged into runs. Tiny one/two
   day interruptions (a single noisy candle) are bridged so one genuine trend isn't
   chopped into fragments.
3. Each candidate run then has to clear several independent "no false signal" filters:
   - minimum length (MIN_TRADING_DAYS)
   - minimum total move (MIN_RETURN_PCT)
   - minimum participation/consistency (share of days moving with the trend)
   - minimum liquidity (average turnover), to drop illiquid/low-conviction names
   - no single-day return larger than MAX_SINGLE_DAY_MOVE_PCT (circuit-style/
     data-glitch jumps are not "momentum")
   - no bonus/split/rights/demerger corporate action inside the window (the price
     series is not split-adjusted, so such an event creates a fake gap)
4. Overlapping/adjacent qualifying runs for the same symbol are merged, and the
   strongest (highest avg ADX) run is kept when choices remain.

This is deliberately conservative -- the goal is a small, clean list of unambiguous
momentum stretches to study, not an exhaustive one.
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "nse" / "csv_transformed"
CA_DIR = BASE_DIR / "data" / "nse" / "csv_ca"
OUTPUT_DIR = BASE_DIR / "data" / "momentum"
OUTPUT_PATH = OUTPUT_DIR / "momentum_stocks.csv"

# --- indicator settings ---
ADX_PERIOD = 14
ADX_THRESHOLD = 25          # ADX >= this => trending (standard Wilder convention)
DI_GAP_MIN = 5              # +DI/-DI must differ by at least this much (clear direction)
BRIDGE_GAP_DAYS = 2         # bridge interruptions of up to this many non-trending days

# --- "no false signal" filters ---
MIN_TRADING_DAYS = 10
MIN_RETURN_PCT = 15.0
MIN_CONSISTENCY = 0.55          # share of days closing in the trend direction
MIN_AVG_TURNOVER = 5_00_00_000  # INR 5 crore average daily turnover
MAX_SINGLE_DAY_MOVE_PCT = 20.0  # drop runs containing an outsized single-day jump
STRUCTURAL_CA_KEYWORDS = ("bonus", "split", "demerger", "rights")
MAX_CALENDAR_GAP_DAYS = 7       # normal weekend/holiday gaps top out at ~5 days; anything
                                # bigger means missing/suspended data -- never bridge it


def load_price_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    numeric_cols = ["open", "high", "low", "close", "vwap", "traded_quantity", "turnover"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def split_into_segments(df: pd.DataFrame) -> list[pd.DataFrame]:
    """Split a symbol's daily series on abnormally large calendar-date gaps so a data
    hole (missing data / trading suspension) can never be stitched into one run."""
    gap_days = df["date"].diff().dt.days
    segment_id = (gap_days > MAX_CALENDAR_GAP_DAYS).cumsum()
    segments = [seg.reset_index(drop=True) for _, seg in df.groupby(segment_id)]
    return segments


def load_structural_ca_dates(symbol: str) -> set:
    ca_path = CA_DIR / f"{symbol}.csv"
    if not ca_path.exists():
        return set()
    df = pd.read_csv(ca_path)
    if "subject" not in df.columns or "exDate" not in df.columns:
        return set()
    mask = df["subject"].str.lower().str.contains("|".join(STRUCTURAL_CA_KEYWORDS), na=False)
    dates = pd.to_datetime(df.loc[mask, "exDate"], format="%d-%b-%Y", errors="coerce")
    return set(dates.dropna().dt.normalize())


def compute_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Wilder's smoothing (equivalent to an EMA with alpha = 1/period)
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_dm_smooth = pd.Series(plus_dm, index=df.index).ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus_dm_smooth = pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    plus_di = 100 * (plus_dm_smooth / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm_smooth / atr.replace(0, np.nan))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    out = df.copy()
    out["plus_di"] = plus_di
    out["minus_di"] = minus_di
    out["adx"] = adx
    out["daily_return_pct"] = close.pct_change() * 100
    return out


def classify_trending_days(df: pd.DataFrame) -> pd.Series:
    """Return a Series of 'up' / 'down' / None per day."""
    is_trending = (df["adx"] >= ADX_THRESHOLD) & ((df["plus_di"] - df["minus_di"]).abs() >= DI_GAP_MIN)
    direction = np.where(df["plus_di"] > df["minus_di"], "up", "down")
    return pd.Series(np.where(is_trending, direction, None), index=df.index)


def find_raw_runs(direction: pd.Series) -> list[tuple[int, int, str]]:
    """Merge consecutive same-direction trending days, bridging small gaps."""
    runs = []
    n = len(direction)
    i = 0
    while i < n:
        if direction.iloc[i] is None:
            i += 1
            continue
        d = direction.iloc[i]
        start = i
        j = i + 1
        last_trending = i
        while j < n:
            if direction.iloc[j] == d:
                last_trending = j
                j += 1
            elif direction.iloc[j] is None and (j - last_trending) <= BRIDGE_GAP_DAYS:
                j += 1
            else:
                break
        runs.append((start, last_trending, d))
        i = last_trending + 1
    return runs


def evaluate_run(df: pd.DataFrame, start: int, end: int, direction: str, ca_dates: set) -> dict | None:
    window = df.iloc[start : end + 1]
    trading_days = len(window)
    if trading_days < MIN_TRADING_DAYS:
        return None

    start_close = window["close"].iloc[0]
    end_close = window["close"].iloc[-1]
    if start_close <= 0:
        return None
    return_pct = (end_close - start_close) / start_close * 100
    if direction == "up" and return_pct < MIN_RETURN_PCT:
        return None
    if direction == "down" and return_pct > -MIN_RETURN_PCT:
        return None

    daily_returns = window["daily_return_pct"].iloc[1:]
    if daily_returns.abs().max() > MAX_SINGLE_DAY_MOVE_PCT:
        return None

    if direction == "up":
        consistency = (daily_returns > 0).mean()
    else:
        consistency = (daily_returns < 0).mean()
    if consistency < MIN_CONSISTENCY:
        return None

    avg_turnover = window["turnover"].mean()
    if pd.isna(avg_turnover) or avg_turnover < MIN_AVG_TURNOVER:
        return None

    window_dates = set(window["date"].dt.normalize())
    if window_dates & ca_dates:
        return None

    return {
        "start_date": window["date"].iloc[0].date(),
        "end_date": window["date"].iloc[-1].date(),
        "direction": direction,
        "trading_days": trading_days,
        "return_pct": round(return_pct, 2),
        "avg_adx": round(window["adx"].mean(), 2),
        "avg_turnover_cr": round(avg_turnover / 1_00_00_000, 2),
    }


def merge_adjacent(results: list[dict]) -> list[dict]:
    """Merge/deduplicate runs that touch or overlap (same symbol/direction already assumed)."""
    if not results:
        return results
    results = sorted(results, key=lambda r: r["start_date"])
    merged = [results[0]]
    for r in results[1:]:
        last = merged[-1]
        if r["direction"] == last["direction"] and r["start_date"] <= last["end_date"]:
            # keep the stronger (higher avg_adx) of the two overlapping runs
            if r["avg_adx"] > last["avg_adx"]:
                merged[-1] = r
        else:
            merged.append(r)
    return merged


def find_momentum_for_symbol(symbol: str, path: Path) -> list[dict]:
    df = load_price_data(path)
    ca_dates = load_structural_ca_dates(symbol)

    results = []
    for segment in split_into_segments(df):
        if len(segment) < MIN_TRADING_DAYS + ADX_PERIOD:
            continue

        segment = compute_adx(segment)
        segment = segment.iloc[ADX_PERIOD:].reset_index(drop=True)  # drop ADX warm-up period

        direction = classify_trending_days(segment)
        raw_runs = find_raw_runs(direction)

        for start, end, d in raw_runs:
            evaluated = evaluate_run(segment, start, end, d, ca_dates)
            if evaluated:
                evaluated["symbol"] = symbol
                results.append(evaluated)

    return merge_adjacent(results)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_files = sorted(INPUT_DIR.glob("*.csv"))
    total = len(csv_files)
    width = len(str(total))

    print(f"Found {total} CSV files")
    print(f"Output file: /{OUTPUT_PATH.relative_to(BASE_DIR.parent)}")
    print("\nScanning for momentum ...\n")

    all_results = []
    success = 0

    for i, csv_path in enumerate(csv_files, start=1):
        symbol = csv_path.stem
        label = f"[{i:0{width}}/{total}]  {symbol:<12}"
        try:
            runs = find_momentum_for_symbol(symbol, csv_path)
            all_results.extend(runs)
            print(f"{label}->  {len(runs)} run(s)")
            success += 1
        except Exception as exc:
            print(f"{label}->  Error ({exc})")

    all_results.sort(key=lambda r: (r["symbol"], r["start_date"]))

    columns = [
        "symbol",
        "start_date",
        "end_date",
        "direction",
        "trading_days",
        "return_pct",
        "avg_adx",
        "avg_turnover_cr",
    ]
    out_df = pd.DataFrame(all_results, columns=columns)
    out_df.to_csv(OUTPUT_PATH, index=False)

    print(f"\nProcessed {success}/{total} symbols")
    print(f"Found {len(all_results)} momentum run(s) -> {OUTPUT_PATH.relative_to(BASE_DIR.parent)}")


if __name__ == "__main__":
    main()
