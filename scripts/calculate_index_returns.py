import csv
import math
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SYMBOLS_PATH = BASE_DIR / "data" / "symbol" / "symbol2.txt"
INPUT_DIR = BASE_DIR / "data" / "nse" / "csv"
OUTPUT_DIR = BASE_DIR / "data" / "calculated" / "index_returns"

RETURN_PERIODS = range(1, 64)
RETURN_FIELDNAMES = [str(period) for period in RETURN_PERIODS]


def sanitize_filename(symbol):
    return re.sub(r"[^A-Za-z0-9]+", "_", symbol).strip("_")


def read_symbols():
    if not SYMBOLS_PATH.exists():
        raise FileNotFoundError(f"Index list not found: {SYMBOLS_PATH}")

    with open(SYMBOLS_PATH, encoding="utf-8") as file:
        symbols = [line.strip() for line in file if line.strip()]

    if not symbols:
        raise ValueError(f"No indices found in {SYMBOLS_PATH}")
    return symbols


def calculate_returns(input_path, output_path):
    with open(input_path, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames
        if not fieldnames or "date" not in fieldnames or "close" not in fieldnames:
            raise ValueError(f"Expected 'date' and 'close' columns in {input_path}")

        rows = list(reader)

    if any(fieldname in fieldnames for fieldname in RETURN_FIELDNAMES):
        raise ValueError(f"Input already contains return columns: {input_path}")

    closes = []
    for row_number, row in enumerate(rows, start=2):
        value = row.get("close", "")
        if value is None or not value.strip():
            closes.append(None)
            continue
        try:
            close = float(value)
        except ValueError as error:
            raise ValueError(
                f"Invalid close value at {input_path}:{row_number}: {value!r}"
            ) from error
        if not math.isfinite(close):
            raise ValueError(
                f"Invalid close value at {input_path}:{row_number}: {value!r}"
            )
        closes.append(close)

    output_fieldnames = ["date", "close", *RETURN_FIELDNAMES]
    for index, row in enumerate(rows):
        current_close = closes[index]
        for period in RETURN_PERIODS:
            previous_index = index - period
            return_value = ""
            if (
                current_close not in (None, 0)
                and previous_index >= 0
                and closes[previous_index] not in (None, 0)
            ):
                return_value = (
                    f"{(current_close / closes[previous_index] - 1) * 100:.2f}"
                )
            row[str(period)] = return_value

    with open(output_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=output_fieldnames)
        writer.writeheader()
        writer.writerows(
            {fieldname: row.get(fieldname, "") for fieldname in output_fieldnames}
            for row in rows
        )

    return len(rows)


def main():
    symbols = read_symbols()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for symbol in symbols:
        filename = f"{sanitize_filename(symbol)}.csv"
        input_path = INPUT_DIR / filename
        if not input_path.exists():
            raise FileNotFoundError(
                f"No historical CSV for index {symbol!r}: {input_path}"
            )

        row_count = calculate_returns(input_path, OUTPUT_DIR / filename)
        print(f"{symbol}: {row_count} rows -> {OUTPUT_DIR / filename}")

    print(f"Calculated {len(symbols)} indices; saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
