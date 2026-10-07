# Code & Data Documentation

This document explains, in plain English, exactly what every Python script under `scripts/` does (step by step), and documents the full structure of everything under `data/` — every folder, every file type, and (for CSVs) every column.

It is meant as a companion to the [README.md](../README.md), which describes the trading hypothesis and pipeline at a higher level. This file goes one level deeper: the actual processing logic inside each script and the exact shape of the data at each stage.

---

## Table of Contents

1. [Pipeline Overview](#pipeline-overview)
2. [Scripts — Code Logic](#scripts--code-logic)
   - [fetch_access_token.py](#fetch_access_tokenpy)
   - [fetch_instruments.py](#fetch_instrumentspy)
   - [generate_symbols.py](#generate_symbolspy)
   - [fetch_nse_data.py](#fetch_nse_datapy)
   - [json_to_csv_nse.py](#json_to_csv_nsepy)
   - [transform_csv.py](#transform_csvpy)
   - [extract_vwap.py](#extract_vwappy)
   - [fetch_historical_data.py](#fetch_historical_datapy)
   - [json_to_csv_zerodha.py](#json_to_csv_zerodhapy)
   - [filter_data.py](#filter_datapy)
   - [generate_trades_intraday.py](#generate_trades_intradaypy)
   - [generate_trades_overnight.py](#generate_trades_overnightpy)
   - [generate_results_intraday.py](#generate_results_intradaypy)
   - [generate_results_overnight.py](#generate_results_overnightpy)
   - [generate_results_30d.py](#generate_results_30dpy)
   - [generate_trades_30d.py](#generate_trades_30dpy)
   - [generate_capital_30d.py](#generate_capital_30dpy)
3. [Data Folder — Structure & File Formats](#data-folder--structure--file-formats)

---

## Pipeline Overview

The scripts run in this order, each one consuming the output of a previous step:

```
fetch_access_token.py
        │
        ▼
fetch_instruments.py
        │
        ▼
generate_symbols.py  (also reads misc/symbols.csv)
        │
        ├─────────────────────────────┐
        ▼                             ▼
fetch_nse_data.py            fetch_historical_data.py --interval minute
        │                             │
        ▼                             ▼
json_to_csv_nse.py            json_to_csv_zerodha.py
        │                             │
        ▼                             ▼
transform_csv.py               filter_data.py
        │                             │
        ▼                             │
extract_vwap.py                       │
        │                             │
        └───────────┬─────────────────┘
                     ▼
       generate_trades_intraday.py  /  generate_trades_overnight.py
                     │
                     ▼
      generate_results_intraday.py  /  generate_results_overnight.py

  (separate, intraday-only, 30-day-rolling capital simulation branch)
       generate_results_30d.py → generate_trades_30d.py → generate_capital_30d.py
```

There are two independent raw data sources that get combined:

- **NSE** (nseindia.com) — provides the **official daily VWAP** for each stock (`fetch_nse_data.py` → ... → `extract_vwap.py`).
- **Zerodha Kite API** — provides **1-minute OHLC candles** used to compute intraday open/high/low/close snapshots (`fetch_historical_data.py` → ... → `filter_data.py`).

The trade generators then join these two datasets by date to decide whether a stock touched its previous day's VWAP.

---

## Scripts — Code Logic

### `fetch_access_token.py`

**Purpose:** Logs into Zerodha Kite programmatically (username/password + TOTP 2FA) and saves an access token used to authenticate all later Kite API calls.

**Steps:**
1. Loads credentials from environment variables via `.env` (`API_KEY`, `API_SECRET`, `TOTP_KEY`, `USER_ID`, `USER_PASSWORD`).
2. `get_request_token(session)`:
   - POSTs `user_id` + `password` to Kite's `/api/login` endpoint, retrieving a `request_id`.
   - POSTs the `request_id` + a freshly generated TOTP code (via `pyotp.TOTP(TOTP_KEY).now()`) + `user_id` to `/api/twofa` to complete 2FA.
   - GETs the Kite Connect login URL (`kite.zerodha.com/connect/login?v=3&api_key=...`) without following redirects.
   - Follows the redirect chain manually (up to `MAX_REDIRECTS = 10` hops) until a `Location` header containing `request_token` is found; raises `RuntimeError` if the chain breaks (empty `Location`) or exceeds the redirect limit.
   - Extracts and returns the `request_token` query parameter from the final redirect URL.
3. `get_access_token(request_token)`: Uses the official `KiteConnect` SDK's `generate_session()` to exchange the request token + `API_SECRET` for an `access_token`.
4. `save_access_token(token)`: Writes the token as plain text to `data/auth/access_token.txt` (creates the directory if missing).
5. `login()` orchestrates steps 2–4 inside a single `requests.Session` (so login cookies persist across the login/2FA/redirect calls).
6. `main()` calls `login()` and prints a success message with the saved file's relative path, or prints `Error | <exception>` on any failure.

---

### `fetch_instruments.py`

**Purpose:** Downloads Zerodha Kite's master list of all tradable instruments (stocks, futures, options, etc.) as a single CSV. This is the lookup table used later to map trading symbols to Kite's internal `instrument_token` IDs.

**Steps:**
1. Reads the access token from `data/auth/access_token.txt`.
2. Sends a GET request to `https://api.kite.trade/instruments` with headers `Authorization: token {API_KEY}:{access_token}` and `X-Kite-Version: 3`.
3. Writes the raw CSV response body directly to `data/instruments/instruments.csv` (no parsing — Kite returns ready-made CSV text).
4. Prints the saved file's relative path, or `Error: <exception>` on failure.

---

### `generate_symbols.py`

**Purpose:** Builds `data/symbols/symbols.json`, a mapping of `{symbol: instrument_token}` for every symbol the research universe cares about (from `misc/symbols.csv`), resolved against the Kite instruments master list.

**Steps:**
1. `read_symbols(misc/symbols.csv)`: Reads the first column of every row, strips whitespace, skips blanks, and de-duplicates while preserving order.
2. `read_instrument_tokens(data/instruments/instruments.csv)`: Iterates every row of the Kite instruments CSV and keeps only rows where `instrument_type == "EQ"`, `segment == "NSE"`, and `exchange == "NSE"` (i.e. plain equity, cash-market listings — excludes futures/options/BSE listings). Builds a dict of `tradingsymbol → instrument_token`, keeping the first occurrence if a symbol appears more than once.
3. For every symbol from step 1, looks up its instrument token from step 2. Symbols with no match are collected into a `missing` list (not written to output, only implicitly reflected in the success count printed).
4. Writes the resulting `{symbol: token}` dict as pretty-printed JSON to `data/symbols/symbols.json`.
5. Prints `Wrote X/Y symbols to ...`.

---

### `fetch_nse_data.py`

**Purpose:** Downloads raw historical price/volume/deliverable data per symbol directly from the NSE website's internal API (this is the source of the **official daily VWAP** used throughout the project). NSE only returns ~90 days per request, so each symbol is fetched in 90-day chunks and the chunks are combined.

**Steps:**
1. `read_symbols()`: Loads `data/symbols/symbols.json` and returns just the list of symbol names (keys), skipping blanks.
2. `get_session()`: Creates a `requests.Session` with a spoofed mobile-Chrome `User-Agent` and an `accept`/`referer` header set, first visits `https://www.nseindia.com` (to obtain the anti-bot cookies NSE requires), then sleeps 1 second.
3. `date_chunks(start, end, days)`: Splits the full date range `2025-01-01` → yesterday into consecutive `CHUNK_DAYS = 90`-day windows, formatted `DD-MM-YYYY` (NSE's expected format).
4. `fetch_symbol(session, symbol, max_retries=3)`: For each 90-day chunk, calls NSE's `generateSecurityWiseHistoricalData` endpoint (`type=priceVolumeDeliverable&series=EQ`). Retries up to 3 times per chunk with exponential backoff (`2**attempt` seconds) on `HTTPError`, `ConnectionError`, or `ValueError` (covers malformed/HTML JSON responses); re-raises after the final attempt. Sleeps 0.5s between chunks. Collects all records across chunks into one list.
5. `save_json(data, path)`: Writes `{"data": [...]}` as indented JSON to `data/nse/json/{symbol}.json`.
6. `main()`:
   - Loops through every symbol, printing a progress label `[i/total] SYMBOL`.
   - Every 50 symbols, refreshes the session (re-fetches NSE's anti-bot cookies) since long-lived sessions tend to get rate-limited/blocked.
   - On failure for a symbol, retries once with a brand-new session before giving up and logging `Error`.
   - Sleeps 1 second between symbols regardless of outcome (rate-limit courtesy).
   - Prints a final `Successfully downloaded and saved data for X/Y symbols` summary.

---

### `json_to_csv_nse.py`

**Purpose:** Converts the raw per-symbol NSE JSON files into CSV, and separately extracts any embedded corporate-action (CA) records (dividends, bonuses, splits, etc.) into their own CSV.

**Steps:**
1. `parse_date(record)`: Parses the `mTIMESTAMP` field (format `DD-Mon-YYYY`, e.g. `01-Jan-2025`) into a `datetime` for sorting; returns `datetime.min` if parsing fails (so unparseable rows sort first rather than crashing).
2. `save_csv(data, path)`:
   - Sorts all records by parsed date.
   - Collects the union of all field names present across records (since NSE's raw records occasionally have inconsistent keys), **excluding** the `CA` key (corporate actions are handled separately).
   - Writes a CSV with sorted column names, using `extrasaction="ignore"` so any stray fields don't crash the writer.
   - Output: `data/nse/csv/{symbol}.csv`.
3. `save_ca_csv(data, path, symbol)`:
   - For each raw record that has a non-empty `CA` list, flattens each corporate-action entry into its own row, tagging it with the record's `mTIMESTAMP`.
   - Writes these flattened CA rows to `data/nse/csv_ca/{symbol}.csv` (only created if the symbol actually has at least one corporate action).
4. `main()`: Iterates every JSON file in `data/nse/json/`, converts it, and prints a per-symbol row count (plus a `(N CA)` suffix when corporate actions were found). Prints final success counts for both CSV and CA extraction.

---

### `transform_csv.py`

**Purpose:** Cleans up and renames the raw NSE CSV columns (which use NSE's internal field names like `CH_OPENING_PRICE`) into simple, consistent names (`open`, `high`, `low`, `close`, `vwap`, etc.), and normalizes the date format.

**Steps:**
1. Defines `COLUMN_MAPPING`, a fixed dict translating each raw NSE column to a clean name:
   - `mTIMESTAMP → date`, `CH_OPENING_PRICE → open`, `CH_TRADE_HIGH_PRICE → high`, `CH_TRADE_LOW_PRICE → low`, `CH_CLOSING_PRICE → close`, `VWAP → vwap`, `CH_TOT_TRADED_QTY → traded_quantity`, `COP_DELIV_QTY → deliverable_quantity`, `COP_DELIV_PERC → deliverable_percentage`, `CH_TOT_TRADED_VAL → turnover`, `CH_TOTAL_TRADES → trades`.
2. `transform_date(date_str)`: Converts `DD-Mon-YYYY` → ISO `YYYY-MM-DD`; returns the original string unchanged if parsing fails.
3. `transform_csv(input_path, output_path)`: Reads every row of the raw CSV, builds a new row using only the mapped columns (in mapping order), converting the date column via step 2, and writes the result.
4. `main()`: Iterates every CSV in `data/nse/csv/`, transforms it, writes to `data/nse/csv_transformed/{symbol}.csv`, and prints per-file row counts and a final success summary.

---

### `extract_vwap.py`

**Purpose:** Produces the actual "previous day VWAP" signal used by the trading strategy: for every trading day, what was VWAP *the day before*.

**Steps:**
1. Reads each transformed NSE CSV, keeping only rows with a non-blank `date`.
2. Sorts rows chronologically by `date`.
3. Walks the sorted rows carrying a `prev_vwap` variable forward: for each row, it emits `{date, vwap, prev_vwap}` where `prev_vwap` is the **previous row's** `vwap` value (empty string for the very first row, since it has no prior day).
4. Writes result to `data/nse/vwap/{symbol}.csv`.
5. `main()`: Iterates all CSVs in `data/nse/csv_transformed/`, processes each, prints per-file row counts and a final summary.

---

### `fetch_historical_data.py`

**Purpose:** Downloads 1-minute OHLC candle data for every symbol from the Zerodha Kite historical-data API. This is the source of intraday open/high/low/close prices used to check if/when price touched the previous VWAP.

**Steps:**
1. Parses a required `--interval` CLI argument (choices: `minute`, `3minute`, `5minute`, ... `day`); the pipeline is run with `--interval minute`.
2. Loads the Kite access token and the `symbols.json` (`symbol → instrument_token`) map.
3. `setup_output_directory()`: Ensures `data/historical/json/` exists and **deletes any existing `.json` files in it** before starting (clean-slate behavior — re-running this script wipes prior downloads).
4. Per-interval `MAX_DAYS` limits how many days one API call can cover (e.g. `minute` → 60 days, `day` → 2000 days) — Kite's API caps the range depending on interval granularity.
5. `generate_date_chunks(start, end, max_days)`: Splits `START_DATE = 2025-01-01` through yesterday into consecutive chunks no longer than `max_days`.
6. `fetch_historical_data(...)`: Calls `GET /instruments/historical/{instrument_token}/{interval}` with `Authorization: token {API_KEY}:{access_token}`, `from`/`to` timestamps, `continuous=0`, `oi=1` (include open interest). Returns `None` and prints the error on any request exception (caller treats a failed chunk as simply missing).
7. `merge_candle_data(chunks_data)`: Concatenates candles from all successful chunks, de-duplicates by timestamp (last write wins, though overlaps shouldn't occur since chunks are contiguous), and sorts by timestamp.
8. `process_symbol(...)`: For one symbol — computes the date range, splits into chunks, fetches each chunk (printing candle counts as it goes), merges multi-chunk results (or uses the single chunk directly), and saves `{"status": "success", "data": {"candles": [...]}}` to `data/historical/json/{symbol}.json`.
9. `main()`: Iterates every symbol in `symbols.json`, calling `process_symbol` for each, and prints a final `Successfully downloaded data for X/Y symbols` summary. Handles `KeyboardInterrupt` gracefully.

**Candle format:** each candle is a 7-element list: `[timestamp, open, high, low, close, volume, open_interest]`, where `timestamp` is an ISO-8601 string with `+0530` (IST) offset, e.g. `"2025-01-01T09:15:00+0530"`.

---

### `json_to_csv_zerodha.py`

**Purpose:** Converts the raw per-symbol Zerodha candle JSON into flat CSV files (one row per minute candle).

**Steps:**
1. For every JSON file in `data/historical/json/`, loads it and pulls out `data.candles` (the list of 7-element candle arrays).
2. Skips (with a printed message) files that have no candle data.
3. Writes a CSV with header `timestamp, open, high, low, close, volume, open_interest`, writing each candle array as one CSV row directly (no transformation — the array order already matches the header order).
4. Output: `data/historical/csv/{symbol}.csv`.
5. Prints per-file row counts and a final `Successfully converted JSON data for X/Y symbols to CSV` summary.

---

### `filter_data.py`

**Purpose:** Collapses a full day of 1-minute candles down to a small set of meaningful daily snapshots: the price at market open (09:15), and at two pre-close checkpoints (15:18 and 15:28), plus the day's session/day high and low. This is the data structure the trade-generation scripts actually consume (much smaller & easier to reason about than raw minute candles).

**Steps:**
1. `TARGET_TIMES = ["09:15", "15:18", "15:28"]` with a `FALLBACK_DIRECTION` per time:
   - `09:15 → "next"`: if there's no candle at exactly 09:15, use the next available candle after it (handles missing opening ticks).
   - `15:18 → "previous"` and `15:28 → "previous"`: if there's no exact candle, use the most recent candle *before* that time (handles the case where trading ends slightly before 15:30 for a given minute bucket).
2. `extract_date_and_time(timestamp)`: Splits an ISO timestamp like `2025-01-01T09:15:00+0530` into `("2025-01-01", "09:15")`.
3. Reads all rows of one symbol's CSV, grouping them into `rows_by_date: {date: [(hhmm, {open,high,low,close,volume}), ...]}`.
4. For each date (sorted), sorts that day's rows by time and:
   - `find_row_for_time(...)`: Finds the exact match for each target time, or falls back per the direction rule above (`next` = first candle strictly after; `previous` = last candle strictly before). If neither an exact match nor a fallback candle exists, values for that time slot stay blank.
   - `compute_session_high_low(...)`: Computes max(high)/min(low) across all candles between `09:15` and `15:18` inclusive (the "regular session").
   - `compute_day_high_low(...)`: Computes max(high)/min(low) across all candles between `09:15` and `15:28` inclusive (the "full day" including the pre-close window).
5. Builds one output row per date with columns: `date`, `0915_open/high/low/close/volume`, `1518_open/high/low/close/volume`, `1528_open/high/low/close/volume`, `session_high`, `session_low`, `day_high`, `day_low`.
6. Writes to `data/historical/filtered/{symbol}.csv`.
7. `main()`: Iterates all CSVs in `data/historical/csv/`, prints per-file row counts and a final summary.

---

### `generate_trades_intraday.py`

**Purpose:** Simulates the core intraday strategy — "does the stock touch yesterday's VWAP today?" — for every trading day of every symbol, and records the outcome as a trade row.

**Strategy logic (per day):**
1. Looks up that day's `prev_vwap` (previous day's VWAP) from the `vwap/{symbol}.csv` file produced by `extract_vwap.py`. Skips the day entirely if there's no `prev_vwap` (e.g. first trading day in the dataset).
2. Reads `open` (09:15 price), `high`/`low` (session high/low, 09:15–15:18), and `close` (15:18 price) from the filtered CSV.
3. **Skip-band check:** if `|open - prev_vwap| <= 0.1% of prev_vwap` (`SKIP_BAND_PERCENT = 0.001`), the stock opened essentially *at* its VWAP already — there's no meaningful directional trade to take, so the row is recorded as `trade_type = "SKIP"` with all trade fields left blank.
4. Otherwise, direction is determined by where the open is relative to `prev_vwap`:
   - `open < prev_vwap` → **LONG** (expect price to rise up to touch VWAP).
   - `open > prev_vwap` → **SHORT** (expect price to fall down to touch VWAP).
   - (Equality here is unreachable in practice since the skip-band check above already catches near-equal/equal opens — this branch is a defensive no-op `continue`.)
5. `entry = open`, `target = prev_vwap`.
6. **Exit logic:** if the day's session range (`low` to `high`) contains `prev_vwap`, the trade is considered to have **hit target** and `exit = prev_vwap` exactly. Otherwise the trade exits at the 15:18 `close` price (target not hit).
7. `target_hit = (exit == prev_vwap)`.
8. P&L: for LONG, `pnl_absolute = exit - entry`; for SHORT, `pnl_absolute = entry - exit`. `pnl_percent = pnl_absolute / entry * 100`.
9. Appends a full row: `date, open, high, low, close, prev_vwap, trade_type, entry, target, exit, target_hit, pnl_absolute, pnl_percent`.
10. `main()`: For every symbol, joins its `filtered/{symbol}.csv` with `nse/vwap/{symbol}.csv`, generates all trade rows, and writes them to `data/backtests/trades/intraday/{symbol}.csv`. Prints, per symbol, the count of non-SKIP ("active") trades, and a final success summary.

---

### `generate_trades_overnight.py`

**Purpose:** Simulates the overnight variant of the strategy — "does a stock that closed away from its own VWAP revert to touch that VWAP on the *next* trading day?" — held from one day's close to the next day's session.

**Strategy logic (per consecutive day pair `day1 → day2`):**
1. Looks up `day2`'s `prev_vwap` (i.e., `day1`'s VWAP) from the vwap CSV. Skips the pair if missing.
2. `prev_close` = `day1`'s 15:28 close (the position is notionally entered at/near the previous day's close). `open`/`high`/`low`/`close` for `day2` use the **day-level** high/low (`day_high`/`day_low`, i.e. the 09:15–15:28 window) rather than the intraday script's session-level range.
3. **Skip-band check:** if `|prev_close - prev_vwap| <= 0.5% of prev_vwap` (`SKIP_BAND_PERCENT = 0.005`, a wider band than the intraday version), record as `trade_type = "SKIP"`.
4. **This strategy is intentionally LONG-only** — there is no SHORT branch. The only entries taken are ones where the position is bought at `prev_close`, expecting price to rise to `target = prev_vwap` by the next day. (This is a deliberate design choice, not a missing feature.)
5. **Exit logic:** if `day2`'s day-range (`low` to `high`) contains the target, `exit = target` (target hit); otherwise `exit = close` (day2's 15:28 close).
6. `pnl_absolute = exit - entry` (long-only, so no sign flip needed); `pnl_percent = pnl_absolute / entry * 100`.
7. Trade rows include an extra `prev_close` column (not present in the intraday version) since the entry price is the *previous* day's close, distinct from `open`.
8. `main()`: Same structure as the intraday script — reads `filtered/{symbol}.csv` + `vwap/{symbol}.csv`, writes to `data/backtests/trades/overnight/{symbol}.csv`.

---

### `generate_results_intraday.py`

**Purpose:** Aggregates the per-day intraday trade rows (from `generate_trades_intraday.py`) into per-symbol summary statistics over three rolling lookback windows: year, quarter, month (all measured back from *today*, i.e. the day the script is run).

**Steps:**
1. `TIMEFRAME_DAYS = {"year": 365, "quarter": 91, "month": 30}`. `get_timeframes()` converts these into concrete `(start_date, end_date)` string pairs anchored on `date.today()`.
2. Loads every symbol's full trade history once into memory (`all_trades`), keyed by symbol.
3. `generate_summary(symbol, trades, start_date, end_date)`: Filters trades to the `[start_date, end_date]` inclusive range, drops `SKIP` rows, and computes:
   - `trade_count` (non-skip trades in range)
   - `target_hit_count` / `target_hit_percent` (% of trades where `target_hit == "true"`)
   - `total_pnl_percent` (sum of `pnl_percent`) and `average_pnl_percent` (mean).
   - Returns `None` if there are no rows at all in the date range (symbol excluded from that timeframe's output).
4. For each of the 3 timeframes, builds one summary row per symbol and writes them to `data/results/intraday/{timeframe}.csv` (only if at least one symbol produced a summary).
5. Prints per-symbol trade counts and a final per-timeframe success summary.

---

### `generate_results_overnight.py`

**Purpose:** Identical logic to `generate_results_intraday.py`, but reads from `data/backtests/trades/overnight/` and writes to `data/results/overnight/{timeframe}.csv`. (By design there is no `prev_close` column needed in the summary — the code is a straight duplicate of the intraday summary logic on different input/output paths.)

---

### `generate_results_30d.py`

**Purpose:** First stage of the 30-day rolling top-N capital simulation. For every symbol, computes a **trailing 30-calendar-day** rolling performance summary anchored on each trading day, used later to *rank* symbols for stock selection — as opposed to the fixed-window (year/quarter/month) summaries above.

**Steps:**
1. `WINDOW_DAYS = 30` (calendar days, not trading days — roughly 19–22 trading days depending on holidays/weekends).
2. `generate_summary(trades, start_date, end_date)`: Same trade-count/target-hit/pnl math as the fixed-timeframe scripts, but critically the date filter is **`start_date <= t["date"] < end_date`** — the current day (`end_date`) is *excluded*. This prevents a day's own outcome from leaking into that same day's selection metric (a bug that existed earlier and was fixed — see repo memory).
3. `generate_rolling_results(trades)`:
   - Determines `cutoff_date = first_trade_date + 30 days` — no rolling summary is produced until at least one full window of history exists.
   - For every trade dated on/after the cutoff, computes a 30-day trailing window `[current_date - 30 days, current_date)` and calls `generate_summary` on it, producing one result row per qualifying trading day: `{date, trade_count, target_hit_count, target_hit_percent, total_pnl_percent, average_pnl_percent}`.
4. `main()`: For every symbol's intraday trades file, computes the rolling results and writes them to `data/backtests/30d_rolling/results/{symbol}.csv`. Prints per-symbol row counts and a final summary.

---

### `generate_trades_30d.py`

**Purpose:** Second stage — for every date, ranks all eligible symbols by their trailing 30-day performance metric and selects the top 10, then pulls each selected symbol's **actual trade** for that specific date (i.e., "if I had picked today's top-10-by-recent-performance stocks, which trades would I actually have taken?").

**Steps:**
1. `TOP_N = 10`, `METRICS = ["target_hit_percent", "average_pnl_percent"]` (two independent ranking strategies are evaluated), `MIN_TRADE_COUNT = 15` (a symbol's trailing-30d `trade_count` must be at least 15 to be eligible — avoids ranking symbols with too few trades, which produces noisy/unreliable percentages).
2. `load_results()`: Reads every `data/backtests/30d_rolling/results/{symbol}.csv` and re-indexes the data by date: `date_map[date] = [{symbol, trade_count, target_hit_percent, average_pnl_percent}, ...]` across all symbols.
3. `load_trades()`: Reads every symbol's full intraday trade history (`data/backtests/trades/intraday/{symbol}.csv`) into `trades_map[symbol][date] = trade_row`, for fast lookup.
4. `get_trade_fieldnames()`: Derives the output CSV's column order from one sample intraday trades file's header (minus `date`, plus a leading `symbol` column).
5. For every date (chronological order):
   - Filters that date's candidate symbols to those meeting `MIN_TRADE_COUNT`.
   - For **each** of the two metrics independently: sorts eligible symbols descending by that metric, takes the top 10, and for each selected symbol looks up its actual trade row for that date (`build_rows`). Symbols with no trade recorded for that exact date are silently skipped.
   - Writes the resulting rows (if any) to `data/backtests/30d_rolling/trades/{metric}/{date}.csv` — i.e. one output CSV per date per ranking metric.
6. Prints per-date counts for both metrics and a final summary.

---

### `generate_capital_30d.py`

**Purpose:** Third stage — simulates actually trading the top-10 picks each day with a real, compounding capital base, equally weighted across the 10 stocks.

**Steps:**
1. `STARTING_CAPITAL = 1_00_00_000` (₹1 crore). Runs the simulation once per `METRICS` entry (`target_hit_percent`, `average_pnl_percent`) independently, each starting fresh from the same capital.
2. `simulate(metric)`:
   - Iterates the per-date top-10 trade files (`data/backtests/30d_rolling/trades/{metric}/*.csv`) in filename (chronological) order.
   - Filters out any `SKIP` rows (`active_trades`).
   - If there are active trades that day: splits the current capital equally across them (`allocation = capital / num_stocks`), computes `quantity = floor(allocation / entry_price)` per stock (whole shares only — no fractional shares), and sums `quantity * pnl_absolute` across all stocks for the day's `total_pnl`.
   - Tracks `zero_quantity_count`: how many of the day's picks got `quantity == 0` because the allocation per stock was smaller than one share's price (informational only — these already contribute ₹0 to `total_pnl` so they don't change the math, just flagged for visibility).
   - Compounds: `capital += total_pnl` carries forward as next day's starting capital.
   - If there are no active trades that day, capital carries forward unchanged (`allocation = 0`, `total_pnl = 0`).
   - Records one row per day: `{date, trade_count, capital_start, allocation_per_stock, zero_quantity_count, total_pnl, capital_end}`.
3. `main()`: Runs `simulate()` for each metric and writes results to `data/results/30d_rolling/{metric}.csv`. Prints per-day running capital and a final capital figure per metric.

**Note:** This 30-day-rolling capital simulation only exists for the **intraday** strategy — there is intentionally no overnight equivalent.

---

## Data Folder — Structure & File Formats

```
data/
├── auth/
│   └── access_token.txt
├── instruments/
│   └── instruments.csv
├── symbols/
│   └── symbols.json
├── nse/
│   ├── json/{symbol}.json
│   ├── csv/{symbol}.csv
│   ├── csv_ca/{symbol}.csv
│   ├── csv_transformed/{symbol}.csv
│   └── vwap/{symbol}.csv
├── historical/
│   ├── json/{symbol}.json          (currently empty — see note below)
│   ├── csv/{symbol}.csv            (currently empty — see note below)
│   └── filtered/{symbol}.csv
├── backtests/
│   ├── trades/
│   │   ├── intraday/{symbol}.csv
│   │   └── overnight/{symbol}.csv
│   └── 30d_rolling/
│       ├── results/{symbol}.csv
│       └── trades/
│           ├── target_hit_percent/{date}.csv
│           └── average_pnl_percent/{date}.csv
└── results/
    ├── intraday/{year,quarter,month}.csv
    ├── overnight/{year,quarter,month}.csv
    └── 30d_rolling/{target_hit_percent,average_pnl_percent}.csv
```

### `data/auth/`

- **`access_token.txt`** — Plain text file containing only the current Zerodha Kite `access_token` string (no newline formatting, no JSON). Produced by `fetch_access_token.py`; read by `fetch_instruments.py` and `fetch_historical_data.py`. Tokens expire daily and must be regenerated each trading day.

### `data/instruments/instruments.csv`

Raw, unmodified CSV dump from Kite's `/instruments` endpoint — covers **every** instrument Kite trades (equities, futures, options, currencies, commodities, across NSE/BSE/NFO/BFO/MCX/CDS). Columns:

| Column | Description |
|---|---|
| `instrument_token` | Kite's internal numeric ID for this instrument (used in historical-data API calls) |
| `exchange_token` | Exchange-assigned numeric token |
| `tradingsymbol` | Ticker symbol as traded on the exchange (e.g. `RELIANCE`, `BANKEX26SEPFUT`) |
| `name` | Company/underlying full name |
| `last_price` | Last traded price at time of download (usually `0` for this static reference file) |
| `expiry` | Expiry date for derivatives; blank for equities |
| `strike` | Option strike price; `0` for non-options |
| `tick_size` | Minimum price movement |
| `lot_size` | Contract lot size (1 for equities) |
| `instrument_type` | `EQ` (equity), `FUT` (futures), `CE`/`PE` (call/put options), etc. |
| `segment` | Market segment, e.g. `NSE`, `BFO-FUT`, `NFO-OPT` |
| `exchange` | `NSE`, `BSE`, `NFO`, `BFO`, `MCX`, `CDS` |

Only rows with `instrument_type=EQ`, `segment=NSE`, `exchange=NSE` are used by `generate_symbols.py` (plain NSE cash-market equities).

### `data/symbols/symbols.json`

A single JSON object mapping `{tradingsymbol: instrument_token}` (token as a string), one entry per resolvable Nifty-500 symbol from `misc/symbols.csv`. Example:
```json
{
  "360ONE": "3343617",
  "3MINDIA": "121345",
  "AADHARHFC": "6074625"
}
```
This is the master symbol list every downstream fetch/processing script iterates over.

### `data/nse/json/{symbol}.json`

Raw NSE API responses, one file per symbol, produced by `fetch_nse_data.py`. Shape: `{"data": [record, record, ...]}`, where each `record` is NSE's raw historical price/volume/deliverable object with fields like `CH_OPENING_PRICE`, `CH_CLOSING_PRICE`, `VWAP`, `mTIMESTAMP` (format `DD-Mon-YYYY`), and optionally a `CA` list of corporate-action sub-objects for that date.

### `data/nse/csv/{symbol}.csv`

Direct CSV conversion of the above JSON (via `json_to_csv_nse.py`), sorted by date, with the `CA` field stripped out. Columns are the union of all raw NSE field names seen, alphabetically sorted, e.g.:

`CH_CLOSING_PRICE, CH_LAST_TRADED_PRICE, CH_OPENING_PRICE, CH_PREVIOUS_CLS_PRICE, CH_SERIES, CH_SYMBOL, CH_TIMESTAMP, CH_TOTAL_TRADES, CH_TOT_TRADED_QTY, CH_TOT_TRADED_VAL, CH_TRADE_HIGH_PRICE, CH_TRADE_LOW_PRICE, COP_DELIV_PERC, COP_DELIV_QTY, VWAP, mTIMESTAMP`

Key columns: `CH_OPENING_PRICE`/`CH_TRADE_HIGH_PRICE`/`CH_TRADE_LOW_PRICE`/`CH_CLOSING_PRICE` (daily OHLC), `VWAP` (official NSE VWAP for the day), `CH_TOT_TRADED_QTY` (volume), `COP_DELIV_QTY`/`COP_DELIV_PERC` (delivery volume/%), `CH_TOT_TRADED_VAL` (turnover ₹), `CH_TOTAL_TRADES` (trade count), `mTIMESTAMP` (date, `DD-Mon-YYYY`).

### `data/nse/csv_ca/{symbol}.csv`

Only created for symbols that had at least one corporate action in the fetched range. Each row is one flattened corporate-action event, tagged with the NSE record date it was attached to (`mTIMESTAMP`). Columns (alphabetical): `bcEndDate, bcStartDate, caBroadcastDate, comp, exDate, faceVal, ind, isin, mTIMESTAMP, ndEndDate, ndStartDate, recDate, series, subject, symbol`. `subject` holds a human-readable description, e.g. `"Dividend - Rs 22 Per Share"` or `"Bonus 1:1"`.

### `data/nse/csv_transformed/{symbol}.csv`

Cleaned/renamed version of `data/nse/csv/` (via `transform_csv.py`). Columns: `date` (ISO `YYYY-MM-DD`), `open`, `high`, `low`, `close`, `vwap`, `traded_quantity`, `deliverable_quantity`, `deliverable_percentage`, `turnover`, `trades`.

### `data/nse/vwap/{symbol}.csv`

The key derived signal (via `extract_vwap.py`). Columns: `date`, `vwap` (that day's official VWAP), `prev_vwap` (the previous trading day's VWAP — blank for the first row in the file). This `prev_vwap` value is the target price the whole strategy is built around.

### `data/historical/json/{symbol}.json` — currently empty (expected structure)

Populated by `fetch_historical_data.py --interval minute`, one file per symbol, containing merged 1-minute OHLC(+OI) candles from the Zerodha Kite historical API for the full backtest period.

Expected structure:
```json
{
  "status": "success",
  "data": {
    "candles": [
      [
        "2025-01-01T09:15:00+0530",
        30400,
        30667.9,
        30400,
        30595.65,
        32,
        0
      ],
      [
        "2025-01-01T09:16:00+0530",
        30595.65,
        30595.65,
        30485,
        30590,
        151,
        0
      ]
    ]
  }
}
```
Each candle array is `[timestamp, open, high, low, close, volume, open_interest]`. `timestamp` is ISO-8601 with the `+0530` (IST) offset. File is named after the symbol, e.g. `3MINDIA.json`.

### `data/historical/csv/{symbol}.csv` — currently empty (expected structure)

Flat CSV conversion of the JSON above (via `json_to_csv_zerodha.py`), one row per 1-minute candle, one file per symbol.

Expected structure (example `3MINDIA.csv`):
```
timestamp,open,high,low,close,volume,open_interest
2025-01-01T09:15:00+0530,30400,30667.9,30400,30595.65,32,0
2025-01-01T09:16:00+0530,30595.65,30595.65,30485,30590,151,0
```
Columns: `timestamp` (ISO-8601, `+0530` offset), `open`, `high`, `low`, `close`, `volume`, `open_interest`.

### `data/historical/filtered/{symbol}.csv`

One row per trading **day** (not per minute) — the condensed daily snapshot produced by `filter_data.py` from the raw minute candles. Columns:

| Column | Meaning |
|---|---|
| `date` | Trading date (`YYYY-MM-DD`) |
| `0915_open/high/low/close/volume` | The 1-minute candle at (or immediately after) 09:15 — market open |
| `1518_open/high/low/close/volume` | The 1-minute candle at (or immediately before) 15:18 — "session close" checkpoint |
| `1528_open/high/low/close/volume` | The 1-minute candle at (or immediately before) 15:28 — "day close" checkpoint |
| `session_high` / `session_low` | Max high / min low across all candles from 09:15–15:18 |
| `day_high` / `day_low` | Max high / min low across all candles from 09:15–15:28 |

### `data/backtests/trades/intraday/{symbol}.csv`

One row per trading day — the simulated intraday VWAP-touch trade outcome, produced by `generate_trades_intraday.py`. Columns: `date, open, high, low, close, prev_vwap, trade_type (LONG/SHORT/SKIP), entry, target, exit, target_hit (true/false), pnl_absolute, pnl_percent`. Trade fields are blank when `trade_type = SKIP`.

### `data/backtests/trades/overnight/{symbol}.csv`

One row per consecutive trading-day pair — the simulated overnight VWAP-reversion trade outcome, produced by `generate_trades_overnight.py`. Columns: `date, open, high, low, close, prev_close, prev_vwap, trade_type (TRADE/SKIP — long-only, no SHORT), entry, target, exit, target_hit (true/false), pnl_absolute, pnl_percent`. `entry` equals `prev_close` (position notionally opened at prior day's close).

### `data/backtests/30d_rolling/results/{symbol}.csv`

Trailing 30-calendar-day rolling performance summary per symbol per day, produced by `generate_results_30d.py` (excludes each row's own day from its own window). Columns: `date, trade_count, target_hit_count, target_hit_percent, total_pnl_percent, average_pnl_percent`.

### `data/backtests/30d_rolling/trades/{target_hit_percent,average_pnl_percent}/{date}.csv`

One CSV per calendar date per ranking metric, containing that date's top-10 selected symbols' actual trades, produced by `generate_trades_30d.py`. Columns: `symbol` followed by the same trade columns as `backtests/trades/intraday/{symbol}.csv` minus `date` (i.e. `symbol, open, high, low, close, prev_vwap, trade_type, entry, target, exit, target_hit, pnl_absolute, pnl_percent`).

### `data/results/intraday/{year,quarter,month}.csv` and `data/results/overnight/{year,quarter,month}.csv`

One row per symbol — fixed-window (trailing 365/91/30 calendar days from today) performance summary, produced by `generate_results_intraday.py` / `generate_results_overnight.py`. Columns: `symbol, trade_count, target_hit_count, target_hit_percent, total_pnl_percent, average_pnl_percent`.

### `data/results/30d_rolling/{target_hit_percent,average_pnl_percent}.csv`

One row per trading day — the simulated compounding capital curve from equally-weighting each day's top-10 picks, produced by `generate_capital_30d.py`. Columns: `date, trade_count, capital_start, allocation_per_stock, zero_quantity_count, total_pnl, capital_end`. `capital_end` of one row equals `capital_start` of the next (compounding day over day, starting from ₹1,00,00,000).

---

## Related, Non-`data/` Inputs

- **`misc/symbols.csv`** — Single-column CSV (no header) listing the Nifty-500 tradingsymbols the whole pipeline is scoped to (e.g. `360ONE`, `3MINDIA`, `AADHARHFC`, ...). This is the seed list consumed by `generate_symbols.py`; everything under `data/` is ultimately derived from resolving these symbols against Kite's instrument master and then fetching/processing their price data.
