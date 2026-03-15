"""
Enrich creches_portugal.csv with Google Knowledge Panel names.

Adds a `nome_google` column. Skips rows already enriched.
Routes through Tor (SOCKS5 on 127.0.0.1:9050) and rotates circuit every 50 requests.
"""

import asyncio
import csv
import time
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from bs4 import BeautifulSoup
from stem import Signal
from stem.control import Controller

INPUT = "creches_portugal.csv"
DELAY = 5          # seconds between requests
ROTATE_EVERY = 50  # rotate Tor circuit every N requests
CHECKPOINT_EVERY = 100


def rotate_tor_circuit():
    try:
        with Controller.from_port(port=9051) as c:
            c.authenticate()
            c.signal(Signal.NEWNYM)
        time.sleep(5)  # wait for new circuit to establish
        print("  ↻ Tor circuit rotated")
    except Exception as e:
        print(f"  ⚠ Could not rotate Tor circuit: {e}")


async def get_knowledge_panel_name(crawler, nome, localidade):
    q = f"{nome} {localidade} Portugal".replace(" ", "+")
    url = f"https://www.google.com/search?q={q}&hl=pt&gl=pt"
    result = await crawler.arun(url, config=CrawlerRunConfig(
        page_timeout=30000,
        cache_mode=CacheMode.BYPASS,
        screenshot=False,
    ))
    if not result.success:
        return None, "fetch_failed"

    if "unusual traffic" in result.html.lower() or "captcha" in result.html.lower():
        return None, "captcha"

    soup = BeautifulSoup(result.html, "html.parser")

    el = soup.select_one('[data-attrid="title"]')
    if el:
        return el.get_text(strip=True), "panel"

    h3 = soup.select_one("h3")
    if h3:
        return h3.get_text(strip=True), "h3"

    return None, "not_found"


async def main():
    with open(INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    if "nome_google" not in fieldnames:
        fieldnames.append("nome_google")
        for r in rows:
            r.setdefault("nome_google", "")

    to_enrich = [(i, r) for i, r in enumerate(rows) if not r.get("nome_google")]
    total = len(to_enrich)
    print(f"Rows to enrich: {total} / {len(rows)}")
    print(f"Routing through Tor — rotating circuit every {ROTATE_EVERY} requests\n")

    found = 0

    browser_config = BrowserConfig(
        headless=True,
        proxy_config={"server": "socks5://127.0.0.1:9050"},
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        for idx, (row_idx, row) in enumerate(to_enrich):

            # Rotate circuit before starting and every ROTATE_EVERY rows
            if idx % ROTATE_EVERY == 0:
                rotate_tor_circuit()

            nome, source = await get_knowledge_panel_name(crawler, row["nome"], row["localidade"])

            if source == "captcha":
                print(f"\n⚠ CAPTCHA at row {row_idx} ({row['nome'][:40]}). Rotating circuit and retrying...")
                rotate_tor_circuit()
                nome, source = await get_knowledge_panel_name(crawler, row["nome"], row["localidade"])
                if source == "captcha":
                    print("  Still blocked. Stopping — resume later.")
                    break

            status = f"→ {nome[:50]}" if nome else "✗"
            src_tag = f"[{source}]" if nome else "[ ]"
            print(f"[{idx+1}/{total}] {row['nome'][:40]:<40} {src_tag} {status}")

            if nome and source == "panel":
                rows[row_idx]["nome_google"] = nome
                found += 1

            await asyncio.sleep(DELAY)

            if (idx + 1) % CHECKPOINT_EVERY == 0:
                _save(rows, fieldnames)
                print(f"\n  ── Checkpoint saved ({idx+1} processed, {found} found) ──\n")

    _save(rows, fieldnames)
    remaining = sum(1 for r in rows if not r.get("nome_google"))
    print(f"\nDone. {found} names found this run. Rows still empty: {remaining}")


def _save(rows, fieldnames):
    with open(INPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    asyncio.run(main())
