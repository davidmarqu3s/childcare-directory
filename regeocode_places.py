# /// script
# requires-python = ">=3.11"
# dependencies = ["aiohttp", "tqdm", "python-dotenv"]
# ///
"""
Run Places Find Place API on imprecise rows that are >1km from their postcode centroid.
Updates regeocode_all_done.json and creches_portugal.csv in place.

Run: uv run regeocode_places.py
Safe to interrupt and resume.
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
PLACES_DONE_FILE = "regeocode_places_done.json"
PLACES_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
VALID_DIST_KM = 20
MIN_IMPROVEMENT_KM = 1.0   # only upgrade if >1km from postcode centroid
CONCURRENCY = 5
SAVE_EVERY = 50


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


def save_csv(rows, fieldnames):
    with open(INPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def main():
    full_postcodes, prefix_postcodes = load_postcodes()

    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())
    rows_by_id = {r["id"]: r for r in rows}

    done = json.load(open(DONE_FILE))

    # Load places-specific progress (tracks which IDs we've already tried)
    places_done = {}
    if os.path.exists(PLACES_DONE_FILE):
        places_done = json.load(open(PLACES_DONE_FILE))

    # Identify candidates: imprecise + >1km from postcode centroid + not yet tried
    candidates = []
    for id_, v in done.items():
        if v["source"] != "google_imprecise":
            continue
        if id_ in places_done:
            continue
        row = rows_by_id.get(id_)
        if not row:
            continue
        c = postcode_centroid(row["codigo_postal"], full_postcodes, prefix_postcodes)
        if not c or not v["lat"]:
            continue
        dist = haversine(c[0], c[1], v["lat"], v["lon"])
        if dist >= MIN_IMPROVEMENT_KM:
            candidates.append((id_, row, c))

    print(f"Candidates for Places upgrade: {len(candidates)}")
    print(f"Estimated cost: ~${len(candidates) * 0.017:.2f} USD\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    upgraded = 0
    no_result = 0
    processed = 0

    try:
        async with aiohttp.ClientSession() as session:

            async def _process(id_, row, cp_coords):
                async with sem:
                    nonlocal upgraded, no_result, processed

                    nome = row["nome"].strip()
                    localidade = row["localidade"].strip()
                    concelho = row["concelho"].strip()
                    cp = row["codigo_postal"].strip()

                    queries = []
                    if nome and localidade:
                        queries.append(f"{nome}, {localidade}, Portugal")
                    if nome and concelho:
                        queries.append(f"{nome}, {concelho}, Portugal")
                    if nome and cp:
                        queries.append(f"{nome}, {cp}, Portugal")

                    result_lat, result_lon = None, None
                    for q in queries:
                        result = await places_find(session, q)
                        if result:
                            lat, lon = result
                            dist = haversine(cp_coords[0], cp_coords[1], lat, lon)
                            if dist <= VALID_DIST_KM:
                                result_lat, result_lon = lat, lon
                                break

                    places_done[id_] = {"tried": True, "upgraded": result_lat is not None}

                    if result_lat is not None:
                        done[id_] = {"lat": result_lat, "lon": result_lon, "source": "places"}
                        rows_by_id[id_]["latitude"] = str(result_lat)
                        rows_by_id[id_]["longitude"] = str(result_lon)
                        upgraded += 1
                    else:
                        no_result += 1

                    processed += 1
                    if processed % SAVE_EVERY == 0:
                        save_csv(rows, fieldnames)
                        with open(DONE_FILE, "w") as f:
                            json.dump(done, f)
                        with open(PLACES_DONE_FILE, "w") as f:
                            json.dump(places_done, f)

            tasks = [_process(id_, row, c) for id_, row, c in candidates]
            for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Places lookup", unit="row"):
                await coro

    except KeyboardInterrupt:
        print("\nInterrupted — saving progress...")

    save_csv(rows, fieldnames)
    with open(DONE_FILE, "w") as f:
        json.dump(done, f)
    with open(PLACES_DONE_FILE, "w") as f:
        json.dump(places_done, f)

    print(f"\nDone. {processed} rows tried:")
    print(f"  Upgraded to Places precision : {upgraded}")
    print(f"  No result / outside bounds   : {no_result}")
    print(f"\nCSV updated: {INPUT}")
    print("Next: run load_supabase.py to sync to Supabase")


if __name__ == "__main__":
    asyncio.run(main())
