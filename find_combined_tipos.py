#!/usr/bin/env python3
"""
Find institution IDs that appear in BOTH Creche (1103) AND Jardim de Infância (1104)
result sets on Carta Social. These should be tagged "Creche e Jardim de Infância".

Usage:
    uv run --with crawl4ai --with beautifulsoup4 python3 find_combined_tipos.py

    # Lisboa only (fast test):
    uv run --with crawl4ai --with beautifulsoup4 python3 find_combined_tipos.py --lisboa

Output:
    combined_tipos.txt  — one institution ID per line
"""

import asyncio
import csv
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

DISTRICTS = [
    ("01-00-00", "Aveiro"),
    ("02-00-00", "Beja"),
    ("03-00-00", "Braga"),
    ("04-00-00", "Bragança"),
    ("05-00-00", "Castelo Branco"),
    ("06-00-00", "Coimbra"),
    ("07-00-00", "Évora"),
    ("08-00-00", "Faro"),
    ("09-00-00", "Guarda"),
    ("10-00-00", "Leiria"),
    ("11-00-00", "Lisboa"),
    ("12-00-00", "Portalegre"),
    ("13-00-00", "Porto"),
    ("14-00-00", "Santarém"),
    ("15-00-00", "Setúbal"),
    ("16-00-00", "Viana do Castelo"),
    ("17-00-00", "Vila Real"),
    ("18-00-00", "Viseu"),
]

LISBOA_ONLY = [("11-00-00", "Lisboa")]

TYPE_CRECHE = ("1103", "Creche")
TYPE_JI = ("1104", "Jardim de Infância")

VALENCE = "1"
LIST_URL = "https://www.cartasocial.pt/resultados-da-pesquisa?vt={vt}&tp={tp}&l={l}"

JS_CLICK_NEXT = (
    "const btn = document.querySelector("
    "'.ui-paginator-next:not(.ui-state-disabled)');"
    " if (btn) btn.click();"
)

CSV_PATH = Path("creches_portugal.csv")
OUTPUT_PATH = Path("combined_tipos.txt")


def is_last_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    btn = soup.select_one(".ui-paginator-next")
    return btn is None or "ui-state-disabled" in btn.get("class", [])


def extract_ids_from_html(html: str) -> list[str]:
    """Extract institution IDs from a list page."""
    soup = BeautifulSoup(html, "html.parser")
    ids = []
    for li in soup.select("li.ui-datalist-item"):
        a = li.select_one("a.entry")
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"idEquipment=(\d+)", href)
        if m:
            ids.append(m.group(1))
    return ids


async def collect_ids_for_district_type(
    crawler: AsyncWebCrawler,
    dist_code: str,
    dist_name: str,
    type_code: str,
    type_label: str,
) -> set[str]:
    """Collect all institution IDs for one district + type combination."""
    url = LIST_URL.format(vt=VALENCE, tp=type_code, l=dist_code)
    session_id = f"list_{dist_code}_{type_code}"
    ids: set[str] = set()
    page = 0

    while True:
        if page == 0:
            config = CrawlerRunConfig(
                page_timeout=60000,
                session_id=session_id,
                wait_for="css:li.ui-datalist-item",
                cache_mode=CacheMode.BYPASS,
            )
            result = await crawler.arun(url, config=config)
        else:
            config = CrawlerRunConfig(
                page_timeout=60000,
                session_id=session_id,
                js_code=JS_CLICK_NEXT,
                js_only=True,
                wait_for="css:li.ui-datalist-item",
                cache_mode=CacheMode.BYPASS,
            )
            result = await crawler.arun(url, config=config)

        if not result.success:
            print(f"    [warn] {dist_name}/{type_label} page {page + 1} failed")
            break

        new_ids = extract_ids_from_html(result.html)

        # If we get no new items, the page may have no results at all
        if page == 0 and not new_ids:
            break

        ids.update(new_ids)
        page += 1

        if is_last_page(result.html):
            break

        await asyncio.sleep(0.5)

    return ids


def load_csv_lookup() -> dict[str, dict]:
    """Load existing CSV, keyed by institution ID."""
    if not CSV_PATH.exists():
        return {}
    lookup: dict[str, dict] = {}
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lookup[row["id"]] = row
    return lookup


async def main() -> None:
    lisboa_only = "--lisboa" in sys.argv
    districts = LISBOA_ONLY if lisboa_only else DISTRICTS

    if lisboa_only:
        print("Running Lisboa only (test mode)")
    else:
        print(f"Running all {len(districts)} districts")

    browser_cfg = BrowserConfig(headless=True, viewport_width=1280, viewport_height=900)

    # Collect IDs per type across all target districts
    creche_ids: set[str] = set()
    ji_ids: set[str] = set()

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        for dist_code, dist_name in districts:
            for (type_code, type_label), target_set in [
                (TYPE_CRECHE, creche_ids),
                (TYPE_JI, ji_ids),
            ]:
                print(f"  {dist_name} — {type_label} ...", end=" ", flush=True)
                ids = await collect_ids_for_district_type(
                    crawler, dist_code, dist_name, type_code, type_label
                )
                target_set.update(ids)
                print(f"{len(ids)} IDs")
                await asyncio.sleep(1)

    print(f"\nCreche IDs total:              {len(creche_ids)}")
    print(f"Jardim de Infância IDs total:  {len(ji_ids)}")

    combined = creche_ids & ji_ids
    print(f"IDs in BOTH (combined tipo):   {len(combined)}")

    # Save to file
    sorted_combined = sorted(combined, key=lambda x: int(x))
    OUTPUT_PATH.write_text("\n".join(sorted_combined) + "\n", encoding="utf-8")
    print(f"\nSaved {len(sorted_combined)} IDs to {OUTPUT_PATH}")

    # Cross-reference with CSV
    csv_lookup = load_csv_lookup()
    if csv_lookup:
        print(f"\nCross-reference with {CSV_PATH}:")
        print(f"  {'ID':<8}  {'Current tipo':<28}  {'Nome'}")
        print(f"  {'-'*8}  {'-'*28}  {'-'*50}")
        for eid in sorted_combined:
            row = csv_lookup.get(eid)
            if row:
                print(f"  {eid:<8}  {row.get('tipo', '?'):<28}  {row.get('nome', '?')}")
            else:
                print(f"  {eid:<8}  {'(not in CSV)':<28}  —")
    else:
        print(f"\n[info] {CSV_PATH} not found — skipping cross-reference")

    # Summary of what current tipo values look like for combined IDs
    if csv_lookup and combined:
        tipo_counts: dict[str, int] = {}
        not_in_csv = 0
        for eid in combined:
            row = csv_lookup.get(eid)
            if row:
                t = row.get("tipo", "")
                tipo_counts[t] = tipo_counts.get(t, 0) + 1
            else:
                not_in_csv += 1
        print(f"\nCurrent 'tipo' distribution for combined IDs:")
        for t, count in sorted(tipo_counts.items(), key=lambda x: -x[1]):
            print(f"  {count:>4}x  {t!r}")
        if not_in_csv:
            print(f"  {not_in_csv:>4}x  (not in CSV)")

    # IDs only in Creche
    creche_only = creche_ids - ji_ids
    # IDs only in JI
    ji_only = ji_ids - creche_ids
    print(f"\nBreakdown:")
    print(f"  Creche only:                   {len(creche_only)}")
    print(f"  Jardim de Infância only:       {len(ji_only)}")
    print(f"  Both (Creche e JI):            {len(combined)}")


if __name__ == "__main__":
    asyncio.run(main())
