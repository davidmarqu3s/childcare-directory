"""
Load creches_portugal.csv into Supabase institutions table.

Rows with lat/lng get a location (geography) value.
Rows without GPS are loaded with location = NULL and can be updated
once geocoding completes (see update_locations.py).

Setup:
  Create a .env file with:
    SUPABASE_URL=https://your-project.supabase.co
    SUPABASE_SERVICE_KEY=your-service-role-key

Run:
  python3 load_supabase.py          — full load
  python3 load_supabase.py 100      — first 100 rows (for testing)
"""

import csv
import os
import sys
from supabase import create_client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INPUT = "creches_portugal.csv"
BATCH_SIZE = 200  # rows per upsert call

# Load .env manually (avoid requiring python-dotenv)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_int(val: str) -> int | None:
    try:
        return int(val) if val.strip() else None
    except ValueError:
        return None


def to_date(val: str) -> str | None:
    return val.strip() if val.strip() else None


def row_to_record(row: dict) -> dict:
    lat = row.get("latitude", "").strip()
    lon = row.get("longitude", "").strip()

    record = {
        "id":                    int(row["id"]),
        "nome":                  row["nome"].strip(),
        "nome_google":           row["nome_google"].strip() or None,
        "morada":                row["morada"].strip() or None,
        "codigo_postal":         row["codigo_postal"].strip() or None,
        "localidade":            row["localidade"].strip() or None,
        "freguesia":             row["freguesia"].strip() or None,
        "concelho":              row["concelho"].strip() or None,
        "distrito":              row["distrito"].strip() or None,
        "tipo":                  row["tipo"].strip() or None,
        "natureza_juridica":     row["natureza_juridica"].strip() or None,
        "entidade_proprietaria": row["entidade_proprietaria"].strip() or None,
        "capacidade":            to_int(row["capacidade"]),
        "utentes":               to_int(row["utentes"]),
        "horario":               row["horario"].strip() or None,
        "telefone":              row["telefone"].strip() or None,
        "telefone_google":       row["telefone_google"].strip() or None,
        "email":                 row["email"].strip() or None,
        "website_google":        row["website_google"].strip() or None,
        "ultima_atualizacao":    to_date(row["ultima_atualizacao"]),
    }

    # Build PostGIS geography value from lat/lng if available
    if lat and lon:
        try:
            record["location"] = f"SRID=4326;POINT({float(lon)} {float(lat)})"
        except ValueError:
            pass  # leave location absent (NULL)

    return record


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(limit: int | None = None):
    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if limit:
        rows = rows[:limit]

    with_gps    = sum(1 for r in rows if r.get("latitude") and r.get("longitude"))
    without_gps = len(rows) - with_gps
    print(f"Rows to load:  {len(rows)}")
    print(f"With GPS:      {with_gps}")
    print(f"Without GPS:   {without_gps}  (location will be NULL — update later)")
    print()

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    records = [row_to_record(r) for r in rows]
    inserted = 0

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        client.table("institutions").upsert(batch).execute()
        inserted += len(batch)
        print(f"  Loaded {inserted}/{len(records)}")

    print(f"\nDone. {inserted} rows upserted → institutions")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit)
