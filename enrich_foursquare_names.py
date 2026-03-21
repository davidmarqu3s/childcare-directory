"""
Enrich creches_portugal.csv with names from Foursquare Places API.

Fills `nome_google` for rows where it is empty.
Also fills latitude/longitude for rows that have neither (bonus — saves Nominatim calls).

Free tier: 100k calls/month.
Run: python3 enrich_foursquare_names.py [limit]
"""

import asyncio
import csv
import os
import sys
import aiohttp
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
API_KEY = os.environ["FOURSQUARE_API_KEY"]

INPUT = "creches_portugal.csv"
ENDPOINT = "https://places-api.foursquare.com/places/search"
CONCURRENCY = 10
CHECKPOINT_EVERY = 200


async def search_place(session: aiohttp.ClientSession, nome: str, localidade: str, concelho: str) -> dict:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "X-Places-Api-Version": "2025-06-17",
    }
    params = {
        "query": f"{nome}",
        "near": f"{localidade}, Portugal",
        "limit": 1,
        "fields": "name,latitude,longitude",
    }
    try:
        async with session.get(ENDPOINT, headers=headers, params=params) as r:
            data = await r.json()
            results = data.get("results", [])
            if not results and concelho and concelho != localidade:
                # Retry with concelho
                params["near"] = f"{concelho}, Portugal"
                async with session.get(ENDPOINT, headers=headers, params=params) as r2:
                    data = await r2.json()
                    results = data.get("results", [])
            if results:
                place = results[0]
                out = {"nome_google": place.get("name", "")}
                lat = place.get("latitude")
                lon = place.get("longitude")
                if lat and lon:
                    out["latitude"] = str(lat)
                    out["longitude"] = str(lon)
                return out
    except Exception as e:
        print(f"  ERROR: {nome} — {e}")
    return {}


async def main():
    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    for field in ["nome_google", "latitude", "longitude"]:
        if field not in fieldnames:
            fieldnames.append(field)
            for r in rows:
                r.setdefault(field, "")

    to_enrich = [(i, r) for i, r in enumerate(rows) if not r.get("nome_google")]
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(to_enrich)
    to_enrich = to_enrich[:limit]
    total = len(to_enrich)
    print(f"Rows to enrich: {total} (of {sum(1 for r in rows if not r.get('nome_google'))} without nome_google)\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    found = 0

    async def enrich(idx, row_idx, row):
        nonlocal found
        async with sem:
            result = await search_place(session, row["nome"], row["localidade"], row["concelho"])
            if result:
                rows[row_idx]["nome_google"] = result["nome_google"]
                # Only fill GPS if not already set
                if not rows[row_idx].get("latitude") and result.get("latitude"):
                    rows[row_idx]["latitude"] = result["latitude"]
                    rows[row_idx]["longitude"] = result["longitude"]
                found += 1
                status = f"→ {result['nome_google'][:45]}"
            else:
                status = "✗"
            print(f"[{idx+1}/{total}] {row['nome'][:42]:<42} {status}")

    async with aiohttp.ClientSession() as session:
        tasks = [enrich(idx, row_idx, row) for idx, (row_idx, row) in enumerate(to_enrich)]

        for i in range(0, len(tasks), CHECKPOINT_EVERY):
            batch = tasks[i:i + CHECKPOINT_EVERY]
            await asyncio.gather(*batch)
            _save(rows, fieldnames)
            done = min(i + CHECKPOINT_EVERY, total)
            print(f"\n  ── Checkpoint saved ({done}/{total}) ──\n")

    _save(rows, fieldnames)
    remaining = sum(1 for r in rows if not r.get("nome_google"))
    print(f"\nDone. {found} names found. Rows still without nome_google: {remaining}")


def _save(rows, fieldnames):
    with open(INPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    asyncio.run(main())
