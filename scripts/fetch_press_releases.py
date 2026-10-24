"""Download NSE Indices press releases matching 'Changes in indices w.e.f. ...'
for years 1998-2026 from https://www.niftyindices.com/press-release

The press-release page loads ALL press items (1998-present) into the HTML at once
and uses client-side JS to show/hide them by year, so a single page fetch is enough;
we just parse all items and filter by year + title pattern ourselves.
"""

import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "data" / "press_release"
OUTPUT_DIR_PATH = f"{BASE_DIR.name}/{OUTPUT_DIR.relative_to(BASE_DIR)}"

PAGE_URL = "https://www.niftyindices.com/press-release"
BASE_URL = "https://www.niftyindices.com"

START_YEAR = 1998
END_YEAR = 2026

TITLE_PATTERN = re.compile(
    r"(?:Changes?|Replacements?) in (?:index|indices) w\.e\.f\.", re.IGNORECASE
)

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def fetch_page(session):
    resp = session.get(PAGE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_press_items(html):
    """Return list of (year, date_str, title, pdf_url) for every press item on the page."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for div in soup.select("div.pressItem"):
        date_str = div.get("data-date", "").strip()
        link = div.find("a")
        if not link or not link.get("href"):
            continue
        title = link.get_text(strip=True)
        href = link["href"].strip()
        pdf_url = urljoin(BASE_URL, href)
        year_match = re.search(r"\b(\d{4})\b", date_str)
        year = int(year_match.group(1)) if year_match else None
        items.append((year, date_str, title, pdf_url))
    return items


def sanitize_filename(name):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return name[:150]


def download_pdf(session, url, dest_path, retries=3):
    if dest_path.exists():
        print(f"Already exists, skipping: {dest_path.name}")
        return True
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            dest_path.write_bytes(resp.content)
            return True
        except requests.RequestException as e:
            print(f"  attempt {attempt}/{retries} failed for {url}: {e}")
            time.sleep(1)
    return False


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {OUTPUT_DIR_PATH}")

    session = requests.Session()
    print(f"Fetching {PAGE_URL} ...")
    html = fetch_page(session)

    items = extract_press_items(html)
    print(f"Found {len(items)} total press items on page")

    matches = [
        (year, date_str, title, pdf_url)
        for year, date_str, title, pdf_url in items
        if year is not None
        and START_YEAR <= year <= END_YEAR
        and TITLE_PATTERN.search(title)
    ]
    matches.sort(key=lambda m: m[0])
    print(f"Found {len(matches)} matching 'Changes in indices w.e.f. ...' items "
          f"between {START_YEAR} and {END_YEAR}")

    downloaded = 0
    failed = []
    for i, (year, date_str, title, pdf_url) in enumerate(matches, start=1):
        filename = sanitize_filename(f"{date_str}_{title}.pdf")
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        dest_path = OUTPUT_DIR / str(year) / filename
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        ok = download_pdf(session, pdf_url, dest_path)
        status = "OK" if ok else "FAILED"
        print(f"[{i}/{len(matches)}] {year} | {title} -> {status}")
        if ok:
            downloaded += 1
        else:
            failed.append((title, pdf_url))

    print(f"\nDone. Downloaded {downloaded}/{len(matches)} files to {OUTPUT_DIR_PATH}")
    if failed:
        print(f"Failed ({len(failed)}):")
        for title, pdf_url in failed:
            print(f"  - {title} ({pdf_url})")


if __name__ == "__main__":
    main()
