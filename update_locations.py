"""
Update location column in Supabase for rows that now have lat/lng in the CSV
but have NULL location in the database.

Run after geocode.py has finished:
  python3 update_locations.py
"""

import csv
import os
import sys
from supabase import create_client

INPUT = "creches_portugal.csv"
BATCH_SIZE = 200

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

    to_update = [
        r for r in rows
        if r.get("latitude") and r.get("longitude")
    ]
    print(f"Rows with GPS in CSV: {len(to_update)}")

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    updated = 0

    for i in range(0, len(to_update), BATCH_SIZE):
        batch = to_update[i : i + BATCH_SIZE]
        records = [
            {
                "id": int(r["id"]),
                "location": f"SRID=4326;POINT({float(r['longitude'])} {float(r['latitude'])})",
            }
            for r in batch
        ]
        client.table("institutions").upsert(records).execute()
        updated += len(batch)
        print(f"  Updated {updated}/{len(to_update)}")

    print(f"\nDone. {updated} location values upserted.")


if __name__ == "__main__":
    main()
