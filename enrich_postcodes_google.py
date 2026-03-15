"""
Enrich remaining incomplete postal codes via Google search (Crawl4AI browser).
"""

import asyncio
import csv
import re
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

INPUT = "creches_portugal.csv"
POSTCODE_RE = re.compile(r'\b(\d{4}-\d{3})\b')


def is_complete(code: str) -> bool:
    return bool(re.match(r'^\d{4}-\d{3}$', code)) and not code.endswith("-000")


def extract_postcode_from_text(text: str, base_code: str) -> str | None:
    """Find a postcode in text that starts with the known 4-digit base."""
    matches = POSTCODE_RE.findall(text)
    for m in matches:
        if not m.endswith("-000"):
            if not base_code or m.startswith(base_code[:4]):
                return m
    return None


async def google_search(crawler: AsyncWebCrawler, query: str, base_code: str) -> str | None:
    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}&kl=pt-pt"
    config = CrawlerRunConfig(
        page_timeout=20000,
        cache_mode=CacheMode.ENABLED,
        excluded_tags=["nav", "footer", "script"],
    )
    result = await crawler.arun(url, config=config)
    if result.success:
        return extract_postcode_from_text(result.markdown, base_code)
    return None


async def main():
    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    remaining = [(i, r) for i, r in enumerate(rows) if not is_complete(r.get("codigo_postal", ""))]
    print(f"Searching Google for {len(remaining)} postal codes...\n")

    browser_config = BrowserConfig(headless=True, viewport_width=1280, viewport_height=800)
    found = 0

    async with AsyncWebCrawler(config=browser_config) as crawler:
        for idx, (row_idx, row) in enumerate(remaining):
            nome = row["nome"].title()
            morada = row["morada"]
            localidade = row["localidade"]
            base = row.get("codigo_postal", "")

            queries = []
            if morada:
                queries.append(f'"{nome}" "{morada}" código postal Portugal')
            queries.append(f'"{nome}" {localidade} código postal Portugal')
            queries.append(f'{nome} {localidade} Portugal postcode')

            postcode = None
            for q in queries:
                postcode = await google_search(crawler, q, base)
                await asyncio.sleep(3)
                if postcode:
                    break

            status = f"→ {postcode}" if postcode else "✗ not found"
            print(f"[{idx+1}/{len(remaining)}] {nome[:45]:<45} {status}")

            if postcode:
                rows[row_idx]["codigo_postal"] = postcode
                found += 1

    with open(INPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nUpdated {found}/{len(remaining)} → {INPUT}")


if __name__ == "__main__":
    asyncio.run(main())
