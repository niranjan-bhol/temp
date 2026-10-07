import csv
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SYMBOLS_CSV = BASE_DIR / "misc" / "symbols.csv"
INSTRUMENTS_CSV = BASE_DIR / "data" / "instruments" / "instruments.csv"
OUTPUT_JSON = BASE_DIR / "data" / "symbols" / "symbols.json"

def read_symbols(path: Path):
	symbols = []
	seen = set()
    
	with path.open("r", newline="") as file:
		reader = csv.reader(file)
		for row in reader:
			if not row:
				continue
            
			symbol = row[0].strip()
			if not symbol:
				continue
            
			if symbol not in seen:
				symbols.append(symbol)
				seen.add(symbol)
    
	return symbols

def read_instrument_tokens(path: Path):
	token_by_symbol = {}
    
	with path.open("r", newline="") as file:
		reader = csv.DictReader(file)
		for row in reader:
			if (
				row.get("instrument_type") == "EQ"
				and row.get("segment") == "NSE"
				and row.get("exchange") == "NSE"
			):
				symbol = (row.get("tradingsymbol") or "").strip()
				token = (row.get("instrument_token") or "").strip()
                                
				if symbol and token and symbol not in token_by_symbol:
					token_by_symbol[symbol] = token
    
	return token_by_symbol

def main():
	symbols = read_symbols(SYMBOLS_CSV)
	instrument_tokens = read_instrument_tokens(INSTRUMENTS_CSV)
    
	output = {}
	missing = []
    
	for symbol in symbols:
		token = instrument_tokens.get(symbol)
		if token is None:
			missing.append(symbol)
			continue
		output[symbol] = token
    
	OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
	with OUTPUT_JSON.open("w") as file:
		json.dump(output, file, indent=2)
		file.write("\n")
    
	relative_output = f"/{BASE_DIR.name}/data/symbols/{OUTPUT_JSON.name}"
	print(f"Wrote {len(output)}/{len(symbols)} symbols to {relative_output}")

if __name__ == "__main__":
	main()
