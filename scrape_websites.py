#!/usr/bin/env python3
"""
Scrape missing websites for creches using Gemini 2.5 Flash + Google Search grounding.
Writes results incrementally — safe to pause and resume.

Usage:
    python3 scrape_websites.py [--batch N] [--delay S]
"""

import csv
import json
import re
import ssl
import time
import urllib.request
import urllib.error
import argparse
import os

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

API_KEY = os.environ.get("GEMINI_API_KEY", "")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"

INPUT_CSV = "creches_portugal.csv"
OUTPUT_CSV = "website_results.csv"
OUTPUT_FIELDNAMES = ["id", "nome", "localidade", "concelho", "tipo", "website_found", "needs_review", "review_reason", "raw_response"]


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


def extract_url(text):
    urls = re.findall(r'https?://[^\s\)\]\'"]+|[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s\)\]\'"]*)?', text, re.I)
    for u in urls:
        if "." in u and not any(skip in u.lower() for skip in ["google.com", "facebook.com", "not found", "cartasocial"]):
            return u.rstrip(".,")
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


def needs_review(nome, website, tipo):
    """Flag URLs that likely point to a parent org rather than the institution itself."""
    reasons = []
    if website:
        # Extract domain keywords (strip www., tld, subpaths)
        domain = re.sub(r'^https?://(www\.)?', '', website).split('/')[0]
        domain_core = re.sub(r'\.[a-z]{2,3}$', '', domain).lower()
        # Normalise name to comparable slug
        name_words = set(re.sub(r'[^\w\s]', '', nome.lower()).split()) - {
            'de', 'da', 'do', 'das', 'dos', 'e', 'a', 'o', 'creche', 'jardim',
            'infancia', 'infantario', 'centro', 'social', 'paroquial', 'casa',
        }
        if name_words and not any(w in domain_core for w in name_words):
            reasons.append("domain doesn't match institution name")
    if tipo == "Creche e Jardim de Infância":
        reasons.append("combined tipo — may have split pages")
    return bool(reasons), "; ".join(reasons)


def query_gemini(nome, localidade, concelho):
    prompt = (
        f'Find the official website for this Portuguese childcare institution: '
        f'"{nome}" in {localidade or concelho}, Portugal. '
        f'Return only the URL or "not found".'
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "thinkingConfig": {"thinkingBudget": 0}
        },
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    text = data["candidates"][0]["content"]["parts"][0].get("text", "")
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=10, help="Number of institutions to process")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    args = parser.parse_args()

    if not API_KEY:
        print("Set GEMINI_API_KEY env var")
        return

    done = load_done_ids()
    missing = load_missing()
    pending = [r for r in missing if r["id"] not in done]

    print(f"Total missing websites: {len(missing)}")
    print(f"Already processed: {len(done)}")
    print(f"Pending: {len(pending)}")
    print(f"Running batch of: {args.batch}")
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

        print(f"[{i}/{len(batch)}] {nome} ({localidade or concelho})", end=" ... ", flush=True)

        flag, reason = False, ""
        try:
            raw = query_gemini(nome, localidade, concelho)
            website = extract_url(raw)
            if website:
                website = validate_url(website)
            status = website if website else "not found"
            if website:
                found_count += 1
                flag, reason = needs_review(nome, website, tipo)
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            status = f"error:{e.code}"
            raw = body
            print(f"HTTP {e.code} — {body[:80]}")
        except Exception as e:
            status = f"error:{e}"
            raw = str(e)
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
            "raw_response": raw,
        })
        out.flush()

        if i < len(batch):
            time.sleep(args.delay)

    out.close()
    print(f"\nDone. Found {found_count}/{len(batch)} websites. Results in {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
