"""
Fix duplicate/merged institutions and GPS errors in creches_portugal.csv,
then sync only the affected rows to Supabase.
"""
import csv, os, sys
from supabase import create_client

INPUT = "creches_portugal.csv"

env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

# ── MERGES: (keep_id, delete_id, new_nome, new_tipo) ──────────────────────────
MERGES = [
    ("25472", "3272",  "Santa Maria",                        "Creche e Jardim de Infância"),
    ("24669", "29727", "Colégio da Fonte",                   "Creche e Jardim de Infância"),
    ("27030", "29722", "Crescer no Campo",                   "Creche e Jardim de Infância"),
    ("3100",  "39129", "Centro Cultural e Social de Santo Adrião", "Creche e Jardim de Infância"),
]

# ── GPS FIXES: (id, new_lat, new_lng) ─────────────────────────────────────────
GPS_FIXES = [
    ("32308", 39.221064, -9.009528),   # Cercal, Cadaval
    ("32688", 38.430182, -9.189497),   # EB Azoia, Sesimbra
    ("34417", 41.061203, -8.480686),   # Painçais, VN de Gaia
    ("34437", 41.066791, -8.473742),   # Portelinha, VN de Gaia
    ("27241", 41.208346, -8.608054),   # CATL Gueifães, Maia (was 1.5km off)
    ("29947", 39.118824, -9.370827),   # JI Boavista-Silveira, Torres Vedras
    ("30108", 39.106137, -9.261681),   # JI Boavista-Olheiros, Torres Vedras
]

# ── Load CSV ──────────────────────────────────────────────────────────────────
with open(INPUT, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    rows = list(reader)

by_id = {r["id"]: r for r in rows}
delete_ids = set()

# Apply merges
for keep_id, del_id, new_nome, new_tipo in MERGES:
    r = by_id[keep_id]
    old_nome, old_tipo = r["nome"], r["tipo"]
    r["nome"] = new_nome
    r["tipo"] = new_tipo
    delete_ids.add(del_id)
    print(f"MERGE  keep={keep_id} '{old_nome}' → '{new_nome}' [{new_tipo}] | delete={del_id}")

# Apply GPS fixes
for fix_id, new_lat, new_lng in GPS_FIXES:
    r = by_id[fix_id]
    print(f"GPS    id={fix_id} '{r['nome'][:45]}'  ({r['latitude']},{r['longitude']}) → ({new_lat},{new_lng})")
    r["latitude"]  = str(new_lat)
    r["longitude"] = str(new_lng)

# Write updated CSV
updated_rows = [r for r in rows if r["id"] not in delete_ids]
with open(INPUT, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(updated_rows)
print(f"\nCSV written: {len(updated_rows)} rows (removed {len(delete_ids)} duplicates)")

# ── Sync to Supabase ──────────────────────────────────────────────────────────
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Upsert merged/updated rows
upsert_ids = {keep for keep, _, _, _ in MERGES} | {fix_id for fix_id, _, _ in GPS_FIXES}
upsert_rows = [r for r in updated_rows if r["id"] in upsert_ids]

def to_int(val):
    try: return int(val) if val.strip() else None
    except: return None

records = []
for r in upsert_rows:
    lat, lng = r.get("latitude","").strip(), r.get("longitude","").strip()
    rec = {
        "id": int(r["id"]),
        "nome": r["nome"].strip(),
        "tipo": r["tipo"].strip() or None,
        "natureza_juridica": r["natureza_juridica"].strip() or None,
        "morada": r["morada"].strip() or None,
        "codigo_postal": r["codigo_postal"].strip() or None,
        "localidade": r["localidade"].strip() or None,
        "freguesia": r["freguesia"].strip() or None,
        "concelho": r["concelho"].strip() or None,
        "distrito": r["distrito"].strip() or None,
        "capacidade": to_int(r["capacidade"]),
        "horario": r["horario"].strip() or None,
    }
    if lat and lng:
        rec["location"] = f"SRID=4326;POINT({float(lng)} {float(lat)})"
    records.append(rec)

sb.table("institutions").upsert(records).execute()
print(f"Upserted {len(records)} rows to Supabase")

# Delete merged-away rows
for del_id in delete_ids:
    sb.table("institutions").delete().eq("id", int(del_id)).execute()
    print(f"Deleted id={del_id} from Supabase")

print("\nDone.")
