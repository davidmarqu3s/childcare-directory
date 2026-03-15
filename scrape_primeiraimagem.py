"""
Scraper for primeiraimagem.com

Step 1: Scrape concelho pages → get all institution names (fast, ~163 pages)
Step 2: Fuzzy-match against creches_portugal.csv → find missing institutions
Step 3: Scrape detail pages only for missing ones → save to primeiraimagem.csv
"""

import asyncio
import csv
import re
import unicodedata
import aiohttp
from bs4 import BeautifulSoup, NavigableString
from tqdm.asyncio import tqdm

BASE = "https://www.primeiraimagem.com"
CONCURRENCY = 15

SKIP_PAGES = {
    "index.php", "listagem.php", "pdc.php", "parceiros.php",
    "sitemap.php", "quemsomos.php", "contactos.php", "testemunhos.php",
    "cookies.php", "politica_privacidade.php", "quiz.php",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def normalise(s: str) -> str:
    """Lowercase, strip accents, remove punctuation — for fuzzy name matching."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")  # strip accents
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


async def fetch(session: aiohttp.ClientSession, url: str) -> tuple[str, str]:
    for attempt in range(3):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                return url, await r.text(encoding="utf-8", errors="replace")
        except Exception as e:
            if attempt == 2:
                print(f"  FAILED {url}: {e}")
                return url, ""
            await asyncio.sleep(1)


def get_concelho_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        path = href.split("primeiraimagem.com/")[-1].lstrip("/") if "primeiraimagem.com/" in href else href.lstrip("/")
        if path.endswith(".php") and "/" not in path and path not in SKIP_PAGES:
            urls.add(f"{BASE}/{path}")
    return sorted(urls)


def get_institution_links(html: str, concelho_url: str) -> list[tuple[str, str, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    concelho = concelho_url.split("/")[-1].replace(".php", "")
    results = []
    for row in soup.select("table.table-condensed tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        a = cells[1].find("a")
        if not a:
            continue
        name = a.get_text(strip=True)
        href = a["href"]
        url = href if href.startswith("http") else f"{BASE}/{href.lstrip('/')}"
        localidade = cells[2].get_text(strip=True)
        results.append((url, name, localidade, concelho))
    return results


def parse_institution(html: str, url: str, name: str, localidade: str, concelho: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "url": url, "nome": name, "localidade": localidade, "concelho": concelho,
        "morada": "", "codigo_postal": "", "cidade": "", "telefone": "", "email": "", "website": "",
    }
    container = soup.select_one("div.hidden-xs")
    if container:
        all_texts = []
        for node in container.descendants:
            if not isinstance(node, NavigableString):
                continue
            text = str(node).strip()
            if text and text not in ("Tel.", "Email:"):
                all_texts.append(text)

        postal_idx = next((i for i, l in enumerate(all_texts) if re.search(r'\d{4}[\s-]+\d{3}', l)), None)
        if postal_idx is not None:
            name_parts = {p.strip() for p in re.split(r'[–\-]', name) if p.strip()}
            name_parts.add(name.strip())
            # "Perfil" is a section label that appears as text in some pages
            address_parts = [l for l in all_texts[:postal_idx] if l not in name_parts and l != "Perfil"]
            data["morada"] = " ".join(address_parts)
            m = re.match(r'(\d{4}[\s-]+\d{3})\s+(.*)', all_texts[postal_idx])
            if m:
                data["codigo_postal"] = m.group(1).strip()
                data["cidade"] = m.group(2).strip()
            for l in all_texts[postal_idx + 1:]:
                if re.match(r'^\d{9}$', re.sub(r'\s', '', l)):
                    data["telefone"] = l.strip()
                    break

    for a in soup.find_all("a", href=True):
        if a["href"].startswith("mailto:"):
            data["email"] = a["href"][7:]
            break

    skip = {"primeiraimagem.com", "facebook.com", "instagram.com", "twitter.com", "blogspot", "caislisbon.org"}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and not any(d in href for d in skip):
            data["website"] = href
            break

    return data


async def main():
    connector = aiohttp.TCPConnector(limit_per_host=CONCURRENCY, ssl=False)

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:

        # ── Step 1: Collect all institution names from concelho pages ──────────
        print("Fetching homepage...")
        _, home_html = await fetch(session, BASE)
        concelho_urls = get_concelho_urls(home_html)
        print(f"Found {len(concelho_urls)} concelho pages\n")

        concelho_pages = await tqdm.gather(
            *[fetch(session, url) for url in concelho_urls],
            desc="Scraping concelho pages", unit="page"
        )

        all_institutions = []
        seen = set()
        for url, html in concelho_pages:
            if not html:
                continue
            for link in get_institution_links(html, url):
                if link[0] not in seen:
                    seen.add(link[0])
                    all_institutions.append(link)  # (url, name, localidade, concelho)

        print(f"\nFound {len(all_institutions)} institutions on primeiraimagem.com")

        # ── Step 2: Compare names against Carta Social CSV ────────────────────
        print("\nLoading creches_portugal.csv...")
        with open("creches_portugal.csv", encoding="utf-8") as f:
            carta_social = list(csv.DictReader(f))

        carta_names = {normalise(r["nome"]) for r in carta_social}

        missing = []
        matched = []
        for inst in all_institutions:
            url, name, localidade, concelho = inst
            if normalise(name) in carta_names:
                matched.append(inst)
            else:
                missing.append(inst)

        print(f"  Matched in Carta Social : {len(matched)}")
        print(f"  NOT in Carta Social     : {len(missing)}")

        # ── Step 3: Scrape detail pages only for missing institutions ──────────
        print(f"\nScraping {len(missing)} detail pages...")
        url_meta = {inst[0]: inst for inst in missing}

        results = []
        with tqdm(total=len(url_meta), desc="Detail pages", unit="page") as bar:
            for coro in asyncio.as_completed([fetch(session, url) for url in url_meta]):
                url, html = await coro
                _, name, localidade, concelho = url_meta[url]
                results.append(parse_institution(html, url, name, localidade, concelho))
                bar.update(1)

    # ── Step 4: Write CSV ──────────────────────────────────────────────────────
    fields = ["nome", "localidade", "concelho", "morada", "codigo_postal", "cidade", "telefone", "email", "website", "url"]
    with open("primeiraimagem.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    print(f"\nDone. {len(results)} institutions not in Carta Social → primeiraimagem.csv")


if __name__ == "__main__":
    asyncio.run(main())
