# /// script
# requires-python = ">=3.11"
# dependencies = ["aiohttp", "tqdm", "python-dotenv"]
# ///
"""
Re-geocode institutions whose GPS is >20km from their stored postcode centroid.
Uses Google Geocoding API (more reliable than Nominatim for Portuguese addresses).
Falls back to postcode centroid if Google returns no result within 20km.

Run: uv run regeocode.py
Safe to interrupt and resume — fixed rows are tracked in regeocode_done.json.
"""

import asyncio
import csv
import json
import math
import os
import sys
import aiohttp
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")
if not API_KEY:
    print("ERROR: set GOOGLE_PLACES_API_KEY in .env")
    sys.exit(1)

INPUT = "creches_portugal.csv"
POSTCODE_CSV = "codigos_postais.csv"
DONE_FILE = "regeocode_done.json"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
MAX_DIST_KM = 20   # rows further than this from their postcode centroid are candidates
VALID_DIST_KM = 20  # Google result must be within this of stored postcode to be accepted
CONCURRENCY = 5
SAVE_EVERY = 50


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def load_postcodes():
    """Load postcode centroids keyed by both full code and 4-digit prefix."""
    full = {}
    prefix = {}
    for r in csv.DictReader(open(POSTCODE_CSV, encoding="utf-8")):
        cp = r["codigo_postal"].strip()
        lat, lon = float(r["latitude"]), float(r["longitude"])
        full[cp] = (lat, lon)
        p4 = cp[:4]
        if p4 not in prefix:
            prefix[p4] = (lat, lon)
    return full, prefix


def postcode_centroid(cp, full_postcodes, prefix_postcodes):
    """Return (lat, lon) for a postcode, trying full then 4-digit prefix."""
    cp = cp.strip()
    return full_postcodes.get(cp) or prefix_postcodes.get(cp[:4])


async def google_geocode(session, address):
    """Call Google Geocoding API. Returns (lat, lon) or None."""
    params = {"address": address, "key": API_KEY, "region": "pt", "language": "pt"}
    try:
        async with session.get(GEOCODE_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"\n  ERROR geocoding {address!r}: {e}", file=sys.stderr)
    return None


async def regeocode_row(session, row, full_postcodes, prefix_postcodes):
    """
    Try to get a better GPS for this row using Google.
    Returns (lat, lon, source) where source is 'google' or 'postcode'.
    """
    cp = row["codigo_postal"].strip()
    cp_coords = postcode_centroid(cp, full_postcodes, prefix_postcodes)

    # Build queries in order of specificity
    morada = row["morada"].strip()
    localidade = row["localidade"].strip()
    nome = row["nome"].strip()
    concelho = row["concelho"].strip()

    queries = []
    if morada and cp:
        queries.append(f"{morada}, {cp}, Portugal")
    if morada and localidade and concelho:
        queries.append(f"{morada}, {localidade}, {concelho}, Portugal")
    if nome and cp:
        queries.append(f"{nome}, {cp}, Portugal")

    for q in queries:
        result = await google_geocode(session, q)
        if result:
            lat, lon = result
            # Validate: result must be within VALID_DIST_KM of postcode centroid
            if cp_coords:
                dist = haversine(cp_coords[0], cp_coords[1], lat, lon)
                if dist <= VALID_DIST_KM:
                    return lat, lon, "google"
            else:
                # No postcode centroid to validate against — trust Google
                return lat, lon, "google"

    # Google didn't return a valid result — fall back to postcode centroid
    if cp_coords:
        return cp_coords[0], cp_coords[1], "postcode"

    return None, None, "failed"


def save_csv(rows, fieldnames):
    with open(INPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def main():
    full_postcodes, prefix_postcodes = load_postcodes()
    print(f"Loaded {len(full_postcodes):,} postcode centroids")

    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    # Build a lookup by id
    rows_by_id = {r["id"]: r for r in rows}

    # Find candidates: GPS >MAX_DIST_KM from stored postcode centroid
    candidates = []
    for r in rows:
        if not r.get("latitude") or not r.get("longitude"):
            continue
        cp_coords = postcode_centroid(r["codigo_postal"], full_postcodes, prefix_postcodes)
        if not cp_coords:
            continue
        dist = haversine(cp_coords[0], cp_coords[1], float(r["latitude"]), float(r["longitude"]))
        if dist > MAX_DIST_KM:
            candidates.append(r)

    # Load already-done ids
    done = {}
    if os.path.exists(DONE_FILE):
        done = json.load(open(DONE_FILE))

    remaining = [r for r in candidates if r["id"] not in done]
    print(f"Candidates (GPS >{MAX_DIST_KM}km from postcode): {len(candidates)}")
    print(f"Already done: {len(done)} | Remaining: {len(remaining)}")
    print(f"Estimated cost: ~${len(remaining) * 0.005:.2f} USD\n")

    google_hits = sum(1 for v in done.values() if v["source"] == "google")
    postcode_hits = sum(1 for v in done.values() if v["source"] == "postcode")
    failed = sum(1 for v in done.values() if v["source"] == "failed")

    sem = asyncio.Semaphore(CONCURRENCY)
    processed = 0

    try:
        async with aiohttp.ClientSession() as session:

            async def _process(row):
                async with sem:
                    nonlocal processed, google_hits, postcode_hits, failed
                    lat, lon, source = await regeocode_row(session, row, full_postcodes, prefix_postcodes)
                    done[row["id"]] = {"lat": lat, "lon": lon, "source": source}
                    if lat:
                        rows_by_id[row["id"]]["latitude"] = str(lat)
                        rows_by_id[row["id"]]["longitude"] = str(lon)
                    if source == "google":
                        google_hits += 1
                    elif source == "postcode":
                        postcode_hits += 1
                    else:
                        failed += 1
                    processed += 1
                    if processed % SAVE_EVERY == 0:
                        save_csv(rows, fieldnames)
                        with open(DONE_FILE, "w") as f:
                            json.dump(done, f)

            tasks = [_process(row) for row in remaining]
            for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Re-geocoding", unit="row"):
                await coro

    except KeyboardInterrupt:
        print("\nInterrupted — saving progress...")

    save_csv(rows, fieldnames)
    with open(DONE_FILE, "w") as f:
        json.dump(done, f)

    total_done = len(done)
    print(f"\nDone. {total_done} rows processed:")
    print(f"  google:   {google_hits} (street-level precision)")
    print(f"  postcode: {postcode_hits} (postcode centroid fallback)")
    print(f"  failed:   {failed} (no postcode data, skipped)")
    print(f"\nCSV updated: {INPUT}")
    print("Next: run load_supabase.py to sync to Supabase")


if __name__ == "__main__":
    asyncio.run(main())
