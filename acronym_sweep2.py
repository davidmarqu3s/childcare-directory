#!/usr/bin/env python3
"""
acronym_sweep2.py
-----------------
Find words in `nome` and `entidade_proprietaria` that are likely acronyms:
- consonant-heavy (vowel ratio < 0.3)
- 2–7 characters long
- NOT already ALL CAPS
- NOT in the exclusion lists

Outputs acronym_sweep_results.txt.  Does NOT modify the CSV.
"""

import csv
import re
import unicodedata
from collections import defaultdict

CSV_PATH = "/Users/D/Documents/GitHub/childcare-directory/creches_portugal.csv"
OUT_PATH = "/Users/D/Documents/GitHub/childcare-directory/acronym_sweep_results.txt"

# ---------------------------------------------------------------------------
# Exclusion lists
# ---------------------------------------------------------------------------

# Common Portuguese function words, prepositions, articles
PORTUGUESE_STOPWORDS = {
    "de", "da", "do", "das", "dos", "e", "em", "a", "o", "as", "os",
    "no", "na", "nos", "nas", "por", "para", "com", "sem", "ao", "aos",
    "à", "às", "um", "uma", "uns", "umas", "ou", "que", "se", "em",
    "até", "sob", "sobre", "ante", "entre", "após", "desde", "durante",
    "mediante", "perante", "consoante", "conforme", "segundo",
    # common words in org names
    "centro", "social", "casa", "lar", "jardim", "creche", "infantil",
    "escola", "colégio", "instituto", "fundação", "associação", "santa",
    "são", "santo", "nossa", "senhora", "paroquial", "obra", "obras",
    "irmandade", "misericórdia", "cooperativa", "patronato", "complexo",
    "comissão", "comunitário", "promoção", "apoio", "acolhimento",
    "familiar", "cultural", "recreativo", "habitação",
    # titles
    "prof", "dr", "dra", "eng", "arq", "pe", "padre", "madre",
    # English words
    "kids", "baby", "park", "club", "star", "fun", "play", "school",
    "happy", "world", "new", "my", "the", "little", "mini", "tiny",
    "smart", "bright", "best", "top", "first", "home", "house",
    # known false positives (real words / proper names)
    "cruz", "flor", "mar", "sol", "bem", "bom", "crescer", "brincar",
    "martins", "santos", "silva", "costa", "ferreira", "rodrigues",
    "pinto", "carvalho", "sousa", "pereira", "lopes", "gomes",
    "jesus", "maria", "josé", "pedro", "paulo", "joão", "rua", "largo",
    "avenida", "praceta", "quinta", "urbanização",
    # abbreviations / suffixes (not acronyms)
    "ldª", "lda", "crl", "sa", "s", "n", "ip", "iss",
}

# Patterns to skip entirely (abbreviations, initials, legal suffixes)
SKIP_PATTERNS = re.compile(
    r"""
    ^[A-Z]\.$           |   # single initial: S. N. etc.
    ^\d                 |   # starts with digit
    ^[^\w]              |   # starts with non-word char
    Ldª$                |   # legal suffix
    ^n\.º$              |   # N.º
    [.,]$                   # ends with punctuation
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Normalise accents for vowel-counting (treat accented vowels as vowels)
def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )

def vowel_ratio(word: str) -> float:
    w = strip_accents(word.lower())
    letters = [c for c in w if c.isalpha()]
    if not letters:
        return 1.0
    vowels = sum(1 for c in letters if c in "aeiouáéíóúàèìòùâêîôûãõ")
    return vowels / len(letters)

def is_likely_acronym(word: str) -> bool:
    """Return True if the word looks like a mis-cased acronym."""
    # Must be alphabetic (allow apostrophe for Sant'ana style — but those
    # won't pass other checks anyway)
    if not re.fullmatch(r"[A-Za-zÀ-ÿ']+", word):
        return False

    length = len(word)
    if length < 2 or length > 7:
        return False

    # Already ALL CAPS → already correct (or intentional)
    if word == word.upper():
        return False

    # Normalised lowercase for exclusion check
    lower = word.lower()
    if lower in PORTUGUESE_STOPWORDS:
        return False

    if SKIP_PATTERNS.search(word):
        return False

    # Must be consonant-heavy
    if vowel_ratio(word) >= 0.3:
        return False

    return True

# ---------------------------------------------------------------------------
# Tokenise a field value into words
# ---------------------------------------------------------------------------

def tokenise(text: str):
    """Split on whitespace / punctuation, keeping apostrophe-internal words."""
    return re.split(r"[\s,;:()\[\]/\\–—\-]+", text)

# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

fields = ["nome", "entidade_proprietaria"]

# data[field][word] = {"count": int, "examples": set()}
data = {f: defaultdict(lambda: {"count": 0, "examples": []}) for f in fields}

with open(CSV_PATH, newline="", encoding="utf-8") as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        for field in fields:
            value = row.get(field, "").strip()
            if not value:
                continue
            for token in tokenise(value):
                token = token.strip("'\"")
                if is_likely_acronym(token):
                    entry = data[field][token]
                    entry["count"] += 1
                    if len(entry["examples"]) < 4:
                        entry["examples"].append(value)

# ---------------------------------------------------------------------------
# Write report
# ---------------------------------------------------------------------------

lines = []
lines.append("ACRONYM CAPITALISATION SWEEP — RESULTS")
lines.append("=" * 70)
lines.append("Strategy: words 2-7 chars, vowel ratio < 0.3, not ALL-CAPS,")
lines.append("          not in stopwords / exclusion list.")
lines.append("Fields checked: nome, entidade_proprietaria")
lines.append("")

for field in fields:
    candidates = data[field]
    # Sort by count descending, then alphabetically
    sorted_candidates = sorted(
        candidates.items(), key=lambda kv: (-kv[1]["count"], kv[0].lower())
    )

    lines.append(f"{'─' * 70}")
    lines.append(f"FIELD: {field.upper()}  ({len(sorted_candidates)} candidates)")
    lines.append(f"{'─' * 70}")

    if not sorted_candidates:
        lines.append("  (none found)")
        lines.append("")
        continue

    for word, info in sorted_candidates:
        vr = vowel_ratio(word)
        lines.append(f"  {word!r:<20}  count={info['count']:<5}  vowel_ratio={vr:.2f}")
        for ex in info["examples"]:
            lines.append(f"      → {ex}")
        lines.append("")

    lines.append("")

report = "\n".join(lines)

with open(OUT_PATH, "w", encoding="utf-8") as fh:
    fh.write(report)

print(report)
print(f"\n[Saved to {OUT_PATH}]")
