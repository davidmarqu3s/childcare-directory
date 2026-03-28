# /// script
# requires-python = ">=3.11"
# dependencies = ["aiohttp", "tqdm", "python-dotenv"]
# ///
"""
Re-geocode ALL institutions with Google Geocoding API.
For rows where Geocoding returns only GEOMETRIC_CENTER or APPROXIMATE
(address too vague for street-level), falls back to Places Find Place API.
Falls back to postcode centroid if neither returns a result within 20km.

Sources (in priority order):
  google_rooftop       — exact street address match
  google_interpolated  — interpolated along a road segment
  places               — Places Find Place (by institution name)
  google_imprecise     — Geocoding returned GEOMETRIC_CENTER or APPROXIMATE
  postcode             — postcode centroid fallback
  failed               — no postcode data available

Run:   uv run regeocode_all.py
Safe to interrupt and resume — done rows tracked in regeocode_all_done.json.
"""

import asyncio
import csv
import json
import math
import os
import sys
from collections import Counter
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
DONE_FILE = "regeocode_all_done.json"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
VALID_DIST_KM = 20
CONCURRENCY = 5
SAVE_EVERY = 50

IMPRECISE_TYPES = {"GEOMETRIC_CENTER", "APPROXIMATE"}


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def load_postcodes():
    full, prefix = {}, {}
    for r in csv.DictReader(open(POSTCODE_CSV, encoding="utf-8")):
        cp = r["codigo_postal"].strip()
        lat, lon = float(r["latitude"]), float(r["longitude"])
        full[cp] = (lat, lon)
        p4 = cp[:4]
        if p4 not in prefix:
            prefix[p4] = (lat, lon)
    return full, prefix


def postcode_centroid(cp, full_postcodes, prefix_postcodes):
    cp = cp.strip()
    return full_postcodes.get(cp) or prefix_postcodes.get(cp[:4])


async def google_geocode(session, address):
    """Returns (lat, lon, location_type) or None."""
    params = {"address": address, "key": API_KEY, "region": "pt", "language": "pt"}
    try:
        async with session.get(GEOCODE_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            if data.get("status") == "OK" and data.get("results"):
                result = data["results"][0]
                loc = result["geometry"]["location"]
                loc_type = result["geometry"].get("location_type", "UNKNOWN")
                return loc["lat"], loc["lng"], loc_type
    except Exception as e:
        print(f"\n  ERROR geocoding {address!r}: {e}", file=sys.stderr)
    return None


async def places_find(session, query):
    """Find Place from Text. Returns (lat, lon) or None."""
    params = {
        "input": query,
        "inputtype": "textquery",
        "fields": "geometry",
        "key": API_KEY,
        "language": "pt",
    }
    try:
        async with session.get(PLACES_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            if data.get("status") == "OK" and data.get("candidates"):
                loc = data["candidates"][0]["geometry"]["location"]
                return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"\n  ERROR places find {query!r}: {e}", file=sys.stderr)
    return None


async def regeocode_row(session, row, full_postcodes, prefix_postcodes):
    cp = row["codigo_postal"].strip()
    cp_coords = postcode_centroid(cp, full_postcodes, prefix_postcodes)

    morada = row["morada"].strip()
    localidade = row["localidade"].strip()
    nome = row["nome"].strip()
    concelho = row["concelho"].strip()

    def valid(lat, lon):
        if not cp_coords:
            return True  # no reference point — trust Google
        return haversine(cp_coords[0], cp_coords[1], lat, lon) <= VALID_DIST_KM

    # Phase 1: Geocoding API — precise results first
    geocode_queries = []
    if morada and cp:
        geocode_queries.append(f"{morada}, {cp}, Portugal")
    if morada and localidade and concelho:
        geocode_queries.append(f"{morada}, {localidade}, {concelho}, Portugal")
    if nome and cp:
        geocode_queries.append(f"{nome}, {cp}, Portugal")

    best_imprecise = None

    for q in geocode_queries:
        result = await google_geocode(session, q)
        if not result:
            continue
        lat, lon, loc_type = result
        if not valid(lat, lon):
            continue
        if loc_type == "ROOFTOP":
            return lat, lon, "google_rooftop"
        elif loc_type == "RANGE_INTERPOLATED":
            return lat, lon, "google_interpolated"
        elif loc_type not in IMPRECISE_TYPES:
            return lat, lon, "google_other"
        elif best_imprecise is None:
            best_imprecise = (lat, lon)

    # Phase 2: Places Find Place — better for named institutions in rural areas
    places_queries = []
    if nome and localidade:
        places_queries.append(f"{nome}, {localidade}, Portugal")
    if nome and concelho:
        places_queries.append(f"{nome}, {concelho}, Portugal")
    if nome and cp:
        places_queries.append(f"{nome}, {cp}, Portugal")

    for q in places_queries:
        result = await places_find(session, q)
        if result:
            lat, lon = result
            if valid(lat, lon):
                return lat, lon, "places"

    # Phase 3: Accept imprecise geocoding result
    if best_imprecise:
        return best_imprecise[0], best_imprecise[1], "google_imprecise"

    # Phase 4: Postcode centroid
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

    rows_by_id = {r["id"]: r for r in rows}

    done = {}
    if os.path.exists(DONE_FILE):
        done = json.load(open(DONE_FILE))

    remaining = [r for r in rows if r["id"] not in done]
    source_counts = Counter(v["source"] for v in done.values())

    print(f"Total rows: {len(rows)} | Done: {len(done)} | Remaining: {len(remaining)}")
    geocode_cost = len(remaining) * 0.005
    est_places = int(len(remaining) * 0.15)
    est_cost = geocode_cost + est_places * 0.017
    print(f"Estimated cost: ~${geocode_cost:.2f} geocoding + ~${est_places * 0.017:.2f} places = ~${est_cost:.2f} USD\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    processed = 0

    try:
        async with aiohttp.ClientSession() as session:

            async def _process(row):
                async with sem:
                    nonlocal processed
                    lat, lon, source = await regeocode_row(session, row, full_postcodes, prefix_postcodes)
                    done[row["id"]] = {"lat": lat, "lon": lon, "source": source}
                    if lat:
                        rows_by_id[row["id"]]["latitude"] = str(lat)
                        rows_by_id[row["id"]]["longitude"] = str(lon)
                    source_counts[source] += 1
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

    print(f"\nDone. {len(done)} rows processed:")
    for src, count in source_counts.most_common():
        label = {
            "google_rooftop":     "rooftop (best)",
            "google_interpolated": "road interpolated",
            "places":             "Places API",
            "google_imprecise":   "imprecise (postcode-level)",
            "postcode":           "postcode centroid fallback",
            "failed":             "failed (no data)",
            "google_other":       "other Google type",
        }.get(src, src)
        print(f"  {label:35s}: {count}")

    print(f"\nCSV updated: {INPUT}")
    print("Next: run load_supabase.py to sync to Supabase")


if __name__ == "__main__":
    asyncio.run(main())
