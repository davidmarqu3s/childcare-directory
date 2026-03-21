"""
Geocode creches_portugal.csv rows missing lat/lng via Nominatim.
Writes results back to creches_portugal.csv.

Query strategy (stops at first hit):
  1. morada + localidade, Portugal
  2. morada + concelho, Portugal
  3. nome + localidade, Portugal
  4. codigo_postal, Portugal  (always available — reliable fallback)

Saves every 50 hits so the script is safe to interrupt and resume.
Run:  python3 geocode.py          — full run
      python3 geocode.py 100      — first 100 rows only (for testing)
"""

import csv
import sys
import time
import requests

INPUT = "creches_portugal.csv"
HEADERS = {"User-Agent": "childcare-directory-pt/1.0 (github.com/davidmarqu3s/childcare-directory)"}
RATE_LIMIT = 1.1  # Nominatim policy: max 1 req/sec


def nominatim_search(q: str) -> tuple[str, str] | None:
    params = {"q": q, "format": "json", "limit": 1, "countrycodes": "pt"}
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=HEADERS,
            timeout=10,
        )
        results = r.json()
        if results:
            lat = results[0].get("lat", "")
            lon = results[0].get("lon", "")
            if lat and lon:
                return lat, lon
    except Exception as e:
        print(f"  ERROR: {e}")
    return None


def geocode_row(row: dict) -> tuple[str, str] | None:
    morada = row["morada"].strip()
    localidade = row["localidade"].strip()
    concelho = row["concelho"].strip()
    nome = row["nome"].strip()
    cp = row["codigo_postal"].strip()

    queries = []
    if morada:
        queries.append(f"{morada}, {localidade}, Portugal")
        queries.append(f"{morada}, {concelho}, Portugal")
    queries.append(f"{nome}, {localidade}, Portugal")
    queries.append(f"{cp}, Portugal")

    for q in queries:
        result = nominatim_search(q)
        time.sleep(RATE_LIMIT)
        if result:
            return result

    return None


def main(limit: int | None = None):
    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    all_missing = [r for r in rows if not r.get("latitude") or not r.get("longitude")]
    to_geocode = all_missing[:limit] if limit else all_missing

    print(f"Total rows:    {len(rows)}")
    print(f"Missing GPS:   {len(all_missing)}")
    print(f"Already done:  {len(rows) - len(all_missing)}")
    print(f"This run:      {len(to_geocode)}")
    print(f"Est. time:     ~{len(to_geocode) * RATE_LIMIT / 3600:.1f}h (best case, 1 query/row)")
    print()

    found = 0
    failed = 0

    def save():
        with open(INPUT, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    for i, row in enumerate(to_geocode, 1):
        result = geocode_row(row)
        if result:
            row["latitude"], row["longitude"] = result
            found += 1
            if found % 50 == 0:
                save()
                print(f"  [checkpoint] {found} geocoded so far ({i}/{len(to_geocode)} processed)")
        else:
            failed += 1
            print(f"  FAILED [{i}/{len(to_geocode)}]: {row['nome'][:50]} ({row['codigo_postal']})")

        # Progress every 100 rows
        if i % 100 == 0:
            print(f"  Progress: {i}/{len(to_geocode)} — found={found}, failed={failed}")

    save()
    print(f"\nGeocoded: {found}/{len(to_geocode)}  |  Failed: {failed}  →  {INPUT}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit)
