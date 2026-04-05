"""
Fix concelho/distrito errors in creches_portugal.csv and sync to Supabase.

Errors found by data sweep (2026-04-05):
  - 41 Lisboa institutions misassigned to Santiago do Cacém / Pombal / Vila Real / Vagos
  - 9 Algarve institutions misassigned (Albufeira→Melgaço/Pombal, Faro→Cascais, Lagos→Lousada)
  - 1 PROBRANCA (id 24787) misassigned to Coruche, should be Albergaria-a-Velha/Aveiro
  - 2 rows with concelho="São Vicente" (a parish), should be Santarém

Run:
  python3 fix_concelhos.py           — preview changes
  python3 fix_concelhos.py --apply   — apply to CSV + Supabase
"""

import csv
import os
import sys

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL      = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
INPUT  = "creches_portugal.csv"
OUTPUT = "creches_portugal.csv"  # overwrite in place
APPLY  = "--apply" in sys.argv

# ---------------------------------------------------------------------------
# Corrections: id → (concelho, distrito)
# ---------------------------------------------------------------------------

# 41 Lisboa institutions — postcode 1xxx, Lisboa GPS, Lisboa parishes
# Misassigned to: Santiago do Cacém, Pombal, Vila Real, Vagos
LISBOA_IDS = {
    642, 653, 701, 714, 743, 1690, 1706, 1716, 1757, 1760,
    2252, 2258, 2259, 5102, 5116, 5121, 5183, 5188, 5197,
    17175, 18614, 20290, 20322, 21381, 22546, 24671, 24935,
    25042, 25451, 26319, 27518, 27667, 29038, 29483, 29535,
    29552, 30155, 30265, 30817, 31065, 31910, 34379, 35284,
    36457, 36621, 36951, 37641, 39156,
}

# Algarve institutions — correct concelho derived from postcode
ALGARVE_FIXES = {
    4068:  ("Albufeira", "Faro"),   # cp 8200-421
    18126: ("Albufeira", "Faro"),   # cp 8200-427
    29846: ("Albufeira", "Faro"),   # cp 8200-428
    29847: ("Albufeira", "Faro"),   # cp 8200-062
    18270: ("Albufeira", "Faro"),   # cp 8200-466  (Paderne is a parish of Albufeira)
    33227: ("Albufeira", "Faro"),   # cp 8200-476
    4101:  ("Faro",      "Faro"),   # cp 8005-489
    37609: ("Faro",      "Faro"),   # cp 8000-670
    34617: ("Lagos",     "Faro"),   # cp 8600-136
}

# Individual fixes
INDIVIDUAL_FIXES = {
    24787: ("Albergaria-a-Velha", "Aveiro"),  # PROBRANCA, cp 3850-564
    30946: ("Santarém",           "Santarém"), # concelho was "São Vicente" (a parish)
    31455: ("Santarém",           "Santarém"), # same
}

# Build full corrections dict
CORRECTIONS: dict[int, tuple[str, str]] = {}
for rid in LISBOA_IDS:
    CORRECTIONS[rid] = ("Lisboa", "Lisboa")
CORRECTIONS.update(ALGARVE_FIXES)
CORRECTIONS.update(INDIVIDUAL_FIXES)

# ---------------------------------------------------------------------------
# Apply corrections to CSV
# ---------------------------------------------------------------------------
with open(INPUT, encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

fieldnames = list(rows[0].keys())
changed = []

for row in rows:
    rid = int(row["id"])
    if rid in CORRECTIONS:
        new_concelho, new_distrito = CORRECTIONS[rid]
        old_c, old_d = row["concelho"], row["distrito"]
        if old_c != new_concelho or old_d != new_distrito:
            changed.append({
                "id": rid,
                "nome": row["nome"][:60],
                "old": f"{old_c} / {old_d}",
                "new": f"{new_concelho} / {new_distrito}",
            })
            if APPLY:
                row["concelho"] = new_concelho
                row["distrito"] = new_distrito

print(f"\n{'PREVIEW' if not APPLY else 'APPLYING'} — {len(changed)} rows to fix:\n")
for c in changed:
    print(f"  [{c['id']:>6}] {c['nome']:<62}  {c['old']} → {c['new']}")

if not APPLY:
    print(f"\nRun with --apply to write changes to CSV and Supabase.")
    sys.exit(0)

# Write CSV
with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
print(f"\nCSV updated: {OUTPUT}")

# ---------------------------------------------------------------------------
# Sync to Supabase
# ---------------------------------------------------------------------------
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("WARNING: no Supabase credentials — skipping DB update")
    sys.exit(0)

from supabase import create_client
client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

patched = 0
for rid, (c, d) in CORRECTIONS.items():
    client.table("institutions").update({"concelho": c, "distrito": d}).eq("id", rid).execute()
    patched += 1
    if patched % 10 == 0:
        print(f"  Supabase: {patched}/{len(CORRECTIONS)} rows updated")

print(f"\nDone. {len(changed)} rows fixed in CSV, {patched} updated in Supabase.")
