"""
Verify postcodes in creches_portugal.csv against Carta Social detail pages.
Samples 40 institutions spread across districts and tipos.
"""

import asyncio
import csv
import re
import random
from collections import defaultdict
from datetime import datetime

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig

# ── Sample selection ──────────────────────────────────────────────────────────

def select_sample(csv_path: str, n: int = 40, seed: int = 42) -> list[dict]:
    random.seed(seed)
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    rows_with_cp = [r for r in rows if r["codigo_postal"].strip()]

    groups = defaultdict(list)
    for r in rows_with_cp:
        key = (r["distrito"], r["tipo"])
        groups[key].append(r)

    sorted_keys = sorted(groups.keys())
    random.shuffle(sorted_keys)

    sample = []
    for key in sorted_keys:
        pool = groups[key]
        pick = min(2, len(pool))
        sample.extend(random.sample(pool, pick))
        if len(sample) >= n:
            break

    return sample[:n]


# ── Postcode extraction ───────────────────────────────────────────────────────

# Portuguese postcode: 4 digits, hyphen, 3 digits
POSTCODE_RE = re.compile(r"\b(\d{4}-\d{3})\b")


def extract_postcode_from_text(text: str) -> str | None:
    """
    Find postcode(s) in page text. Returns the first match that looks like a
    real PT postcode (not a phone number fragment, etc.).
    """
    matches = POSTCODE_RE.findall(text)
    if matches:
        return matches[0]
    return None


# ── URL builder ───────────────────────────────────────────────────────────────

BASE_URL = (
    "https://www.cartasocial.pt/en/search-results"
    "?p_p_id=SocialLetterPortlet_WAR_cartasocialportlet"
    "&p_p_lifecycle=0"
    "&p_p_state=normal"
    "&p_p_mode=view"
    "&p_p_col_id=column-1"
    "&p_p_col_count=1"
    "&_SocialLetterPortlet_WAR_cartasocialportlet__facesViewIdRender="
    "%2Fviews%2FsocialLetter%2Flist%2Fview%2Fequipment%2Fequipment_detail.xhtml"
    "&_SocialLetterPortlet_WAR_cartasocialportlet_idEquipment={id}"
)


def detail_url(equipment_id: str) -> str:
    return BASE_URL.format(id=equipment_id)


# ── Main crawl ────────────────────────────────────────────────────────────────

async def check_postcodes(csv_path: str, results_path: str):
    sample = select_sample(csv_path)
    print(f"Selected {len(sample)} institutions to verify.\n")

    browser_cfg = BrowserConfig(headless=True, verbose=False)
    # Wait for the portlet content to appear
    run_cfg = CrawlerRunConfig(
        wait_for="css:table",
        page_timeout=30_000,
        delay_before_return_html=2.0,
    )

    results = []

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        for i, row in enumerate(sample, 1):
            eq_id = row["id"]
            nome = row["nome"]
            distrito = row["distrito"]
            tipo = row["tipo"]
            csv_cp = row["codigo_postal"].strip()
            url = detail_url(eq_id)

            print(f"[{i:02d}/40] ID={eq_id} | {nome[:55]}")

            try:
                result = await crawler.arun(url=url, config=run_cfg)

                if not result.success:
                    status = "LOAD_FAIL"
                    cs_cp = None
                    note = result.error_message or "Crawler returned failure"
                else:
                    # Use markdown text (cleaner than raw HTML)
                    page_text = result.markdown or result.cleaned_html or ""

                    # Try to find postcode in text
                    cs_cp = extract_postcode_from_text(page_text)

                    if cs_cp is None:
                        status = "NO_POSTCODE"
                        note = "Pattern not found on page"
                    elif cs_cp == csv_cp:
                        status = "MATCH"
                        note = ""
                    else:
                        status = "MISMATCH"
                        note = f"CSV={csv_cp} | CS={cs_cp}"

            except Exception as e:
                status = "ERROR"
                cs_cp = None
                note = str(e)[:120]

            results.append({
                "id": eq_id,
                "nome": nome,
                "distrito": distrito,
                "tipo": tipo,
                "csv_postcode": csv_cp,
                "cs_postcode": cs_cp or "",
                "status": status,
                "note": note,
                "url": url,
            })

            icon = {"MATCH": "✓", "MISMATCH": "✗", "LOAD_FAIL": "!", "NO_POSTCODE": "?", "ERROR": "E"}[status]
            print(f"         {icon} {status:12s} CSV={csv_cp:8s} CS={cs_cp or '—':8s} {note}")

            # Small delay to be polite
            await asyncio.sleep(1.0)

    # ── Write results file ────────────────────────────────────────────────────
    matches = [r for r in results if r["status"] == "MATCH"]
    mismatches = [r for r in results if r["status"] == "MISMATCH"]
    no_postcode = [r for r in results if r["status"] == "NO_POSTCODE"]
    load_fails = [r for r in results if r["status"] in ("LOAD_FAIL", "ERROR")]

    with open(results_path, "w") as f:
        f.write(f"Postcode Verification — Carta Social vs creches_portugal.csv\n")
        f.write(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Sample: {len(results)} institutions\n")
        f.write("=" * 70 + "\n\n")

        f.write(f"SUMMARY\n")
        f.write(f"  Matches:       {len(matches)}\n")
        f.write(f"  Mismatches:    {len(mismatches)}\n")
        f.write(f"  No postcode:   {len(no_postcode)}\n")
        f.write(f"  Load failures: {len(load_fails)}\n")
        f.write("\n")

        if mismatches:
            f.write("MISMATCHES — REQUIRES ATTENTION\n")
            f.write("-" * 70 + "\n")
            for r in mismatches:
                f.write(f"  ID {r['id']:>6} | {r['nome'][:55]}\n")
                f.write(f"           Distrito: {r['distrito']} | Tipo: {r['tipo']}\n")
                f.write(f"           CSV postcode : {r['csv_postcode']}\n")
                f.write(f"           CS  postcode : {r['cs_postcode']}\n")
                f.write(f"           URL: {r['url']}\n\n")

        if no_postcode:
            f.write("NO POSTCODE FOUND ON PAGE\n")
            f.write("-" * 70 + "\n")
            for r in no_postcode:
                f.write(f"  ID {r['id']:>6} | {r['nome'][:55]}\n")
                f.write(f"           URL: {r['url']}\n\n")

        if load_fails:
            f.write("LOAD FAILURES / ERRORS\n")
            f.write("-" * 70 + "\n")
            for r in load_fails:
                f.write(f"  ID {r['id']:>6} | {r['nome'][:55]}\n")
                f.write(f"           Status: {r['status']}\n")
                f.write(f"           Note:   {r['note']}\n")
                f.write(f"           URL: {r['url']}\n\n")

        if matches:
            f.write("MATCHES\n")
            f.write("-" * 70 + "\n")
            for r in matches:
                f.write(f"  ID {r['id']:>6} | {r['csv_postcode']:8s} | {r['nome'][:55]}\n")
            f.write("\n")

        f.write("=" * 70 + "\n")
        f.write("ALL RESULTS\n")
        f.write("-" * 70 + "\n")
        f.write(f"{'ID':>6}  {'STATUS':12s}  {'CSV_CP':8s}  {'CS_CP':8s}  {'NOME'}\n")
        for r in results:
            f.write(f"{r['id']:>6}  {r['status']:12s}  {r['csv_postcode']:8s}  {r['cs_postcode']:8s}  {r['nome'][:55]}\n")

    print("\n" + "=" * 70)
    print(f"RESULTS SUMMARY")
    print(f"  Matches:       {len(matches)}")
    print(f"  Mismatches:    {len(mismatches)}")
    print(f"  No postcode:   {len(no_postcode)}")
    print(f"  Load failures: {len(load_fails)}")
    if mismatches:
        print(f"\n  MISMATCHES:")
        for r in mismatches:
            print(f"    ID {r['id']} — {r['nome'][:50]}")
            print(f"      CSV={r['csv_postcode']}  CS={r['cs_postcode']}")
    print(f"\nFull results written to: {results_path}")


if __name__ == "__main__":
    asyncio.run(check_postcodes(
        csv_path="/Users/D/Documents/GitHub/childcare-directory/creches_portugal.csv",
        results_path="/Users/D/Documents/GitHub/childcare-directory/postcode_check_results.txt",
    ))
