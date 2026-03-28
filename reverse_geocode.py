"""
Reverse geocode all institutions with GPS using Nominatim.
Compares returned address fields against stored values.
Saves results to reverse_geocode_results.csv.

Run: python3 reverse_geocode.py
Safe to interrupt and resume — already-processed rows are skipped.
"""

import csv
import json
import os
import time
import urllib.request
import urllib.parse

INPUT = "creches_portugal.csv"
OUTPUT = "reverse_geocode_results.csv"
DELAY = 1.5  # Nominatim rate limit: 1 req/sec — using 1.5s for safety margin

FIELDNAMES = [
    "id", "nome", "stored_morada", "stored_codigo_postal", "stored_localidade",
    "stored_freguesia", "stored_concelho", "stored_distrito",
    "lat", "lng",
    "nom_road", "nom_house_number", "nom_postcode", "nom_suburb",
    "nom_city", "nom_municipality", "nom_county", "nom_state",
    "nom_display_name",
    "cp_match", "concelho_match", "distrito_match", "flag",
]

def load_done():
    if not os.path.exists(OUTPUT):
        return set()
    with open(OUTPUT, encoding="utf-8") as f:
        return {int(r["id"]) for r in csv.DictReader(f)}

def reverse_geocode(lat, lng):
    url = (
        "https://nominatim.openstreetmap.org/reverse"
        f"?lat={lat}&lon={lng}&format=json&addressdetails=1&accept-language=pt"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "childcare-pt-validation/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

def normalize(s):
    return (s or "").strip().lower()

def main():
    rows = [r for r in csv.DictReader(open(INPUT, encoding="utf-8"))
            if r.get("latitude", "").strip() and r.get("longitude", "").strip()]

    done = load_done()
    remaining = [r for r in rows if int(r["id"]) not in done]
    print(f"Total with GPS: {len(rows)} | Done: {len(done)} | Remaining: {len(remaining)}")

    write_header = not os.path.exists(OUTPUT) or os.path.getsize(OUTPUT) == 0
    out_file = open(OUTPUT, "a", encoding="utf-8", newline="")
    writer = csv.DictWriter(out_file, fieldnames=FIELDNAMES)
    if write_header:
        writer.writeheader()

    try:
        for i, row in enumerate(remaining):
            lat = float(row["latitude"])
            lng = float(row["longitude"])
            result = reverse_geocode(lat, lng)

            addr = result.get("address", {})
            nom_postcode = addr.get("postcode", "")
            nom_municipality = addr.get("municipality", addr.get("city", addr.get("town", addr.get("village", ""))))
            nom_county = addr.get("county", "")
            nom_state = addr.get("state", "")

            stored_cp = row.get("codigo_postal", "").strip()
            stored_concelho = row.get("concelho", "").strip()
            stored_distrito = row.get("distrito", "").strip()

            # Normalize postcode: compare first 4 digits only (sub-codes vary)
            cp_match = normalize(nom_postcode[:4]) == normalize(stored_cp[:4]) if nom_postcode and stored_cp else False
            concelho_match = normalize(nom_municipality) == normalize(stored_concelho)
            distrito_match = normalize(nom_state) == normalize(stored_distrito)

            flags = []
            if not cp_match and nom_postcode:
                flags.append("CP_MISMATCH")
            if not concelho_match and nom_municipality:
                flags.append("CONCELHO_MISMATCH")
            if not distrito_match and nom_state:
                flags.append("DISTRITO_MISMATCH")

            writer.writerow({
                "id": row["id"],
                "nome": row["nome"],
                "stored_morada": row["morada"],
                "stored_codigo_postal": stored_cp,
                "stored_localidade": row.get("localidade", ""),
                "stored_freguesia": row.get("freguesia", ""),
                "stored_concelho": stored_concelho,
                "stored_distrito": stored_distrito,
                "lat": lat,
                "lng": lng,
                "nom_road": addr.get("road", ""),
                "nom_house_number": addr.get("house_number", ""),
                "nom_postcode": nom_postcode,
                "nom_suburb": addr.get("suburb", addr.get("neighbourhood", "")),
                "nom_city": addr.get("city", addr.get("town", addr.get("village", ""))),
                "nom_municipality": nom_municipality,
                "nom_county": nom_county,
                "nom_state": nom_state,
                "nom_display_name": result.get("display_name", result.get("error", "")),
                "cp_match": cp_match,
                "concelho_match": concelho_match,
                "distrito_match": distrito_match,
                "flag": "|".join(flags),
            })

            if (i + 1) % 100 == 0:
                out_file.flush()
                print(f"  {i + 1}/{len(remaining)} processed")

            time.sleep(DELAY)

    except KeyboardInterrupt:
        print("\nInterrupted — progress saved.")
    finally:
        out_file.flush()
        out_file.close()

    # Summary
    results = list(csv.DictReader(open(OUTPUT, encoding="utf-8")))
    flagged = [r for r in results if r["flag"]]
    print(f"\nDone. {len(results)} rows processed, {len(flagged)} flagged.")
    from collections import Counter
    flag_counts = Counter()
    for r in flagged:
        for f in r["flag"].split("|"):
            if f:
                flag_counts[f] += 1
    for flag, count in flag_counts.most_common():
        print(f"  {flag}: {count}")

if __name__ == "__main__":
    main()
