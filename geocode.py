# /// script
# requires-python = ">=3.11"
# dependencies = ["aiohttp", "tqdm"]
# ///
"""
Geocode creches_portugal.csv rows missing lat/lng using Nominatim.
Writes results back to creches_portugal.csv in-place.

Run with: uv run geocode.py

Rate: 1 request/sec (Nominatim policy).
Safe to interrupt and resume — already-geocoded rows are skipped on next run.
Progress is flushed to disk every 50 rows so a crash loses at most 50 rows of work.
"""

import asyncio
import csv
import signal
import sys
import aiohttp
from tqdm import tqdm

INPUT = "creches_portugal.csv"
HEADERS = {"User-Agent": "childcare-directory-pt/1.0 (geocode)"}
RATE_LIMIT = 1.1   # seconds between requests (Nominatim requires ≥1/sec)
SAVE_EVERY = 50    # flush to disk every N rows processed


def save(rows: list[dict], fieldnames: list[str]) -> None:
    with open(INPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def nominatim_geocode(session: aiohttp.ClientSession, q: str) -> tuple[str, str] | None:
    params = {
        "q": q,
        "format": "json",
        "limit": 1,
        "countrycodes": "pt",
        "bounded": 1,
        "viewbox": "-9.5,36.8,-6.2,42.2",  # Portugal bounding box
    }
    try:
        async with session.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            results = await r.json()
            if results:
                return results[0]["lat"], results[0]["lon"]
    except Exception as e:
        print(f"\n  ERROR ({q!r}): {e}", file=sys.stderr)
    return None


async def geocode_row(session: aiohttp.ClientSession, row: dict) -> tuple[str, str] | None:
    morada = row["morada"]
    localidade = row["localidade"]
    cp = row["codigo_postal"]
    nome = row["nome"]

    queries = []
    if morada and cp:
        queries.append(f"{morada}, {cp}, Portugal")
    if morada and localidade:
        queries.append(f"{morada}, {localidade}, Portugal")
    if nome and cp:
        queries.append(f"{nome}, {cp}, Portugal")
    if nome and localidade:
        queries.append(f"{nome}, {localidade}, Portugal")

    for q in queries:
        result = await nominatim_geocode(session, q)
        await asyncio.sleep(RATE_LIMIT)
        if result:
            return result

    return None


async def main():
    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    to_geocode = [r for r in rows if not r.get("latitude") or not r.get("longitude")]
    already_done = len(rows) - len(to_geocode)
    print(f"Already geocoded: {already_done} / {len(rows)}")
    print(f"Remaining:        {len(to_geocode)}")
    est_hours = len(to_geocode) * RATE_LIMIT / 3600
    print(f"Estimated time:   {est_hours:.1f}h best case, {est_hours * 4:.1f}h worst case")
    print(f"Saving every {SAVE_EVERY} rows — safe to Ctrl-C and resume.\n")

    found = 0
    processed = 0

    # Register SIGTERM handler so kill also saves cleanly
    def _shutdown(signum, frame):
        print(f"\nSignal {signum} received — saving progress ({found} new hits)...")
        save(rows, fieldnames)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        async with aiohttp.ClientSession() as session:
            for row in tqdm(to_geocode, desc="Geocoding", unit="row"):
                result = await geocode_row(session, row)
                if result:
                    row["latitude"], row["longitude"] = result
                    found += 1
                processed += 1
                if processed % SAVE_EVERY == 0:
                    save(rows, fieldnames)

    except KeyboardInterrupt:
        print(f"\nInterrupted — saving progress ({found} new hits)...")

    save(rows, fieldnames)
    print(f"\nDone. Geocoded {found}/{len(to_geocode)} rows → {INPUT}")


if __name__ == "__main__":
    asyncio.run(main())
