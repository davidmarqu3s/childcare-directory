"""
Enrich creches_portugal.csv using Google Places API (Text Search).

Adds per row: nome_google, latitude, longitude, telefone_google, website_google.
Skips rows already enriched (latitude present).
~$0.032/request — 5,887 rows ≈ $188, within the $200/month free tier.
"""

import asyncio
import csv
import os
import sys
import aiohttp
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
API_KEY = os.environ["GOOGLE_PLACES_API_KEY"]

INPUT = "creches_portugal.csv"
ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = "places.displayName,places.location,places.formattedAddress,places.internationalPhoneNumber,places.websiteUri,places.types"

ACCEPTED_TYPES = {
    "child_care_agency", "preschool", "school", "primary_school",
    "private_school", "educational_institution",
}
CONCURRENCY = 10
CHECKPOINT_EVERY = 200

NEW_FIELDS = ["nome_google", "latitude", "longitude", "telefone_google", "website_google"]


# Bounding box covering mainland Portugal + Azores + Madeira
PORTUGAL_BOUNDS = {
    "rectangle": {
        "low":  {"latitude": 30.0, "longitude": -31.3},
        "high": {"latitude": 42.2, "longitude": -6.2},
    }
}


async def search_place(session: aiohttp.ClientSession, nome: str, localidade: str, concelho: str) -> dict:
    query = f"{nome} {localidade} Portugal"
    payload = {"textQuery": query, "languageCode": "pt", "locationRestriction": PORTUGAL_BOUNDS}
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    try:
        async with session.post(ENDPOINT, json=payload, headers=headers) as r:
            data = await r.json()
            places = data.get("places", [])
            if not places:
                # Retry with concelho if localidade gave nothing
                payload["textQuery"] = f"{nome} {concelho} Portugal"
                async with session.post(ENDPOINT, json=payload, headers=headers) as r2:
                    data = await r2.json()
                    places = data.get("places", [])
            if places:
                p = places[0]
                place_types = set(p.get("types", []))
                if not place_types.intersection(ACCEPTED_TYPES):
                    return {}
                google_name = p.get("displayName", {}).get("text", "")
                return {
                    "nome_google": google_name,
                    "latitude": str(p.get("location", {}).get("latitude", "")),
                    "longitude": str(p.get("location", {}).get("longitude", "")),
                    "telefone_google": p.get("internationalPhoneNumber", ""),
                    "website_google": p.get("websiteUri", ""),
                }
    except Exception as e:
        print(f"  ERROR: {nome} — {e}")
    return {}


async def main():
    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    for field in NEW_FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)
            for r in rows:
                r.setdefault(field, "")

    to_enrich = [(i, r) for i, r in enumerate(rows) if not r.get("latitude")]
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(to_enrich)
    to_enrich = to_enrich[:limit]
    total = len(to_enrich)
    print(f"Rows to enrich: {total} (of {sum(1 for r in rows if not r.get('latitude'))} remaining)\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    found = 0

    async def enrich(idx, row_idx, row):
        nonlocal found
        async with sem:
            result = await search_place(session, row["nome"], row["localidade"], row["concelho"])
            nome_g = result.get("nome_google", "—")
            lat = result.get("latitude", "")
            status = f"→ {nome_g[:40]} ({lat})" if result else "✗"
            print(f"[{idx+1}/{total}] {row['nome'][:42]:<42} {status}")
            if result:
                for k, v in result.items():
                    rows[row_idx][k] = v
                found += 1

    async with aiohttp.ClientSession() as session:
        tasks = [enrich(idx, row_idx, row) for idx, (row_idx, row) in enumerate(to_enrich)]

        for i in range(0, len(tasks), CHECKPOINT_EVERY):
            batch = tasks[i:i + CHECKPOINT_EVERY]
            await asyncio.gather(*batch)
            _save(rows, fieldnames)
            done = min(i + CHECKPOINT_EVERY, total)
            print(f"\n  ── Checkpoint saved ({done}/{total}) ──\n")

    _save(rows, fieldnames)
    remaining = sum(1 for r in rows if not r.get("latitude"))
    print(f"\nDone. {found} places found. Rows without GPS: {remaining}")


def _save(rows, fieldnames):
    with open(INPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    asyncio.run(main())
