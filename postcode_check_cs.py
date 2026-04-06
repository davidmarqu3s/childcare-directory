#!/usr/bin/env python3
"""
Verify postcodes in creches_portugal.csv against live Carta Social detail pages.

Usage:
  uv run --with requests --with beautifulsoup4 python3 postcode_check_cs.py

Results written to postcode_check_results.txt.
"""

import csv
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CSV_PATH = Path("creches_portugal.csv")
RESULTS_PATH = Path("postcode_check_results.txt")
DELAY = 0.5  # seconds between requests

DETAIL_URL = (
    "https://www.cartasocial.pt/en/search-results"
    "?p_p_id=SocialLetterPortlet_WAR_cartasocialportlet"
    "&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
    "&p_p_col_id=column-1&p_p_col_count=1"
    "&_SocialLetterPortlet_WAR_cartasocialportlet__facesViewIdRender="
    "%2Fviews%2FsocialLetter%2Flist%2Fview%2Fequipment%2Fequipment_detail.xhtml"
    "&_SocialLetterPortlet_WAR_cartasocialportlet_idEquipment={id}"
)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; postcode-audit/1.0)"}


def extract_postcode(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    _footer = ("translated automatically", "© GEP", "Developed by")
    p_texts = [
        p.get_text(" ", strip=True)
        for p in soup.select("p")
        if not p.get("class")
        and p.get_text(strip=True)
        and not any(kw in p.get_text(" ", strip=True) for kw in _footer)
    ]
    for text in p_texts:
        m = re.match(r"^(\d{4}-\d{3})\s+", text)
        if m:
            return m.group(1)
        m = re.match(r"^(\d{4})(?:\s+(\d{3}))?\s+[A-ZÁÉÍÓÚÀÃÕÇ]", text)
        if m:
            return f"{m.group(1)}-{m.group(2)}" if m.group(2) else m.group(1)
    return None


def main() -> None:
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("codigo_postal") and row.get("id"):
                rows.append(row)

    total = len(rows)
    print(f"Checking all {total} institutions against Carta Social...\n")

    session = requests.Session()
    session.headers.update(HEADERS)

    matches, mismatches, errors = [], [], []

    for i, row in enumerate(rows):
        inst_id = row["id"]
        our_cp = row["codigo_postal"].strip()

        try:
            resp = session.get(DETAIL_URL.format(id=inst_id), timeout=15)
            resp.raise_for_status()
            cs_cp = extract_postcode(resp.text)
        except Exception as e:
            errors.append({"id": inst_id, "nome": row["nome"], "reason": str(e)})
            print(f"  [{i+1}/{total}] ERROR    id={inst_id} — {e}")
            time.sleep(DELAY)
            continue

        if cs_cp is None:
            errors.append({"id": inst_id, "nome": row["nome"], "reason": "postcode not found in page"})
            print(f"  [{i+1}/{total}] ERROR    id={inst_id} — postcode not found  {row['nome']}")
        elif cs_cp == our_cp:
            matches.append({"id": inst_id, "nome": row["nome"], "postcode": our_cp})
            if (i + 1) % 100 == 0:
                print(f"  [{i+1}/{total}] ...{len(matches)} matches, {len(mismatches)} mismatches, {len(errors)} errors so far")
        else:
            mismatches.append({"id": inst_id, "nome": row["nome"], "ours": our_cp, "carta_social": cs_cp})
            print(f"  [{i+1}/{total}] MISMATCH id={inst_id}  ours={our_cp}  cs={cs_cp}  {row['nome']}")

        time.sleep(DELAY)

    # Write results file
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        f.write(f"Postcode Verification — Carta Social vs creches_portugal.csv\n")
        f.write(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Checked: {total} institutions\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"SUMMARY\n")
        f.write(f"  Matches:    {len(matches)}\n")
        f.write(f"  Mismatches: {len(mismatches)}\n")
        f.write(f"  Errors:     {len(errors)}\n\n")
        if mismatches:
            f.write("MISMATCHES\n" + "-" * 70 + "\n")
            for m in mismatches:
                f.write(f"  id={m['id']}  ours={m['ours']}  cs={m['carta_social']}  {m['nome']}\n")
            f.write("\n")
        if errors:
            f.write("ERRORS\n" + "-" * 70 + "\n")
            for e in errors:
                f.write(f"  id={e['id']}  {e['reason']}  {e['nome']}\n")

    print(f"\n── Results ────────────────────────────────────")
    print(f"  Checked : {total}")
    print(f"  Match   : {len(matches)}")
    print(f"  Mismatch: {len(mismatches)}")
    print(f"  Errors  : {len(errors)}")
    if mismatches:
        print("\nMismatches:")
        for m in mismatches:
            print(f"  id={m['id']}  ours={m['ours']}  cs={m['carta_social']}  {m['nome']}")
    print(f"\nFull results: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
