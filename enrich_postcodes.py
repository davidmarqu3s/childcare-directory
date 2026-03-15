"""
Enrich creches_portugal.csv with missing/incomplete postal codes via Nominatim.
Writes results back to creches_portugal.csv.
"""

import asyncio
import csv
import re
import aiohttp
from tqdm import tqdm

INPUT = "creches_portugal.csv"
HEADERS = {"User-Agent": "childcare-directory-pt/1.0 (github.com/childcare-directory)"}
RATE_LIMIT = 1.1  # seconds between requests (Nominatim requires 1/sec)


def is_complete(code: str) -> bool:
    return bool(re.match(r'^\d{4}-\d{3}$', code)) and not code.endswith("-000")


async def nominatim_search(session: aiohttp.ClientSession, q: str) -> str | None:
    params = {"q": q, "format": "json", "addressdetails": 1, "limit": 1, "countrycodes": "pt"}
    try:
        async with session.get("https://nominatim.openstreetmap.org/search",
                               params=params, headers=HEADERS) as r:
            results = await r.json()
            if results:
                postcode = results[0].get("address", {}).get("postcode", "")
                if postcode and is_complete(postcode):
                    return postcode
    except Exception as e:
        print(f"  ERROR: {e}")
    return None


async def lookup(session: aiohttp.ClientSession, row: dict) -> str | None:
    nome = row["nome"].title()
    morada = row["morada"]
    localidade = row["localidade"]
    concelho = row["concelho"]

    queries = []
    if morada:
        queries.append(f"{morada}, {localidade}, Portugal")
        queries.append(f"{morada}, {concelho}, Portugal")
    queries.append(f"{nome}, {localidade}, Portugal")
    queries.append(f"{nome}, {concelho}, Portugal")

    for q in queries:
        postcode = await nominatim_search(session, q)
        await asyncio.sleep(RATE_LIMIT)
        if postcode:
            return postcode

    return None


async def main():
    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    to_fix = [r for r in rows if not is_complete(r.get("codigo_postal", ""))]
    print(f"Rows needing postal code: {len(to_fix)} / {len(rows)}")

    found = 0
    async with aiohttp.ClientSession() as session:
        for row in tqdm(to_fix, desc="Nominatim lookups", unit="row"):
            result = await lookup(session, row)
            if result:
                row["codigo_postal"] = result
                found += 1

    with open(INPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nUpdated {found}/{len(to_fix)} postal codes → {INPUT}")


if __name__ == "__main__":
    asyncio.run(main())
