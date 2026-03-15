#!/usr/bin/env python3
"""
Carta Social scraper — crèches and jardins de infância across Portugal
Output: creches_portugal.csv

Two-phase approach:
  1. Collect all institution IDs, names and concelhos from list pages (JS-paginated)
  2. Fetch detail pages for each ID and extract remaining fields
"""

import asyncio
import csv
import re
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

RESPONSE_TYPES = [
    ("1103", "Creche"),
    ("1104", "Jardim de Infância"),
]

VALENCE = "1"  # Infância e Juventude

LIST_URL = (
    "https://www.cartasocial.pt/resultados-da-pesquisa"
    "?vt={vt}&tp={tp}&l={l}"
)

DETAIL_URL = (
    "https://www.cartasocial.pt/en/search-results"
    "?p_p_id=SocialLetterPortlet_WAR_cartasocialportlet"
    "&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
    "&p_p_col_id=column-1&p_p_col_count=1"
    "&_SocialLetterPortlet_WAR_cartasocialportlet__facesViewIdRender="
    "%2Fviews%2FsocialLetter%2Flist%2Fview%2Fequipment%2Fequipment_detail.xhtml"
    "&_SocialLetterPortlet_WAR_cartasocialportlet_idEquipment={id}"
)

CSV_FIELDS = [
    "id", "nome", "tipo", "distrito", "concelho",
    "morada", "codigo_postal", "localidade",
    "telefone", "email",
    "entidade_proprietaria", "natureza_juridica",
    "capacidade", "utentes", "horario", "ultima_atualizacao",
]

JS_CLICK_NEXT = (
    "const btn = document.querySelector("
    "'.ui-paginator-next:not(.ui-state-disabled)');"
    " if (btn) btn.click();"
)


def is_last_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    btn = soup.select_one(".ui-paginator-next")
    return btn is None or "ui-state-disabled" in btn.get("class", [])


def extract_listings_from_html(html: str) -> list[dict]:
    """Extract id, nome, concelho from a list page."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("li.ui-datalist-item"):
        a = li.select_one("a.entry")
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"idEquipment=(\d+)", href)
        if not m:
            continue
        equip_id = m.group(1)
        nome = a.select_one(".equipment-title")
        concelho = a.select_one(".equipment-location")
        items.append({
            "id": equip_id,
            "nome": nome.get_text(strip=True) if nome else "",
            "concelho": concelho.get_text(strip=True) if concelho else "",
        })
    return items


def parse_detail(html: str, base: dict) -> dict:
    """Enrich a base record (id, tipo, distrito, nome, concelho) with detail page fields."""
    soup = BeautifulSoup(html, "html.parser")
    data = dict(base)

    # Institution name from <h2> without class, strip "ui-button " prefix
    if not data.get("nome"):
        for h2 in soup.select("h2"):
            if not h2.get("class"):
                text = re.sub(r"^ui-button\s*", "", h2.get_text(" ", strip=True), flags=re.IGNORECASE).strip()
                if text and text.lower() not in ("search results",):
                    data["nome"] = text
                    break

    # Contact fields — always appear in fixed order in <p> tags with no class:
    # [0] address, [1] postal+locality, [2] phone?, [3] email?, [4] entity, [5] legal nature
    _footer = ("translated automatically", "© GEP", "Developed by")
    p_texts = [
        p.get_text(" ", strip=True)
        for p in soup.select("p")
        if not p.get("class")
        and p.get_text(strip=True)
        and not any(kw in p.get_text(" ", strip=True) for kw in _footer)
    ]

    if p_texts:
        # First <p> is always the address line
        data["morada"] = p_texts[0]

    for text in p_texts[1:]:
        # Postal code — new format: "7440-045 ALTER DO CHÃO"
        m = re.match(r"^(\d{4}-\d{3})\s+(.+)$", text)
        if m and "codigo_postal" not in data:
            data["codigo_postal"] = m.group(1)
            data["localidade"] = m.group(2).strip()
            continue

        # Postal code — old formats: "7460 CABEÇO DE VIDE" or "7400 021 GALVEIAS"
        m = re.match(r"^(\d{4})(?:\s+(\d{3}))?\s+([A-ZÁÉÍÓÚÀÃÕÇ].+)$", text)
        if m and "codigo_postal" not in data:
            data["codigo_postal"] = f"{m.group(1)}-{m.group(2)}" if m.group(2) else m.group(1)
            data["localidade"] = m.group(3).strip()
            continue

        # Email
        if "@" in text and re.match(r"^[\w._%+\-]+@[\w.\-]+\.\w+$", text):
            data.setdefault("email", text)
            continue

        # Phone — strip non-digits and check length
        clean = re.sub(r"[\s\-\+\(\)]", "", text)
        if clean.isdigit() and 7 <= len(clean) <= 15:
            data.setdefault("telefone", clean)
            continue

        # Entity name (all caps, no digits)
        if text == text.upper() and len(text) > 5 and not re.search(r"\d", text):
            data.setdefault("entidade_proprietaria", text)
            continue

        # Legal nature — first mixed-case line after entity name
        if "entidade_proprietaria" in data and "natureza_juridica" not in data:
            data["natureza_juridica"] = text

    # Services table: tbody.ui-datatable-data tr td[role="gridcell"]
    # PrimeFaces injects <span class="ui-column-title"> for responsive layout — strip them first
    for span in soup.select(".ui-column-title"):
        span.decompose()
    for row in soup.select("tbody.ui-datatable-data tr.ui-widget-content"):
        cells = [td.get_text(" ", strip=True) for td in row.select("td[role='gridcell']")]
        if len(cells) >= 4:
            data.setdefault("capacidade", cells[1] if len(cells) > 1 else "")
            data.setdefault("utentes", cells[2] if len(cells) > 2 else "")
            data.setdefault("horario", cells[3] if len(cells) > 3 else "")
            data.setdefault("ultima_atualizacao", cells[4] if len(cells) > 4 else "")
            break

    return data


async def collect_listings(
    crawler: AsyncWebCrawler,
    dist_code: str,
    dist_name: str,
    type_code: str,
    type_name: str,
) -> list[dict]:
    """Collect all institution listings for a district + type by paginating with JS clicks."""
    url = LIST_URL.format(vt=VALENCE, tp=type_code, l=dist_code)
    session_id = f"list_{dist_code}_{type_code}"
    listings: list[dict] = []
    seen_ids: set[str] = set()
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
            print(f"    [warn] page {page + 1} failed")
            break

        for item in extract_listings_from_html(result.html):
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                listings.append({
                    **item,
                    "tipo": type_name,
                    "distrito": dist_name,
                })

        page += 1
        if is_last_page(result.html):
            break
        await asyncio.sleep(0.5)

    return listings


async def fetch_detail(
    crawler: AsyncWebCrawler,
    base: dict,
) -> dict:
    url = DETAIL_URL.format(id=base["id"])
    config = CrawlerRunConfig(
        page_timeout=30000,
        cache_mode=CacheMode.ENABLED,
    )
    result = await crawler.arun(url, config=config)
    if not result.success:
        return base
    return parse_detail(result.html, base)


async def main() -> None:
    output = Path("creches_portugal.csv")
    browser_cfg = BrowserConfig(headless=True, viewport_width=1280, viewport_height=900)

    # ── Phase 1: collect listings ─────────────────────────────────────────────
    print("Phase 1: collecting institution listings...")
    all_listings: list[dict] = []
    seen_ids: set[str] = set()

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        for dist_code, dist_name in DISTRICTS:
            for type_code, type_name in RESPONSE_TYPES:
                print(f"  {dist_name} — {type_name} ...", end=" ", flush=True)
                items = await collect_listings(crawler, dist_code, dist_name, type_code, type_name)
                new = [i for i in items if i["id"] not in seen_ids]
                for i in new:
                    seen_ids.add(i["id"])
                all_listings.extend(new)
                print(f"{len(new)} found (total: {len(all_listings)})")
                await asyncio.sleep(1)

    print(f"\nTotal unique institutions: {len(all_listings)}")

    # ── Phase 2: fetch detail pages ───────────────────────────────────────────
    print("\nPhase 2: fetching detail pages...")

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()

            for i, base in enumerate(all_listings):
                record = await fetch_detail(crawler, base)
                writer.writerow(record)

                if (i + 1) % 100 == 0:
                    print(f"  {i + 1}/{len(all_listings)}")

                await asyncio.sleep(0.3)

    print(f"\nDone — saved to {output}")


if __name__ == "__main__":
    asyncio.run(main())
