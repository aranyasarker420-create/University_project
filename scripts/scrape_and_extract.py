"""
scrape_and_extract.py
---------------------
Full automated pipeline:
  URL → fetch page → clean text → Qwen (Ollama) → JSON → validate → SQLite

Single URL:
    python scripts/scrape_and_extract.py --url https://www.helsinki.fi/en/admissions/masters

Batch from file (one URL per line):
    python scripts/scrape_and_extract.py --batch data/urls.txt

Save without inserting (review first):
    python scripts/scrape_and_extract.py --url https://... --save data/extracted.json --no-insert

Dry run (scrape + extract, no DB write):
    python scripts/scrape_and_extract.py --url https://... --dry-run
"""

import json
import argparse
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Run:  pip install requests beautifulsoup4")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from validate_record import validate_university_record
from insert_record   import insert_record


# ──────────────────────────────────────────────────────────────────────────────
# Ollama config  (must match what you have in qwen_extract.py)
# ──────────────────────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"   # run `ollama list` to confirm your model name

DB_PATH = BASE_DIR / "data" / "universities.db"

# Seconds to wait between batch requests — be polite to university servers
BATCH_DELAY = 3


# ──────────────────────────────────────────────────────────────────────────────
# Schema (same as qwen_extract.py — kept here so this script is self-contained)
# ──────────────────────────────────────────────────────────────────────────────

SCHEMA_TEMPLATE = {
    "name": None, "country": None, "city": None, "degree": None,
    "program": None, "program_category": None, "language": None,
    "duration_years": None, "tuition_usd": None, "cgpa_requirement": None,
    "cgpa_scale": 4.0, "ielts_requirement": None, "toefl_requirement": None,
    "gre_requirement": None, "gre_quant_min": None,
    "research_required": False, "research_preferred": False,
    "research_experience_required": False, "minimum_research_years": 0,
    "published_paper_required": False, "published_paper_preferred": False,
    "minimum_published_papers": 0, "journal_paper_preferred": False,
    "conference_paper_preferred": False, "first_author_preferred": False,
    "indexed_publication_preferred": False, "research_proposal_required": False,
    "supervisor_contact_required": False, "work_experience_years": 0,
    "scholarship_available": False, "scholarship_details": None,
    "application_deadline": None, "intake_months": [], "acceptance_rate": None,
    "qs_ranking": None, "work_permit_friendly": None, "pr_friendliness_score": None,
    "part_time_work_allowed": None, "living_cost_monthly_usd": None,
    "application_fee_usd": None, "official_website": None, "program_url": None,
    "scholarship_url": None, "source_url": None, "last_verified": None,
    "data_confidence_score": None, "notes": None,
}

SYSTEM_PROMPT = (
    "You extract university admission information into strict JSON. "
    "Return only the JSON object — no explanation, no markdown fences, no extra text."
)

# Domain → country mapping so Qwen can infer country from the URL
DOMAIN_COUNTRY_MAP = {
    ".fi":  "Finland",
    ".de":  "Germany",
    ".se":  "Sweden",
    ".no":  "Norway",
    ".dk":  "Denmark",
    ".nl":  "Netherlands",
    ".ie":  "Ireland",
    ".ca":  "Canada",
    ".au":  "Australia",
    ".nz":  "New Zealand",
    ".uk":  "United Kingdom",
    ".ac.uk": "United Kingdom",
    ".fr":  "France",
    ".it":  "Italy",
    ".es":  "Spain",
    ".at":  "Austria",
    ".ch":  "Switzerland",
    ".be":  "Belgium",
    ".jp":  "Japan",
    ".kr":  "South Korea",
    ".sg":  "Singapore",
    ".edu": "United States",
}

# Well-known university → country so Qwen doesn't have to guess
KNOWN_UNIVERSITIES = {
    "aalto":      ("Finland",     "Espoo"),
    "helsinki":   ("Finland",     "Helsinki"),
    "tampere":    ("Finland",     "Tampere"),
    "tuni":       ("Finland",     "Tampere"),
    "oulu":       ("Finland",     "Oulu"),
    "tum":        ("Germany",     "Munich"),
    "rwth":       ("Germany",     "Aachen"),
    "kit":        ("Germany",     "Karlsruhe"),
    "kth":        ("Sweden",      "Stockholm"),
    "chalmers":   ("Sweden",      "Gothenburg"),
    "lund":       ("Sweden",      "Lund"),
    "ntnu":       ("Norway",      "Trondheim"),
    "tudelft":    ("Netherlands", "Delft"),
    "tue":        ("Netherlands", "Eindhoven"),
    "ucd":        ("Ireland",     "Dublin"),
    "tcd":        ("Ireland",     "Dublin"),
    "utoronto":   ("Canada",      "Toronto"),
    "ubc":        ("Canada",      "Vancouver"),
    "mcgill":     ("Canada",      "Montreal"),
    "uwaterloo":  ("Canada",      "Waterloo"),
    "melbourne":  ("Australia",   "Melbourne"),
    "anu":        ("Australia",   "Canberra"),
}


def _infer_country_city_from_url(url: str) -> tuple[str | None, str | None]:
    """
    Returns (country, city) guessed from the URL domain and known university names.
    Both may be None if nothing matches.
    """
    url_lower = url.lower()

    # Check known university keywords first
    for keyword, (country, city) in KNOWN_UNIVERSITIES.items():
        if keyword in url_lower:
            return country, city

    # Fall back to TLD
    for tld, country in DOMAIN_COUNTRY_MAP.items():
        if tld in url_lower:
            return country, None

    return None, None


EXTRACTION_PROMPT = """Extract university admission data from the text below.

Schema to follow exactly:
{schema}

Rules:
- Use null for any field not mentioned in the text.
- EXCEPTION for country and city: if they are not explicitly stated in the text,
  infer them from the university name or the source URL domain. For example,
  aalto.fi → Finland / Espoo, tum.de → Germany / Munich. Do not leave country
  as null if it can be reasonably inferred.
- Boolean fields must be true or false (lowercase).
- Dates must be YYYY-MM-DD format.
- tuition_usd must be a yearly USD number. Convert from other currencies using
  approximate current rates only if the currency is clearly stated; otherwise null.
  Use these approximate rates: 1 EUR = 1.08 USD, 1 GBP = 1.27 USD, 1 CAD = 0.74 USD,
  1 AUD = 0.65 USD, 1 SEK = 0.096 USD, 1 NOK = 0.094 USD.
- degree must be one of: Bachelors, Masters, PhD, Diploma, Certificate.
- intake_months must be a JSON array, e.g. ["September"] or ["January","September"].
- data_confidence_score: 0.0–1.0, your confidence in the extracted data.
- source_url: {source_url}
- Hint — country hint from URL: {country_hint}
- Hint — city hint from URL: {city_hint}

Text:
{text}

Return only the JSON object. No other text."""


# ──────────────────────────────────────────────────────────────────────────────
# Step 1 — Scrape
# ──────────────────────────────────────────────────────────────────────────────

# Tags that never contain useful admission text
_SKIP_TAGS = {
    "script", "style", "noscript", "nav", "footer", "header",
    "aside", "advertisement", "cookie", "banner",
}

# Noise phrases common on university pages
_NOISE_PATTERNS = [
    r"accept\s+cookies?", r"privacy\s+policy", r"cookie\s+settings",
    r"javascript\s+is\s+(required|disabled)", r"©\s*\d{4}",
    r"all\s+rights\s+reserved", r"follow\s+us\s+on", r"subscribe\s+to",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)


def scrape_url(url: str) -> str:
    """
    Fetches a URL and returns clean plain text suitable for Qwen extraction.
    Raises requests.RequestException on network errors.
    Raises ValueError if the page returns no usable content.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove noisy tags
    for tag in soup(list(_SKIP_TAGS)):
        tag.decompose()

    # Try to find the main content block first
    main = (
        soup.find("main") or
        soup.find("article") or
        soup.find(id=re.compile(r"(main|content|program|admission)", re.I)) or
        soup.find(class_=re.compile(r"(main|content|program|admission)", re.I)) or
        soup.body
    )

    raw = (main or soup).get_text(separator="\n")

    # Clean up whitespace
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if len(line) < 3:
            continue
        if _NOISE_RE.search(line):
            continue
        lines.append(line)

    text = "\n".join(lines)

    # Truncate to ~6000 chars — Qwen context limit safety
    if len(text) > 6000:
        text = text[:6000] + "\n[truncated]"

    if len(text) < 100:
        raise ValueError(f"Page returned too little usable text ({len(text)} chars). "
                         "It may require JavaScript or block scraping.")

    return text


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 — Extract via Ollama
# ──────────────────────────────────────────────────────────────────────────────

def _call_ollama(prompt: str) -> str:
    payload = json.dumps({
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.05, "num_predict": 2000},
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())["response"]
    except urllib.error.URLError as exc:
        raise ConnectionError(
            f"Cannot reach Ollama at {OLLAMA_URL}\n"
            f"Run:  ollama serve\nError: {exc}"
        ) from exc


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
    raw = re.sub(r"```\s*$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        raw = raw[start:end + 1]
    return json.loads(raw)


def extract_from_text(text: str, source_url: str) -> dict:
    country_hint, city_hint = _infer_country_city_from_url(source_url)

    prompt = f"{SYSTEM_PROMPT}\n\n" + EXTRACTION_PROMPT.format(
        schema=json.dumps(SCHEMA_TEMPLATE, indent=2),
        source_url=source_url,
        country_hint=country_hint or "unknown — infer from university name or text",
        city_hint=city_hint or "unknown — infer from university name or text",
        text=text,
    )
    raw = _call_ollama(prompt)
    extracted = _parse_json(raw)
    merged = {**SCHEMA_TEMPLATE, **extracted}
    merged["source_url"] = source_url

    # Hard-fill country/city if Qwen still left them null
    if not merged.get("country") and country_hint:
        merged["country"] = country_hint
    if not merged.get("city") and city_hint:
        merged["city"] = city_hint

    return merged


# ──────────────────────────────────────────────────────────────────────────────
# Step 3 — Full pipeline for one URL
# ──────────────────────────────────────────────────────────────────────────────

def process_url(url: str, save_path: Path | None = None,
                dry_run: bool = False, auto_insert: bool = True) -> dict | None:
    """
    Runs the full pipeline for a single URL.
    Returns the extracted record dict, or None on failure.
    """
    print(f"\n{'─'*60}")
    print(f"URL:  {url}")

    # 1. Scrape
    print("  [1/3] Scraping page ...", end=" ", flush=True)
    try:
        text = scrape_url(url)
        print(f"OK ({len(text)} chars)")
    except Exception as exc:
        print(f"FAILED\n       {exc}")
        return None

    # 2. Extract
    print(f"  [2/3] Extracting with Qwen ({OLLAMA_MODEL}) ...", end=" ", flush=True)
    try:
        record = extract_from_text(text, source_url=url)
        print("OK")
    except (ConnectionError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"FAILED\n       {exc}")
        return None

    # 3. Validate
    validation = validate_university_record(record)
    if validation["warnings"]:
        for w in validation["warnings"]:
            print(f"  ⚠  {w}")
    if not validation["valid"]:
        print("  ✗  Validation failed:")
        for e in validation["errors"]:
            print(f"     - {e}")
        return record   # return anyway so caller can inspect

    name = record.get("name") or "Unknown"
    country = record.get("country") or "?"
    program = record.get("program") or "?"
    print(f"  ✓  {name} | {country} | {program}")

    # 4. Save JSON if requested
    if save_path:
        with open(save_path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, ensure_ascii=False)
        print(f"  💾  Saved to {save_path}")

    # 5. Insert
    if dry_run:
        print("  [3/3] Dry run — skipping DB insert")
    elif auto_insert and validation["valid"]:
        print("  [3/3] Inserting into database ...", end=" ", flush=True)
        new_id = insert_record(record, DB_PATH)
        if new_id:
            print(f"OK  (id={new_id})")
        else:
            print("FAILED")

    return record


# ──────────────────────────────────────────────────────────────────────────────
# Batch runner
# ──────────────────────────────────────────────────────────────────────────────

def process_batch(url_file: Path, dry_run: bool = False,
                  auto_insert: bool = True) -> None:
    urls = [
        line.strip() for line in url_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    if not urls:
        print("No URLs found in file.")
        return

    print(f"Found {len(urls)} URL(s) in {url_file.name}\n")

    success, failed = 0, 0

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}]", end="")
        result = process_url(url, dry_run=dry_run, auto_insert=auto_insert)
        if result:
            success += 1
        else:
            failed += 1

        if i < len(urls):
            print(f"  Waiting {BATCH_DELAY}s ...", flush=True)
            time.sleep(BATCH_DELAY)

    print(f"\n{'─'*60}")
    print(f"Batch complete:  {success} succeeded  |  {failed} failed")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scrape a university page and extract admission data using Qwen2.5 via Ollama"
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--url",   type=str,  help="Single university program URL")
    mode.add_argument("--batch", type=Path, help="Text file with one URL per line")

    parser.add_argument("--save",      type=Path, default=None,
                        help="Save extracted JSON to this path (single URL mode)")
    parser.add_argument("--no-insert", action="store_true",
                        help="Skip DB insert — extract and validate only")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Scrape and extract but do not write to DB")

    args = parser.parse_args()

    auto_insert = not (args.no_insert or args.dry_run)

    if args.url:
        process_url(
            args.url,
            save_path=args.save,
            dry_run=args.dry_run,
            auto_insert=auto_insert,
        )
    else:
        process_batch(args.batch, dry_run=args.dry_run, auto_insert=auto_insert)


if __name__ == "__main__":
    main()