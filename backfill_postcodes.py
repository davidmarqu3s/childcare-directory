# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "tqdm"]
# ///
"""
1. Downloads CP7 postcode → coordinates dataset from temospena/CP7.
2. Aggregates to one centroid per postcode → saves codigos_postais.csv.
3. Backfills latitude/longitude in creches_portugal.csv for rows missing coords.

Run with: uv run backfill_postcodes.py
"""

import csv
import io
import requests
from tqdm import tqdm

CP7_URL = "https://raw.githubusercontent.com/temospena/CP7/master/CP7%20Portugal/CP7_Portugal_nov2022.txt"
CRECHES_CSV = "creches_portugal.csv"
POSTCODE_CSV = "codigos_postais.csv"


def download_cp7() -> dict[str, tuple[float, float]]:
    """Download CP7 dataset and return {postcode: (lat, lng)} centroid map."""
    print("Downloading CP7 postcode dataset...")
    r = requests.get(CP7_URL, timeout=60)
    r.raise_for_status()
    r.encoding = "utf-8"

    # Accumulate lat/lng sums per postcode for centroid calculation
    sums: dict[str, list] = {}  # cp7 -> [lat_sum, lng_sum, count]

    reader = csv.DictReader(io.StringIO(r.text), delimiter="\t")
    for row in reader:
        cp7 = row.get("CP7", "").strip().strip('"')
        try:
            lat = float(row["Lat"])
            lng = float(row["Long"])
        except (ValueError, KeyError):
            continue
        if not cp7:
            continue
        if cp7 not in sums:
            sums[cp7] = [0.0, 0.0, 0]
        sums[cp7][0] += lat
        sums[cp7][1] += lng
        sums[cp7][2] += 1

    centroids = {
        cp7: (s[0] / s[2], s[1] / s[2])
        for cp7, s in sums.items()
        if s[2] > 0
    }
    print(f"  {len(centroids):,} unique postcodes loaded.")
    return centroids


def save_postcode_csv(centroids: dict[str, tuple[float, float]]) -> None:
    """Save postcode → centroid lookup as codigos_postais.csv."""
    with open(POSTCODE_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["codigo_postal", "latitude", "longitude"])
        for cp7, (lat, lng) in sorted(centroids.items()):
            writer.writerow([cp7, f"{lat:.7f}", f"{lng:.7f}"])
    print(f"  Saved {POSTCODE_CSV} ({len(centroids):,} rows).")


def backfill_creches(centroids: dict[str, tuple[float, float]]) -> None:
    """Backfill missing lat/lng in creches_portugal.csv using postcode centroids."""
    with open(CRECHES_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    missing = [r for r in rows if not r.get("latitude") or not r.get("longitude")]
    print(f"\nRows missing coordinates: {len(missing)}")

    filled = 0
    not_found = []
    for row in tqdm(missing, desc="Backfilling", unit="row"):
        cp = row.get("codigo_postal", "").strip()
        if cp in centroids:
            lat, lng = centroids[cp]
            row["latitude"] = f"{lat:.7f}"
            row["longitude"] = f"{lng:.7f}"
            filled += 1
        else:
            not_found.append((row.get("nome"), cp))

    with open(CRECHES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nBackfilled: {filled} rows")
    print(f"Still missing: {len(not_found)} rows")
    if not_found:
        print("  Could not match:")
        for nome, cp in not_found:
            print(f"    {nome!r} — postcode: {cp!r}")


if __name__ == "__main__":
    centroids = download_cp7()
    save_postcode_csv(centroids)
    backfill_creches(centroids)
    print("\nDone.")
