# /// script
# requires-python = ">=3.11"
# dependencies = ["supabase", "python-dotenv", "tqdm", "unicode-slugify"]
# ///
"""
Load creches_portugal.csv and codigos_postais.csv into Supabase.

Run with: uv run load.py

Requires in .env:
  SUPABASE_URL=https://xxxx.supabase.co
  SUPABASE_SERVICE_KEY=eyJ...

Run schema.sql in the Supabase SQL editor first.
"""

import csv
import os
import re
import unicodedata
from dotenv import load_dotenv
from supabase import create_client
from tqdm import tqdm

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

CRECHES_CSV = "creches_portugal.csv"
POSTCODE_CSV = "codigos_postais.csv"

BATCH_SIZE = 200  # rows per upsert batch


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_int(val: str) -> int | None:
    try:
        return int(val) if val.strip() else None
    except ValueError:
        return None


def parse_date(val: str) -> str | None:
    return val.strip() if val.strip() else None


def load_instituicoes(client) -> None:
    print("Loading instituicoes...")
    with open(CRECHES_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    records = []
    for row in rows:
        lat = row.get("latitude", "").strip()
        lng = row.get("longitude", "").strip()

        record = {
            "id": row["id"].strip(),
            "slug": f"{row['id'].strip()}-{slugify(row['nome'])}",
            "nome": row["nome"].strip(),
            "nome_google": row.get("nome_google", "").strip() or None,
            "tipo": row.get("tipo", "").strip() or None,
            "natureza_juridica": row.get("natureza_juridica", "").strip() or None,
            "morada": row.get("morada", "").strip() or None,
            "codigo_postal": row.get("codigo_postal", "").strip() or None,
            "localidade": row.get("localidade", "").strip() or None,
            "concelho": row.get("concelho", "").strip() or None,
            "distrito": row.get("distrito", "").strip() or None,
            "telefone": row.get("telefone", "").strip() or None,
            "telefone_google": row.get("telefone_google", "").strip() or None,
            "email": row.get("email", "").strip() or None,
            "website_google": row.get("website_google", "").strip() or None,
            "place_id": row.get("place_id", "").strip() or None,
            "capacidade": parse_int(row.get("capacidade", "")),
            "utentes": parse_int(row.get("utentes", "")),
            "horario": row.get("horario", "").strip() or None,
            "ultima_atualizacao": parse_date(row.get("ultima_atualizacao", "")),
        }

        # PostGIS point — pass as WKT, Supabase/PostGIS handles the cast
        if lat and lng:
            try:
                record["location"] = f"POINT({float(lng)} {float(lat)})"
            except ValueError:
                pass

        records.append(record)

    total = len(records)
    inserted = 0
    for i in tqdm(range(0, total, BATCH_SIZE), desc="Inserting instituicoes", unit="batch"):
        batch = records[i:i + BATCH_SIZE]
        client.table("instituicoes").upsert(batch).execute()
        inserted += len(batch)

    print(f"  Done — {inserted} rows loaded.")


def load_codigos_postais(client) -> None:
    print("\nLoading codigos_postais...")
    with open(POSTCODE_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    records = [
        {
            "codigo_postal": r["codigo_postal"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
        }
        for r in rows
    ]

    total = len(records)
    for i in tqdm(range(0, total, BATCH_SIZE), desc="Inserting codigos_postais", unit="batch"):
        batch = records[i:i + BATCH_SIZE]
        client.table("codigos_postais").upsert(batch).execute()

    print(f"  Done — {total} rows loaded.")


if __name__ == "__main__":
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    load_instituicoes(client)
    load_codigos_postais(client)
    print("\nMigration complete.")
