"""
Postcode audit script for creches_portugal.csv
1. Internal consistency audit of all postcodes
2. Sample 25 institutions across different districts and fetch Carta Social pages
3. Compare CSV postcode vs Carta Social postcode
"""

import asyncio
import csv
import re
import random
from collections import defaultdict
from datetime import datetime

# ── Portuguese postcode district mapping ──────────────────────────────────────
# First digit(s) of 4-digit prefix → expected distrito(s)
# Source: CTT postcode zone assignments
POSTCODE_DISTRICT_MAP = {
    "1": ["Lisboa"],
    "2": ["Lisboa", "Setúbal", "Santarém", "Leiria"],   # 2xxx spans several
    "3": ["Coimbra", "Aveiro", "Viseu", "Castelo Branco", "Leiria"],
    "4": ["Porto", "Braga", "Viana do Castelo"],
    "5": ["Vila Real", "Bragança"],
    "6": ["Castelo Branco", "Guarda", "Coimbra"],
    "7": ["Évora", "Beja", "Portalegre", "Setúbal"],
    "8": ["Faro"],
    "9": ["Açores", "Madeira"],
}

# More precise: 2-digit prefix → narrow district list
POSTCODE_2DIG_MAP = {
    "10": ["Lisboa"], "11": ["Lisboa"], "12": ["Lisboa"], "13": ["Lisboa"],
    "14": ["Lisboa"], "15": ["Lisboa"], "16": ["Lisboa"], "17": ["Lisboa"],
    "18": ["Lisboa"], "19": ["Lisboa"],
    "20": ["Setúbal"], "21": ["Setúbal"], "22": ["Setúbal"], "23": ["Setúbal"],
    "24": ["Setúbal"], "25": ["Setúbal"], "26": ["Setúbal"], "27": ["Lisboa", "Setúbal"],
    "28": ["Lisboa", "Setúbal"],
    "29": ["Santarém", "Lisboa"],
    "30": ["Leiria", "Santarém"], "31": ["Leiria"], "32": ["Leiria"], "33": ["Leiria"],
    "34": ["Coimbra"], "35": ["Coimbra"], "36": ["Coimbra"], "37": ["Coimbra"],
    "38": ["Coimbra", "Castelo Branco"], "39": ["Coimbra"],
    "40": ["Aveiro"], "41": ["Aveiro"], "42": ["Aveiro"], "43": ["Aveiro"],
    "44": ["Aveiro", "Porto"], "45": ["Aveiro"],
    "46": ["Porto", "Aveiro"], "47": ["Porto", "Aveiro"],
    "48": ["Aveiro"],
    "49": ["Viseu", "Aveiro"],
    "50": ["Braga"], "51": ["Braga"], "52": ["Braga"], "53": ["Braga"],
    "54": ["Braga"], "55": ["Braga"], "56": ["Braga"], "57": ["Braga"],
    "58": ["Braga"],
    "59": ["Viana do Castelo", "Braga"],
    "60": ["Vila Real"], "61": ["Vila Real"], "62": ["Vila Real"], "63": ["Vila Real"],
    "64": ["Vila Real", "Braga"],
    "65": ["Bragança"], "66": ["Bragança"], "67": ["Bragança"],
    "68": ["Bragança", "Vila Real"],
    "69": ["Bragança"],
    "70": ["Évora"], "71": ["Évora"], "72": ["Évora"],
    "73": ["Portalegre", "Évora"],
    "74": ["Portalegre"], "75": ["Portalegre"],
    "76": ["Castelo Branco", "Portalegre"],
    "77": ["Guarda", "Castelo Branco"],
    "78": ["Beja"], "79": ["Beja"],
    "80": ["Faro"], "81": ["Faro"], "82": ["Faro"], "83": ["Faro"], "84": ["Faro"],
    "85": ["Faro"], "86": ["Faro"], "87": ["Faro"], "88": ["Faro"], "89": ["Faro"],
    "90": ["Açores"], "91": ["Açores"], "92": ["Açores"], "93": ["Açores"],
    "94": ["Açores"], "95": ["Açores"],
    "96": ["Madeira"], "97": ["Madeira"],
    "98": ["Madeira"], "99": ["Madeira"],
    # Porto 4xxx
    "40": ["Porto", "Aveiro"], "41": ["Porto", "Aveiro"],
    "42": ["Porto", "Aveiro"], "43": ["Porto", "Aveiro"],
    "44": ["Porto", "Aveiro"],
}

# Known Algarve (Faro district) postcode range: 8000–8999
# Known Lisboa postcode range: 1000–1999
# Known Porto postcode range: 4000–4999
# Known Braga: ~4700–4800 range

def postcode_prefix(cp):
    """Extract 4-digit numeric prefix from postcode like '1234-567'."""
    m = re.match(r'^(\d{4})-(\d{3})$', cp.strip())
    if not m:
        return None
    return m.group(1)

def postcode_check(cp, distrito):
    """
    Returns (is_suspicious, reason) tuple.
    Checks if the postcode prefix is geographically consistent with the distrito.
    """
    prefix = postcode_prefix(cp)
    if not prefix:
        return True, f"Invalid format: '{cp}'"

    first_two = prefix[:2]
    first_one = prefix[0]

    # Check strict Faro (Algarve): must be 8xxx
    if distrito == "Faro" and first_one != "8":
        return True, f"Faro distrito but postcode {cp} (prefix {prefix}, not 8xxx)"

    # Check strict Lisboa: must be 1xxx
    if distrito == "Lisboa" and first_one != "1":
        return True, f"Lisboa distrito but postcode {cp} (prefix {prefix}, not 1xxx)"

    # Check Porto: must be 4xxx
    if distrito == "Porto" and first_one != "4":
        return True, f"Porto distrito but postcode {cp} (prefix {prefix}, not 4xxx)"

    # Check Braga: must be 4xxx or 5xxx (rare)
    if distrito == "Braga" and first_one not in ("4", "5"):
        return True, f"Braga distrito but postcode {cp} (prefix {prefix}, not 4xxx/5xxx)"

    # Check Viana do Castelo: 4xxx
    if distrito == "Viana do Castelo" and first_one != "4":
        return True, f"Viana do Castelo but postcode {cp} (prefix {prefix}, not 4xxx)"

    # Check Aveiro: must be 3xxx or 4xxx
    if distrito == "Aveiro" and first_one not in ("3", "4"):
        return True, f"Aveiro distrito but postcode {cp} (prefix {prefix}, not 3xxx/4xxx)"

    # Check Coimbra: must be 3xxx
    if distrito == "Coimbra" and first_one != "3":
        return True, f"Coimbra distrito but postcode {cp} (prefix {prefix}, not 3xxx)"

    # Check Viseu: must be 3xxx
    if distrito == "Viseu" and first_one != "3":
        return True, f"Viseu distrito but postcode {cp} (prefix {prefix}, not 3xxx)"

    # Check Castelo Branco: 3xxx or 6xxx
    if distrito == "Castelo Branco" and first_one not in ("3", "6"):
        return True, f"Castelo Branco but postcode {cp} (prefix {prefix}, not 3xxx/6xxx)"

    # Check Guarda: 6xxx
    if distrito == "Guarda" and first_one != "6":
        return True, f"Guarda but postcode {cp} (prefix {prefix}, not 6xxx)"

    # Check Leiria: 2xxx or 3xxx
    if distrito == "Leiria" and first_one not in ("2", "3"):
        return True, f"Leiria but postcode {cp} (prefix {prefix}, not 2xxx/3xxx)"

    # Check Santarém: 2xxx
    if distrito == "Santarém" and first_one not in ("2",):
        return True, f"Santarém but postcode {cp} (prefix {prefix}, not 2xxx)"

    # Check Setúbal: 2xxx
    if distrito == "Setúbal" and first_one != "2":
        return True, f"Setúbal but postcode {cp} (prefix {prefix}, not 2xxx)"

    # Check Évora: 7xxx
    if distrito == "Évora" and first_one != "7":
        return True, f"Évora but postcode {cp} (prefix {prefix}, not 7xxx)"

    # Check Beja: 7xxx
    if distrito == "Beja" and first_one != "7":
        return True, f"Beja but postcode {cp} (prefix {prefix}, not 7xxx)"

    # Check Portalegre: 7xxx
    if distrito == "Portalegre" and first_one != "7":
        return True, f"Portalegre but postcode {cp} (prefix {prefix}, not 7xxx)"

    # Check Vila Real: 5xxx
    if distrito == "Vila Real" and first_one not in ("5", "6"):
        return True, f"Vila Real but postcode {cp} (prefix {prefix}, not 5xxx/6xxx)"

    # Check Bragança: 5xxx
    if distrito == "Bragança" and first_one not in ("5",):
        return True, f"Bragança but postcode {cp} (prefix {prefix}, not 5xxx)"

    # Check Açores: 9xxx
    if distrito == "Açores" and first_one != "9":
        return True, f"Açores but postcode {cp} (prefix {prefix}, not 9xxx)"

    # Check Madeira: 9xxx
    if distrito == "Madeira" and first_one != "9":
        return True, f"Madeira but postcode {cp} (prefix {prefix}, not 9xxx)"

    return False, None


def load_csv(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def internal_audit(rows):
    """Run internal consistency checks on all postcode/distrito pairs."""
    suspicious = []
    invalid_format = []
    district_counts = defaultdict(int)
    prefix_counts = defaultdict(int)

    for row in rows:
        cp = row.get("codigo_postal", "").strip()
        distrito = row.get("distrito", "").strip()

        if not cp:
            invalid_format.append({"id": row["id"], "nome": row["nome"], "reason": "Empty postcode"})
            continue

        if not re.match(r'^\d{4}-\d{3}$', cp):
            invalid_format.append({"id": row["id"], "nome": row["nome"], "cp": cp, "reason": "Bad format"})
            continue

        prefix = cp[:4]
        prefix_counts[prefix[0]] += 1
        district_counts[distrito] += 1

        is_bad, reason = postcode_check(cp, distrito)
        if is_bad:
            suspicious.append({
                "id": row["id"],
                "nome": row["nome"],
                "cp": cp,
                "distrito": distrito,
                "concelho": row.get("concelho", ""),
                "reason": reason,
            })

    return suspicious, invalid_format, district_counts, prefix_counts


def select_sample(rows, n=25):
    """
    Pick ~25 institutions spread across different districts.
    Prefer Creche tipo (have Carta Social IDs more reliably).
    Focus on districts with higher postcode-mismatch risk.
    """
    # Group by district
    by_district = defaultdict(list)
    for row in rows:
        if row.get("codigo_postal") and re.match(r'^\d{4}-\d{3}$', row["codigo_postal"]):
            by_district[row["distrito"]].append(row)

    districts = sorted(by_district.keys())
    sample = []

    # Prioritise districts: Lisboa, Faro, Porto, Braga, Setúbal, Aveiro, Coimbra, Évora, Beja,
    # Santarém, Leiria, Guarda, Castelo Branco, Viseu, Vila Real, Bragança, Viana do Castelo,
    # Portalegre, Açores, Madeira
    priority = [
        "Lisboa", "Faro", "Porto", "Braga", "Setúbal", "Aveiro",
        "Coimbra", "Évora", "Beja", "Santarém", "Leiria", "Guarda",
        "Castelo Branco", "Viseu", "Vila Real", "Bragança",
        "Viana do Castelo", "Portalegre", "Açores", "Madeira",
    ]

    random.seed(42)  # reproducible

    for dist in priority:
        if dist not in by_district:
            continue
        candidates = [r for r in by_district[dist] if r.get("id")]
        if candidates:
            pick = random.choice(candidates)
            sample.append(pick)
        if len(sample) >= n:
            break

    # If we still have room, add more from populous districts
    if len(sample) < n:
        remaining = [r for r in rows if r not in sample and r.get("id")]
        extra = random.sample(remaining, min(n - len(sample), len(remaining)))
        sample.extend(extra)

    return sample[:n]


def build_carta_social_url(institution_id):
    base = (
        "https://www.cartasocial.pt/en/search-results"
        "?p_p_id=SocialLetterPortlet_WAR_cartasocialportlet"
        "&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
        "&p_p_col_id=column-1&p_p_col_count=1"
        "&_SocialLetterPortlet_WAR_cartasocialportlet__facesViewIdRender="
        "%2Fviews%2FsocialLetter%2Flist%2Fview%2Fequipment%2Fequipment_detail.xhtml"
        f"&_SocialLetterPortlet_WAR_cartasocialportlet_idEquipment={institution_id}"
    )
    return base


def extract_postcode_from_html(html):
    """
    Extract postcode from Carta Social detail page HTML.
    The postcode appears in several possible locations.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: Look for Portuguese postcode pattern in text
    # Carta Social shows address in a specific div

    # Try finding postcode pattern directly in text
    text = soup.get_text(" ", strip=True)

    # Portuguese postcode: 4 digits, hyphen, 3 digits
    matches = re.findall(r'\b(\d{4}-\d{3})\b', text)

    if matches:
        # Return the first one that looks like a real postcode (not phone/reference)
        for m in matches:
            prefix = int(m[:4])
            if 1000 <= prefix <= 9999:
                return m

    return None


def extract_address_block(html):
    """Extract the full address block from the page for context."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Look for common address-containing elements
    address_text = ""

    # Try specific selectors that Carta Social might use
    for selector in [
        ".equipment-detail", ".equipamento-detail",
        ".detail-content", "[class*='address']", "[class*='morada']",
        "table", ".panel-body", ".content-detail"
    ]:
        el = soup.select_one(selector)
        if el:
            t = el.get_text(" ", strip=True)
            if re.search(r'\d{4}-\d{3}', t):
                address_text = t[:500]
                break

    if not address_text:
        # Fallback: full text truncated
        address_text = soup.get_text(" ", strip=True)[:800]

    return address_text


async def fetch_carta_social_pages(sample):
    """Fetch Carta Social detail pages for the sample using crawl4ai."""
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    from crawl4ai.async_configs import CacheMode

    results = []

    browser_config = BrowserConfig(
        headless=True,
        viewport_width=1280,
        viewport_height=900,
    )

    crawl_config = CrawlerRunConfig(
        page_timeout=45000,
        cache_mode=CacheMode.BYPASS,
        # Wait for the portlet content to render (JSF page)
        wait_for="css:.portlet-body,#column-1,.equipment-detail,table",
        js_code="""
            // Wait a moment for JSF lifecycle
            await new Promise(r => setTimeout(r, 2000));
        """,
        remove_overlay_elements=True,
    )

    print(f"\nFetching {len(sample)} Carta Social pages...")

    async with AsyncWebCrawler(config=browser_config) as crawler:
        for i, row in enumerate(sample):
            inst_id = row["id"]
            url = build_carta_social_url(inst_id)
            csv_cp = row["codigo_postal"].strip()

            print(f"  [{i+1}/{len(sample)}] ID {inst_id}: {row['nome'][:50]} — CSV postcode: {csv_cp}")

            try:
                result = await crawler.arun(url=url, config=crawl_config)

                if result.success:
                    cs_cp = extract_postcode_from_html(result.html)
                    address_text = extract_address_block(result.html)

                    match = None
                    if cs_cp:
                        match = (cs_cp == csv_cp)

                    results.append({
                        "id": inst_id,
                        "nome": row["nome"],
                        "distrito": row["distrito"],
                        "concelho": row["concelho"],
                        "csv_postcode": csv_cp,
                        "cs_postcode": cs_cp if cs_cp else "NOT FOUND",
                        "match": match,
                        "url": url,
                        "address_snippet": address_text[:300] if address_text else "",
                        "fetch_ok": True,
                    })

                    status = "MATCH" if match else ("MISMATCH" if match is False else "NOT FOUND")
                    print(f"    → Carta Social: {cs_cp if cs_cp else 'not found'} [{status}]")
                else:
                    print(f"    → FETCH FAILED: {result.error_message}")
                    results.append({
                        "id": inst_id,
                        "nome": row["nome"],
                        "distrito": row["distrito"],
                        "concelho": row["concelho"],
                        "csv_postcode": csv_cp,
                        "cs_postcode": "FETCH ERROR",
                        "match": None,
                        "url": url,
                        "address_snippet": str(result.error_message or "")[:200],
                        "fetch_ok": False,
                    })
            except Exception as e:
                print(f"    → EXCEPTION: {e}")
                results.append({
                    "id": inst_id,
                    "nome": row["nome"],
                    "distrito": row["distrito"],
                    "concelho": row["concelho"],
                    "csv_postcode": csv_cp,
                    "cs_postcode": "EXCEPTION",
                    "match": None,
                    "url": url,
                    "address_snippet": str(e)[:200],
                    "fetch_ok": False,
                })

            # Polite delay between requests
            if i < len(sample) - 1:
                await asyncio.sleep(1.5)

    return results


def write_report(output_path, suspicious, invalid_format, district_counts, prefix_counts, sample_results, total_rows):
    lines = []
    lines.append("=" * 70)
    lines.append("POSTCODE AUDIT REPORT — creches_portugal.csv")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Total rows audited: {total_rows}")
    lines.append("=" * 70)

    # ── Section 1: Internal consistency audit ─────────────────────────────────
    lines.append("\n\n── SECTION 1: INTERNAL CONSISTENCY AUDIT ──────────────────────────────")
    lines.append(f"\nRows by distrito:")
    for dist, count in sorted(district_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {dist:30s} {count:5d}")

    lines.append(f"\nRows by postcode first digit:")
    for digit in sorted(prefix_counts.keys()):
        lines.append(f"  {digit}xxx  →  {prefix_counts[digit]:5d} rows")

    lines.append(f"\nInvalid postcode format: {len(invalid_format)} rows")
    if invalid_format:
        for row in invalid_format[:20]:
            lines.append(f"  ID {row['id']:>6}: {row.get('cp','(empty)'):15s} — {row['reason']}")
        if len(invalid_format) > 20:
            lines.append(f"  ... and {len(invalid_format)-20} more")

    lines.append(f"\nSuspicious postcode/distrito combos: {len(suspicious)} rows")
    if suspicious:
        # Group by reason category
        by_district = defaultdict(list)
        for s in suspicious:
            by_district[s["distrito"]].append(s)

        for dist, items in sorted(by_district.items(), key=lambda x: -len(x[1])):
            lines.append(f"\n  {dist} ({len(items)} issues):")
            for item in items[:10]:
                lines.append(f"    ID {item['id']:>6}: {item['cp']:12s} | {item['concelho']:25s} | {item['reason']}")
            if len(items) > 10:
                lines.append(f"    ... and {len(items)-10} more in {dist}")
    else:
        lines.append("  None found.")

    # ── Section 2: Carta Social comparison ────────────────────────────────────
    lines.append("\n\n── SECTION 2: CARTA SOCIAL LIVE COMPARISON ────────────────────────────")

    fetched = [r for r in sample_results if r["fetch_ok"]]
    failed = [r for r in sample_results if not r["fetch_ok"]]
    matched = [r for r in fetched if r["match"] is True]
    mismatched = [r for r in fetched if r["match"] is False]
    not_found = [r for r in fetched if r["match"] is None]

    lines.append(f"\nSample size: {len(sample_results)}")
    lines.append(f"  Successfully fetched: {len(fetched)}")
    lines.append(f"  Fetch errors:         {len(failed)}")
    lines.append(f"\nPostcode comparison (of {len(fetched)} fetched pages):")
    lines.append(f"  Match:      {len(matched):3d}  ({100*len(matched)/max(len(fetched),1):.0f}%)")
    lines.append(f"  Mismatch:   {len(mismatched):3d}  ({100*len(mismatched)/max(len(fetched),1):.0f}%)")
    lines.append(f"  Not found:  {len(not_found):3d}  ({100*len(not_found)/max(len(fetched),1):.0f}%)")

    if mismatched:
        lines.append(f"\nMISMATCHES — {len(mismatched)} found:")
        for r in mismatched:
            lines.append(f"\n  ID {r['id']:>6}: {r['nome'][:55]}")
            lines.append(f"    District:  {r['distrito']}, {r['concelho']}")
            lines.append(f"    CSV:       {r['csv_postcode']}")
            lines.append(f"    CartaSoc:  {r['cs_postcode']}")
            lines.append(f"    URL:       {r['url']}")
            if r["address_snippet"]:
                snippet = r["address_snippet"][:200].replace("\n", " ")
                lines.append(f"    Context:   {snippet}")
    else:
        lines.append("\nNo mismatches found in sample.")

    if not_found:
        lines.append(f"\nNOT FOUND on page (postcode not extracted) — {len(not_found)}:")
        for r in not_found:
            lines.append(f"  ID {r['id']:>6}: {r['nome'][:55]}")
            lines.append(f"    CSV postcode: {r['csv_postcode']} | {r['distrito']}")
            lines.append(f"    URL: {r['url']}")

    lines.append(f"\nFULL SAMPLE RESULTS:")
    lines.append(f"  {'ID':>6}  {'CSV CP':12}  {'CS CP':12}  {'Match':7}  {'District':20}  Name")
    lines.append("  " + "-"*90)
    for r in sample_results:
        match_str = "MATCH" if r["match"] is True else ("MISMATCH" if r["match"] is False else ("NO-CP" if r["fetch_ok"] else "ERR"))
        lines.append(f"  {r['id']:>6}  {r['csv_postcode']:12}  {r['cs_postcode']:12}  {match_str:7}  {r['distrito']:20}  {r['nome'][:40]}")

    if failed:
        lines.append(f"\nFETCH ERRORS — {len(failed)}:")
        for r in failed:
            lines.append(f"  ID {r['id']:>6}: {r['nome'][:55]} — {r['address_snippet'][:100]}")

    lines.append("\n" + "=" * 70)
    lines.append("END OF REPORT")
    lines.append("=" * 70)

    report = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    return report


async def main():
    csv_path = "/Users/D/Documents/GitHub/childcare-directory/creches_portugal.csv"
    output_path = "/Users/D/Documents/GitHub/childcare-directory/postcode_audit_results.txt"

    print("Loading CSV...")
    rows = load_csv(csv_path)
    print(f"Loaded {len(rows)} rows")

    # ── Part 1: Internal audit ─────────────────────────────────────────────────
    print("\nRunning internal consistency audit...")
    suspicious, invalid_format, district_counts, prefix_counts = internal_audit(rows)
    print(f"  Invalid format: {len(invalid_format)}")
    print(f"  Suspicious combos: {len(suspicious)}")

    # ── Part 2: Select sample ──────────────────────────────────────────────────
    print("\nSelecting sample of 25 institutions...")
    sample = select_sample(rows, n=25)
    print(f"  Selected {len(sample)} from districts: {', '.join(sorted(set(r['distrito'] for r in sample)))}")

    # ── Part 3: Fetch Carta Social pages ───────────────────────────────────────
    sample_results = await fetch_carta_social_pages(sample)

    # ── Part 4: Write report ───────────────────────────────────────────────────
    print(f"\nWriting report to {output_path}...")
    report = write_report(output_path, suspicious, invalid_format, district_counts, prefix_counts, sample_results, len(rows))

    # Print summary to stdout
    matched = sum(1 for r in sample_results if r["match"] is True)
    mismatched = sum(1 for r in sample_results if r["match"] is False)
    fetched = sum(1 for r in sample_results if r["fetch_ok"])
    print(f"\nDone. Results: {matched}/{fetched} match, {mismatched} mismatch, {len(suspicious)} internal anomalies")
    print(f"Report saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
