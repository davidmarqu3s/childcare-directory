"""
Load codigos_postais.csv into Supabase codigos_postais table.

Run:
  python3 load_postcodes.py
"""

import csv
import os
import sys
from supabase import create_client

INPUT = "codigos_postais.csv"
BATCH_SIZE = 500

env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env")
    sys.exit(1)


def main():
    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Rows to load: {len(rows)}")

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    inserted = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        records = [
            {
                "codigo_postal": r["codigo_postal"].strip(),
                "latitude": float(r["latitude"]),
                "longitude": float(r["longitude"]),
            }
            for r in batch
        ]
        client.table("codigos_postais").upsert(records).execute()
        inserted += len(batch)
        print(f"  Loaded {inserted}/{len(rows)}")

    print(f"\nDone. {inserted} rows upserted → codigos_postais")


if __name__ == "__main__":
    main()
