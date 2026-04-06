#!/usr/bin/env python3
"""
postcode_audit.py
Audit creches_portugal.csv for postcode/district mismatches and missing data.
"""

import csv
import re
from collections import defaultdict

CSV_PATH = "creches_portugal.csv"

# --- Rules ----------------------------------------------------------------
# Each rule: (label, postcode_prefix_test, forbidden_distritos)
# We also keep the inverse: expected distritos for clear ranges.

CLEAR_MUST_BE = {
    "1": ["Lisboa"],
    "8": ["Faro"],
    "9": ["Açores", "Madeira", "Ilha da Madeira", "Ilha de São Miguel",
          "Ilha Terceira", "Ilha do Faial", "Ilha do Pico",
          "Ilha de Santa Maria", "Ilha das Flores", "Ilha do Corvo",
          "Ilha de São Jorge", "Ilha do Graciosa"],
}

# For 4xxx: flag if assigned to southern districts
NORTHERN_POSTCODE_SOUTHERN_DISTRICTS = {
    "4": ["Lisboa", "Setúbal", "Faro", "Évora", "Beja", "Portalegre"],
}

# For 7xxx: flag if assigned to northern districts
SOUTHERN_POSTCODE_NORTHERN_DISTRICTS = {
    "7": ["Porto", "Braga", "Bragança", "Vila Real", "Viana do Castelo",
          "Aveiro", "Braga"],
}

def get_postcode_prefix(cp):
    """Return first digit of postcode, or None if unparseable."""
    if not cp:
        return None
    cp = cp.strip()
    if re.match(r"^\d", cp):
        return cp[0]
    return None

def normalise_distrito(d):
    if not d:
        return ""
    return d.strip()

def check_row(row, mismatches, missing_postcode, missing_gps):
    cp = row.get("codigo_postal", "").strip()
    distrito = normalise_distrito(row.get("distrito", ""))
    lat = row.get("latitude", "").strip()
    lon = row.get("longitude", "").strip()
    id_ = row.get("id", "?")
    nome = row.get("nome", "?")
    concelho = row.get("concelho", "")

    has_gps = bool(lat and lon)
    has_postcode = bool(cp)

    if not has_postcode:
        missing_postcode.append({
            "id": id_, "nome": nome, "concelho": concelho,
            "distrito": distrito, "has_gps": has_gps,
        })

    if not has_gps:
        missing_gps.append({
            "id": id_, "nome": nome, "concelho": concelho,
            "distrito": distrito, "has_postcode": has_postcode,
        })

    if not cp:
        return

    prefix = get_postcode_prefix(cp)
    if prefix is None:
        return

    # High-confidence: 1xxx must be Lisboa
    if prefix in CLEAR_MUST_BE:
        expected = CLEAR_MUST_BE[prefix]
        if distrito not in expected:
            mismatches.append({
                "confidence": "HIGH",
                "rule": f"{prefix}xxx → must be {'/'.join(expected)}",
                "id": id_,
                "nome": nome,
                "codigo_postal": cp,
                "distrito": distrito,
                "concelho": concelho,
            })

    # 4xxx → flagged if southern district
    elif prefix in NORTHERN_POSTCODE_SOUTHERN_DISTRICTS:
        bad = NORTHERN_POSTCODE_SOUTHERN_DISTRICTS[prefix]
        if distrito in bad:
            mismatches.append({
                "confidence": "MEDIUM",
                "rule": f"{prefix}xxx (Porto/Braga region) but district is southern",
                "id": id_,
                "nome": nome,
                "codigo_postal": cp,
                "distrito": distrito,
                "concelho": concelho,
            })

    # 7xxx → flagged if northern district
    elif prefix in SOUTHERN_POSTCODE_NORTHERN_DISTRICTS:
        bad = SOUTHERN_POSTCODE_NORTHERN_DISTRICTS[prefix]
        if distrito in bad:
            mismatches.append({
                "confidence": "MEDIUM",
                "rule": f"{prefix}xxx (Alentejo region) but district is northern",
                "id": id_,
                "nome": nome,
                "codigo_postal": cp,
                "distrito": distrito,
                "concelho": concelho,
            })


def main():
    mismatches = []
    missing_postcode = []
    missing_gps = []
    total = 0

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            check_row(row, mismatches, missing_postcode, missing_gps)

    print(f"{'='*70}")
    print(f"POSTCODE AUDIT — creches_portugal.csv")
    print(f"Total rows: {total}")
    print(f"{'='*70}\n")

    # --- Mismatches --------------------------------------------------------
    high = [m for m in mismatches if m["confidence"] == "HIGH"]
    medium = [m for m in mismatches if m["confidence"] == "MEDIUM"]

    print(f"MISMATCHES: {len(mismatches)} total  ({len(high)} HIGH confidence, {len(medium)} MEDIUM)")
    print()

    if high:
        print("--- HIGH CONFIDENCE MISMATCHES ---")
        for m in high:
            print(f"  id={m['id']}  CP={m['codigo_postal']}  distrito={m['distrito']}  concelho={m['concelho']}")
            print(f"    Rule: {m['rule']}")
            print(f"    Nome: {m['nome']}")
        print()

    if medium:
        print("--- MEDIUM CONFIDENCE MISMATCHES ---")
        for m in medium:
            print(f"  id={m['id']}  CP={m['codigo_postal']}  distrito={m['distrito']}  concelho={m['concelho']}")
            print(f"    Rule: {m['rule']}")
            print(f"    Nome: {m['nome']}")
        print()

    if not mismatches:
        print("  No mismatches found.\n")

    # --- Missing postcodes -------------------------------------------------
    print(f"{'='*70}")
    print(f"MISSING POSTCODES: {len(missing_postcode)}")
    if missing_postcode:
        with_gps = [r for r in missing_postcode if r["has_gps"]]
        without_gps = [r for r in missing_postcode if not r["has_gps"]]
        print(f"  - With GPS (potentially fixable via reverse geocode): {len(with_gps)}")
        print(f"  - Without GPS (harder to fix): {len(without_gps)}")
        if with_gps:
            print("\n  Rows with GPS but no postcode:")
            for r in with_gps:
                print(f"    id={r['id']}  concelho={r['concelho']}  distrito={r['distrito']}  nome={r['nome']}")
        if without_gps:
            print("\n  Rows without GPS or postcode:")
            for r in without_gps:
                print(f"    id={r['id']}  concelho={r['concelho']}  distrito={r['distrito']}  nome={r['nome']}")
    print()

    # --- Missing GPS -------------------------------------------------------
    print(f"{'='*70}")
    print(f"MISSING GPS: {len(missing_gps)}")
    if missing_gps:
        with_cp = [r for r in missing_gps if r["has_postcode"]]
        without_cp = [r for r in missing_gps if not r["has_postcode"]]
        print(f"  - With postcode (geocodable): {len(with_cp)}")
        print(f"  - Without postcode (harder): {len(without_cp)}")
    print()

    # --- Summary of distrito distribution per prefix -----------------------
    print(f"{'='*70}")
    print("POSTCODE PREFIX → DISTRITO DISTRIBUTION (all rows)")
    prefix_distrito = defaultdict(lambda: defaultdict(int))
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cp = row.get("codigo_postal", "").strip()
            distrito = normalise_distrito(row.get("distrito", "")) or "(blank)"
            prefix = get_postcode_prefix(cp) or "?"
            prefix_distrito[prefix][distrito] += 1

    for prefix in sorted(prefix_distrito.keys()):
        distritos = prefix_distrito[prefix]
        total_prefix = sum(distritos.values())
        print(f"\n  {prefix}xxx  ({total_prefix} rows)")
        for d, count in sorted(distritos.items(), key=lambda x: -x[1]):
            flag = ""
            if prefix == "1" and d not in CLEAR_MUST_BE.get("1", []):
                flag = " *** MISMATCH"
            elif prefix == "8" and d not in CLEAR_MUST_BE.get("8", []):
                flag = " *** MISMATCH"
            elif prefix == "9" and d not in (CLEAR_MUST_BE.get("9", []) + ["(blank)"]):
                flag = " *** MISMATCH"
            print(f"    {d}: {count}{flag}")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
