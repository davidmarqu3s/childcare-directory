#!/usr/bin/env python3
"""
Find missing websites using Serper.dev Google Search API.
Writes results incrementally — safe to pause and resume.

Usage:
    python3 scrape_serper.py [--batch N] [--delay S]

Requires BW_SESSION env var (run: export BW_SESSION=$(bw unlock --raw))
"""

import csv
import json
import os
import re
import ssl
import subprocess
import time
import unicodedata
import urllib.request
import urllib.error
import argparse
from urllib.parse import urlparse

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

SERPER_URL = "https://google.serper.dev/search"

INPUT_CSV = "creches_portugal.csv"
OUTPUT_CSV = "serper_results.csv"
OUTPUT_FIELDNAMES = ["id", "nome", "localidade", "concelho", "tipo", "website_found", "needs_review", "review_reason", "search_query"]

# Domains to always skip — aggregators, social media, directories
SKIP_DOMAINS = [
    "google.com", "google.pt",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "youtube.com",
    "pai.pt", "118.pt", "einformar.pt", "infopages.pt", "guiame.pt",
    "cartasocial.mtsss.gov.pt", "seg-social.pt", "mtsss.gov.pt",
    "yelp.com", "foursquare.com",
    "wikipedia.org", "wikimedia.org",
    "tripadvisor.com", "tripadvisor.pt",
    "sapo.pt", "dn.pt", "publico.pt", "jn.pt", "observador.pt",
    # Business registries and directories that describe institutions but aren't them
    "racius.com", "einforma.pt", "portugalio.com",
    "wanderlog.com", "citysearch.com",
    "coverflex.com",
    "mapasocial.pt", "socialgest.pt",
    "pordata.pt",
    "dgeste.mec.pt", "dge.mec.pt",
    "acss.min-saude.pt",
    # Childcare/school directories
    "infantariospt.com", "crechenaminharua.pt", "creches.com.pt", "skoolist.pt",
    # Generic business/trade data
    "tendata.com", "kompass.com", "europages.pt", "dnb.com",
    # Wiki/encyclopedia/maps
    "grokipedia.com", "wikiwand.com", "wikimapia.org", "waze.com",
    # School/education directories
    "escoladevidro.pt", "directorioescolas.eu", "ecoescolas.abaae.pt",
    "servicospublicos.pt", "municipiosefreguesias.pt",
    # News sites
    "correiodominho.pt", "noticiasdecoimbra.pt", "ovarnews.pt",
    "jornaldenegocios.pt", "empresite.jornaldenegocios.pt",
    # Other directories/aggregators
    "apoioperto.com", "laresonline.pt", "developmentaid.org",
    "infoisinfo.com.pt", "portaldaqueixa.com", "primeiraimagem.com",
    "moovitapp.com", "associativismo.guimaraes.pt",
]

# Words stripped before checking name↔domain/title match
STOP_WORDS = {
    # Portuguese function words
    "de", "da", "do", "das", "dos", "e", "a", "o", "os", "as", "em", "no", "na",
    "um", "uma",
    # Generic childcare terms
    "creche", "jardim", "infancia", "infantario", "infantil", "crianca", "centro",
    "pre", "escolar", "escola", "colegio",
    # Common org descriptors
    "social", "paroquial", "casa", "lar", "obra", "associacao", "fundacao",
    "instituto", "cooperativa", "misericordia", "ipss",
    # Religious/honorary
    "santa", "santo", "sao", "nossa", "senhora", "sagrado", "coracao",
    "jesus", "maria", "jose", "paulo", "pedro", "joao", "francisco",
    # Generic place/size words
    "portugal", "nacional", "municipal", "grande", "novo", "nova",
    "primeiro", "segunda",
}


def get_api_key():
    key = os.environ.get("SERPER_API_KEY", "")
    if key:
        return key
    session = os.environ.get("BW_SESSION", "")
    if not session:
        return ""
    try:
        result = subprocess.run(
            ["/usr/local/bin/bw", "list", "items", "--session", session],
            capture_output=True, text=True, timeout=10,
        )
        items = json.loads(result.stdout)
        for item in items:
            if item.get("name", "").lower() == "serper.dev":
                for field in item.get("fields", []):
                    if field.get("name", "").lower() == "api key":
                        return field.get("value", "")
        return ""
    except Exception:
        return ""


def normalize(text):
    nfkd = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", ascii_text)


def distinctive_words(nome):
    words = set(normalize(nome).split()) - STOP_WORDS
    return {w for w in words if len(w) > 2}


def domain_core(url):
    try:
        host = urlparse(url).netloc.lower().replace("www.", "")
        return normalize(re.sub(r"\.[a-z]{2,3}$", "", host))
    except Exception:
        return ""


def should_skip(url):
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace("www.", "")
    except Exception:
        return True
    if any(skip in host for skip in SKIP_DOMAINS):
        return True
    # Municipality/parish domains at any subdomain level (e.g. sub.cm-mealhada.pt)
    if re.search(r"(^|\.)cm-|\.jf-|municipio\.", host):
        return True
    return False


def is_confident_match(nome, url):
    """Only accept if a distinctive name word appears in the URL (domain + path).

    Title matching is intentionally excluded: directories have pages *about*
    institutions so their titles match perfectly — that's a false positive, not
    a hit. We require the word to be in the URL itself.
    """
    words = distinctive_words(nome)
    if not words:
        return False

    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.lower()
        url_slug = normalize(host + " " + path)
    except Exception:
        return False

    return any(w in url_slug for w in words)


def best_url_from_results(organic, nome):
    for result in organic[:5]:
        url = result.get("link", "")
        if url and not should_skip(url) and is_confident_match(nome, url):
            return url
    return ""


def validate_url(url):
    if not url.startswith("http"):
        url = "https://" + url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
            return url if r.status < 400 else ""
    except urllib.error.HTTPError as e:
        return url if e.code < 400 else ""
    except Exception:
        return ""


def check_needs_review(nome, website, tipo):
    reasons = []
    words = distinctive_words(nome)
    dc = domain_core(website)
    if words and not any(w in dc for w in words):
        reasons.append("word matched in path not domain — verify")
    if tipo == "Creche e Jardim de Infância":
        reasons.append("combined tipo — may have split pages")
    return bool(reasons), "; ".join(reasons)


def load_done_ids():
    done = {}
    if not os.path.exists(OUTPUT_CSV):
        return done
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done[row["id"]] = row["website_found"]
    return done


def load_missing():
    rows = []
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("website_google", "").strip():
                rows.append(row)
    return rows


def build_query(nome, localidade, concelho):
    location = localidade or concelho or "Portugal"
    return f'"{nome}" {location} Portugal'


def search_serper(query, api_key):
    payload = json.dumps({"q": query, "gl": "pt", "hl": "pt", "num": 5}).encode()
    req = urllib.request.Request(
        SERPER_URL,
        data=payload,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=100, help="Number of institutions to process")
    parser.add_argument("--delay", type=float, default=0.3, help="Seconds between requests")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("No API key found. Set BW_SESSION (export BW_SESSION=$(bw unlock --raw)) or SERPER_API_KEY.")
        return

    done = load_done_ids()
    missing = load_missing()
    pending = [r for r in missing if r["id"] not in done]

    print(f"Total missing websites: {len(missing)}")
    print(f"Already processed:      {len(done)}")
    print(f"Pending:                {len(pending)}")
    print(f"Running batch of:       {args.batch}")
    print()

    write_header = not os.path.exists(OUTPUT_CSV)
    out = open(OUTPUT_CSV, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(out, fieldnames=OUTPUT_FIELDNAMES)
    if write_header:
        writer.writeheader()

    batch = pending[: args.batch]
    found_count = 0

    for i, row in enumerate(batch, 1):
        nome = row["nome"]
        localidade = row["localidade"]
        concelho = row["concelho"]
        tipo = row["tipo"]
        rid = row["id"]
        query = build_query(nome, localidade, concelho)

        print(f"[{i}/{len(batch)}] {nome} ({localidade or concelho})", end=" ... ", flush=True)

        website = ""
        flag, reason = False, ""
        try:
            data = search_serper(query, api_key)
            organic = data.get("organic", [])
            candidate = best_url_from_results(organic, nome)
            if candidate:
                website = validate_url(candidate)
            status = website if website else "not found"
            if website:
                found_count += 1
                flag, reason = check_needs_review(nome, website, tipo)
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            status = f"error:{e.code}"
            print(f"HTTP {e.code} — {body[:80]}")
        except Exception as e:
            status = f"error:{e}"
            print(f"ERROR: {e}")
        else:
            suffix = " ⚠ review" if flag else ""
            print(status + suffix)

        writer.writerow({
            "id": rid,
            "nome": nome,
            "localidade": localidade,
            "concelho": concelho,
            "tipo": tipo,
            "website_found": status,
            "needs_review": "yes" if flag else "",
            "review_reason": reason,
            "search_query": query,
        })
        out.flush()

        if i < len(batch):
            time.sleep(args.delay)

    out.close()
    print(f"\nDone. Found {found_count}/{len(batch)} websites. Results in {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
