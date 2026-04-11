# /// script
# requires-python = ">=3.11"
# dependencies = ["supabase"]
# ///
"""
Update Supabase with CS coordinates for the 18 institutions
where we have no GPS coords but Carta Social does (CS_ONLY status).

Run: uv run python3 patch_cs_only_coords.py
"""

import csv
import os
import sys
from pathlib import Path

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env")
    sys.exit(1)

from supabase import create_client

VERDICT_CSV = Path("cs_coord_verdict.csv")


def main():
    cs_only = [
        r for r in csv.DictReader(open(VERDICT_CSV, encoding="utf-8"))
        if r["status"] == "CS_ONLY" and r["cs_lat"] and r["cs_lng"]
    ]
    print(f"CS_ONLY rows to update: {len(cs_only)}")

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    updated = 0
    for row in cs_only:
        inst_id = int(row["id"])
        lat = float(row["cs_lat"])
        lng = float(row["cs_lng"])
        client.table("institutions").update({
            "location": f"SRID=4326;POINT({lng} {lat})",
        }).eq("id", inst_id).execute()
        updated += 1
        print(f"  [{updated}/{len(cs_only)}] id={inst_id} → ({lat}, {lng})  {row['nome'][:60]}")

    print(f"\nDone. {updated} institutions updated.")


if __name__ == "__main__":
    main()
