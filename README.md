# Previous Day VWAP Touch

## Hypothesis

Stocks tend to touch their previous day's VWAP (Volume Weighted Average Price) during the current trading day. If the stock opens below the previous VWAP, it will rise to touch it (LONG). If it opens above, it will fall to touch it (SHORT).

Stocks that close away from their own VWAP tend to revert to touch it on the following day (LONG, held overnight).

---

## Data

- **Universe:** Nifty 500 stocks
- **VWAP source:** NSE historical price-volume-deliverable data (daily)
- **OHLC source:** Zerodha Kite historical API (1-minute candles), used for entry/exit prices and day high/low
- **Period:** 01 Jan 2025 – 31 Aug 2026
- **Format:** Fetched as JSON → converted to CSV → transformed/filtered to clean CSV

---

## Pipeline

```
# Auth & symbol setup
scripts/fetch_access_token.py         # Log in to Zerodha Kite → data/auth/access_token.txt
scripts/fetch_instruments.py          # Download Kite instruments list → data/instruments/instruments.csv
scripts/generate_symbols.py           # Map Nifty 500 symbols → instrument tokens → data/symbols/symbols.json

# NSE data → previous day VWAP
scripts/fetch_nse_data.py             # Fetch raw JSON from NSE (90-day chunks per symbol)
scripts/json_to_csv_nse.py            # Convert JSON → CSV (+ corporate actions → csv_ca/)
scripts/transform_csv.py              # Rename & clean columns → csv_transformed/
scripts/extract_vwap.py               # Carry forward each day's VWAP as next day's prev_vwap → nse/vwap/

# Zerodha data → intraday OHLC
scripts/fetch_historical_data.py --interval minute   # Fetch 1-minute candles from Kite → historical/json/
scripts/json_to_csv_zerodha.py        # Convert JSON → CSV → historical/csv/
scripts/filter_data.py                # Extract 09:15, 15:18 & 15:28 snapshots + session/day high-low → historical/filtered/

# Trades & results
scripts/generate_trades_intraday.py   # Combine filtered OHLC + prev_vwap → backtests/trades/intraday/<symbol>.csv
scripts/generate_trades_overnight.py  # Combine filtered OHLC + prev_vwap → backtests/trades/overnight/<symbol>.csv
scripts/generate_results_intraday.py  # Summarise intraday trades by month/quarter/year → results/intraday/*.csv
scripts/generate_results_overnight.py # Summarise overnight trades by month/quarter/year → results/overnight/*.csv
```

---

## Trade Logic

### Intraday

#### Entry

| Condition | Trade |
|-----------|-------|
| 09:15 open < Previous day VWAP | LONG at 09:15 open |
| 09:15 open > Previous day VWAP | SHORT at 09:15 open |

- Entry price is the open of the 09:15 1-minute candle (falls back to the next available candle if 09:15 is missing).

#### Skip

- If `|open − prev_vwap| <= 0.1%` of prev_vwap, the day is **skipped** (open too near to target).

#### Target / Exit

- **Target:** Previous day's VWAP
- **Exit:** If the VWAP level was touched between 09:15 and 15:18 (`session_low <= prev_vwap <= session_high`), exit at prev_vwap. Otherwise exit at the 15:18 close (falls back to the previous available candle if 15:18 is missing).

### Overnight

#### Entry

| Condition | Trade |
|-----------|-------|
| Always | LONG at previous day's 15:28 close |

- Entry price is the previous day's 15:28 close (falls back to the previous available candle if 15:28 is missing).
- The target VWAP is the *same* day's VWAP as the entry close (i.e. `prev_vwap` relative to the next trading day).

#### Skip

- If `|prev_close − prev_vwap| <= 0.5%` of prev_vwap, the day is **skipped** (close too near to target).

#### Target / Exit

- **Target:** The entry day's own VWAP
- **Exit:** If the target was touched at any point during the next day's full session (`day_low <= prev_vwap <= day_high`), exit at prev_vwap. Otherwise exit at the next day's 15:28 close (falls back to the previous available candle if 15:28 is missing).

---

## Results

| Period | Range | Intraday File | Overnight File |
|--------|-------|----------------|-----------------|
| Year | 01 Sep 2025 – 31 Aug 2026 | `results/intraday/year.csv` | `results/overnight/year.csv` |
| Quarter | 01 Jun 2026 – 31 Aug 2026 | `results/intraday/quarter.csv` | `results/overnight/quarter.csv` |
| Month | 01 Aug 2026 – 31 Aug 2026 | `results/intraday/month.csv` | `results/overnight/month.csv` |

