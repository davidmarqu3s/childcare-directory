#!/usr/bin/env python3
"""
Compare Carta Social map coordinates against our CSV lat/lng.

For each institution:
  - Fetches the CS map page (idEquipment = row id)
  - Extracts Google Maps LatLng from JS
  - Computes Haversine distance vs our coordinates
  - Classifies result:
      MATCH        — distance ≤ 100 m (or both missing)
      MINOR        — 100 m < distance ≤ 500 m
      MISMATCH     — distance > 500 m
      CS_ONLY      — we have no coords, CS does
      NO_CS_COORDS — CS page returned no coordinates
      ERROR        — fetch failed

Usage:
  uv run --with requests --with beautifulsoup4 python3 check_cs_coords.py

Output: cs_coord_check.csv
"""

import csv
import math
import re
import time
from datetime import datetime
from pathlib import Path

import requests

CSV_PATH = Path("creches_portugal.csv")
OUTPUT_PATH = Path("cs_coord_check.csv")
DELAY = 0.5  # seconds between requests

MAP_URL = (
    "https://www.cartasocial.pt/resultados-da-pesquisa"
    "?p_p_id=SocialLetterPortlet_WAR_cartasocialportlet"
    "&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
    "&p_p_col_id=column-1&p_p_col_count=1"
    "&_SocialLetterPortlet_WAR_cartasocialportlet__facesViewIdRender="
    "%2Fviews%2FsocialLetter%2Flist%2Fview%2Fequipment%2Fequipment_maps.xhtml"
    "&_SocialLetterPortlet_WAR_cartasocialportlet_idEquipment={id}"
)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; coord-check/1.0)"}

LATLNG_RE = re.compile(r"new google\.maps\.LatLng\(([-\d.]+),\s*([-\d.]+)\)")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def extract_cs_coords(html: str) -> tuple[float, float] | None:
    m = LATLNG_RE.search(html)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def classify(our_lat, our_lng, cs_lat, cs_lng, distance_m) -> str:
    has_ours = our_lat is not None
    has_cs = cs_lat is not None
    if not has_cs:
        return "NO_CS_COORDS"
    if not has_ours:
        return "CS_ONLY"
    if distance_m <= 100:
        return "MATCH"
    if distance_m <= 500:
        return "MINOR"
    return "MISMATCH"


def main() -> None:
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("id"):
                rows.append(row)

    # Load already-processed IDs for resume support
    done_ids: set[str] = set()
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("id"):
                    done_ids.add(r["id"])

    remaining = [r for r in rows if r["id"] not in done_ids]
    total = len(rows)
    print(f"Total: {total} | Already done: {len(done_ids)} | Remaining: {len(remaining)}")
    if not remaining:
        print("Nothing to do.")
        return

    session = requests.Session()
    session.headers.update(HEADERS)

    counts = {"MATCH": 0, "MINOR": 0, "MISMATCH": 0, "CS_ONLY": 0, "NO_CS_COORDS": 0, "ERROR": 0}

    # Append to existing output so previous results are preserved
    file_mode = "a" if done_ids else "w"
    with open(OUTPUT_PATH, file_mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "id", "nome", "our_lat", "our_lng", "cs_lat", "cs_lng",
            "distance_m", "status", "error",
        ])
        if not done_ids:
            writer.writeheader()

        for i, row in enumerate(remaining):
            inst_id = row["id"]
            nome = row.get("nome", "")

            our_lat = float(row["latitude"]) if row.get("latitude") else None
            our_lng = float(row["longitude"]) if row.get("longitude") else None

            try:
                resp = session.get(MAP_URL.format(id=inst_id), timeout=15)
                resp.raise_for_status()
                cs_coords = extract_cs_coords(resp.text)
            except Exception as e:
                counts["ERROR"] += 1
                writer.writerow({
                    "id": inst_id, "nome": nome,
                    "our_lat": our_lat, "our_lng": our_lng,
                    "cs_lat": "", "cs_lng": "",
                    "distance_m": "", "status": "ERROR", "error": str(e),
                })
                f.flush()
                print(f"  [{i+1}/{len(remaining)}] ERROR     id={inst_id} — {e}", flush=True)
                time.sleep(DELAY)
                continue

            cs_lat, cs_lng = cs_coords if cs_coords else (None, None)

            distance_m = None
            if our_lat is not None and cs_lat is not None:
                distance_m = haversine_m(our_lat, our_lng, cs_lat, cs_lng)

            status = classify(our_lat, our_lng, cs_lat, cs_lng, distance_m)
            counts[status] += 1

            writer.writerow({
                "id": inst_id, "nome": nome,
                "our_lat": our_lat if our_lat is not None else "",
                "our_lng": our_lng if our_lng is not None else "",
                "cs_lat": cs_lat if cs_lat is not None else "",
                "cs_lng": cs_lng if cs_lng is not None else "",
                "distance_m": f"{distance_m:.0f}" if distance_m is not None else "",
                "status": status, "error": "",
            })
            f.flush()

            n = len(remaining)
            if status in ("MISMATCH", "MINOR", "CS_ONLY"):
                dist_str = f"{distance_m:.0f}m" if distance_m is not None else "—"
                print(f"  [{i+1}/{n}] {status:<12} id={inst_id}  dist={dist_str}  {nome[:50]}", flush=True)
            elif (i + 1) % 100 == 0:
                pct = (i + 1) / n * 100
                print(f"  [{i+1}/{n}] {pct:.0f}%  {counts}", flush=True)

            time.sleep(DELAY)

    print(f"\n── Results ──────────────────────────────────────────")
    print(f"  Total checked : {total}")
    for k, v in counts.items():
        print(f"  {k:<14}: {v}")
    print(f"\nFull results: {OUTPUT_PATH}")
    print(f"Run completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
