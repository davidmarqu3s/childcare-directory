# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Post-process cs_coord_check.csv to add a verdict for MISMATCH rows.

For each MISMATCH, computes the distance from both our coord and the CS coord
to the institution's postcode centroid. Whichever is closer is flagged as likely correct.

Verdict values:
  OURS     — our coord is closer to the postcode centroid
  CS       — CS coord is closer to the postcode centroid
  UNCLEAR  — difference < UNCLEAR_THRESHOLD_M (too close to call)
  N/A      — not a MISMATCH row, or postcode centroid unavailable

Output: cs_coord_verdict.csv (all rows from cs_coord_check.csv + verdict column)

Run: uv run python3 check_cs_verdict.py
"""

import csv
import math
from pathlib import Path

CHECK_CSV = Path("cs_coord_check.csv")
CRECHES_CSV = Path("creches_portugal.csv")
POSTCODE_CSV = Path("codigos_postais.csv")
OUTPUT_CSV = Path("cs_coord_verdict.csv")

UNCLEAR_THRESHOLD_M = 500  # if the two distances differ by less than this, call it UNCLEAR


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_postcodes():
    full, prefix = {}, {}
    for r in csv.DictReader(open(POSTCODE_CSV, encoding="utf-8")):
        cp = r["codigo_postal"].strip()
        lat, lon = float(r["latitude"]), float(r["longitude"])
        full[cp] = (lat, lon)
        p4 = cp[:4]
        if p4 not in prefix:
            prefix[p4] = (lat, lon)
    return full, prefix


def postcode_centroid(cp, full, prefix):
    cp = cp.strip()
    return full.get(cp) or prefix.get(cp[:4])


def main():
    full_postcodes, prefix_postcodes = load_postcodes()
    print(f"Loaded {len(full_postcodes):,} postcode centroids")

    # Build id → codigo_postal lookup from creches CSV
    postcode_by_id = {}
    for r in csv.DictReader(open(CRECHES_CSV, encoding="utf-8")):
        postcode_by_id[r["id"]] = r.get("codigo_postal", "").strip()

    rows = list(csv.DictReader(open(CHECK_CSV, encoding="utf-8")))
    print(f"Loaded {len(rows):,} rows from {CHECK_CSV}")

    counts = {"OURS": 0, "CS": 0, "UNCLEAR": 0, "N/A": 0, "NO_POSTCODE": 0}
    out_rows = []

    for row in rows:
        verdict = "N/A"

        if row["status"] == "MISMATCH":
            inst_id = row["id"]
            cp = postcode_by_id.get(inst_id, "")
            centroid = postcode_centroid(cp, full_postcodes, prefix_postcodes) if cp else None

            if not centroid:
                verdict = "NO_POSTCODE"
                counts["NO_POSTCODE"] += 1
            else:
                try:
                    our_lat = float(row["our_lat"])
                    our_lng = float(row["our_lng"])
                    cs_lat = float(row["cs_lat"])
                    cs_lng = float(row["cs_lng"])
                except (ValueError, KeyError):
                    verdict = "N/A"
                    counts["N/A"] += 1
                else:
                    dist_ours = haversine_m(centroid[0], centroid[1], our_lat, our_lng)
                    dist_cs = haversine_m(centroid[0], centroid[1], cs_lat, cs_lng)
                    diff = abs(dist_ours - dist_cs)

                    if diff < UNCLEAR_THRESHOLD_M:
                        verdict = "UNCLEAR"
                    elif dist_ours < dist_cs:
                        verdict = "OURS"
                    else:
                        verdict = "CS"

                    counts[verdict] += 1
        else:
            counts["N/A"] += 1

        out_rows.append({**row, "verdict": verdict})

    fieldnames = list(rows[0].keys()) + ["verdict"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    mismatches = sum(1 for r in rows if r["status"] == "MISMATCH")
    print(f"\nMISMATCH rows: {mismatches}")
    print(f"  OURS (our coord closer to postcode)  : {counts['OURS']}")
    print(f"  CS   (CS coord closer to postcode)   : {counts['CS']}")
    print(f"  UNCLEAR (difference < {UNCLEAR_THRESHOLD_M}m)         : {counts['UNCLEAR']}")
    print(f"  NO_POSTCODE                          : {counts['NO_POSTCODE']}")
    print(f"\nOutput: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
