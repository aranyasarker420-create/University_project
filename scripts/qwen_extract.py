"""
qwen_extract.py
---------------
Uses a locally running Ollama instance to extract structured university
admission data from raw webpage text, then validates the result.

Ollama must be running before you use this script:
    ollama serve
    ollama pull qwen2.5:7b   (or whichever size you downloaded)

Usage:
    python scripts/qwen_extract.py --text "Master's in CS, Helsinki, IELTS 6.5..."
    python scripts/qwen_extract.py --file path/to/raw_text.txt --url https://example.edu/program
    python scripts/qwen_extract.py --file path/to/raw_text.txt --save data/extracted.json
"""

import json
import argparse
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from validate_record import validate_university_record


# ──────────────────────────────────────────────────────────────────────────────
# Ollama config
# ──────────────────────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"   # change to qwen2.5:3b or qwen2.5:14b if needed

# How to find your exact model name:
#   ollama list
# Use the name from the NAME column exactly, e.g. "qwen2.5:7b" or "qwen2.5:3b"


# ──────────────────────────────────────────────────────────────────────────────
# Schema template — every field Qwen should try to fill
# ──────────────────────────────────────────────────────────────────────────────

SCHEMA_TEMPLATE = {
    "name": None,
    "country": None,
    "city": None,
    "degree": None,
    "program": None,
    "program_category": None,
    "language": None,
    "duration_years": None,
    "tuition_usd": None,
    "cgpa_requirement": None,
    "cgpa_scale": 4.0,
    "ielts_requirement": None,
    "toefl_requirement": None,
    "gre_requirement": None,
    "gre_quant_min": None,
    "research_required": False,
    "research_preferred": False,
    "research_experience_required": False,
    "minimum_research_years": 0,
    "published_paper_required": False,
    "published_paper_preferred": False,
    "minimum_published_papers": 0,
    "journal_paper_preferred": False,
    "conference_paper_preferred": False,
    "first_author_preferred": False,
    "indexed_publication_preferred": False,
    "research_proposal_required": False,
    "supervisor_contact_required": False,
    "work_experience_years": 0,
    "scholarship_available": False,
    "scholarship_details": None,
    "application_deadline": None,
    "intake_months": [],
    "acceptance_rate": None,
    "qs_ranking": None,
    "work_permit_friendly": None,
    "pr_friendliness_score": None,
    "part_time_work_allowed": None,
    "living_cost_monthly_usd": None,
    "application_fee_usd": None,
    "official_website": None,
    "program_url": None,
    "scholarship_url": None,
    "source_url": None,
    "last_verified": None,
    "data_confidence_score": None,
    "notes": None,
}

SYSTEM_PROMPT = (
    "You extract university admission information into strict JSON. "
    "Return only the JSON object — no explanation, no markdown fences, no extra text."
)

USER_PROMPT_TEMPLATE = """Extract university admission data from the text below.

Schema to follow exactly:
{schema}

Rules:
- Use null for any field not mentioned in the text. Do not guess.
- Boolean fields must be true or false (lowercase).
- Dates must be YYYY-MM-DD format.
- tuition_usd must be a yearly USD number. If the text gives a non-USD currency,
  convert only if an exchange rate is clearly implied; otherwise use null.
- degree must be one of: Bachelors, Masters, PhD, Diploma, Certificate.
- intake_months must be a JSON array, e.g. ["September"] or ["January", "September"].
- data_confidence_score: your confidence that the extracted data is accurate (0.0 to 1.0).
- source_url: {source_url}

Text:
{text}

Return only the JSON object. No other text."""


# ──────────────────────────────────────────────────────────────────────────────
# Ollama call
# ──────────────────────────────────────────────────────────────────────────────

def _call_ollama(prompt: str) -> str:
    """
    Sends a prompt to the local Ollama API and returns the model's response text.
    Raises ConnectionError if Ollama is not running.
    Raises RuntimeError on any unexpected API error.
    """
    payload = json.dumps({
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.05,   # near-deterministic — better for structured output
            "num_predict": 2000,   # max tokens to generate
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["response"]

    except urllib.error.URLError as exc:
        raise ConnectionError(
            f"\n❌  Cannot reach Ollama at {OLLAMA_URL}\n"
            f"    Make sure Ollama is running:  ollama serve\n"
            f"    Original error: {exc}"
        ) from exc

    except KeyError:
        raise RuntimeError(
            "Ollama response did not contain a 'response' field. "
            "Check your model name with: ollama list"
        )


# ──────────────────────────────────────────────────────────────────────────────
# JSON cleanup
# ──────────────────────────────────────────────────────────────────────────────

def _extract_json_from_response(text: str) -> str:
    """
    Strips markdown fences and any leading/trailing prose the model may add.
    Returns the raw JSON string, ready for json.loads().
    """
    # Remove ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = re.sub(r"```\s*$", "", text).strip()

    # Find the outermost { … } block
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    return text  # let json.loads raise a clear error if still malformed


# ──────────────────────────────────────────────────────────────────────────────
# Main extraction function
# ──────────────────────────────────────────────────────────────────────────────

def extract_university_data(raw_text: str, source_url: str | None = None) -> dict:
    """
    Builds the prompt, calls Ollama, parses the JSON output, validates it,
    and returns a merged dict with schema defaults filled in for missing keys.

    Raises ConnectionError if Ollama is not reachable.
    Raises ValueError if the model output cannot be parsed as JSON.
    """
    prompt = f"{SYSTEM_PROMPT}\n\n" + USER_PROMPT_TEMPLATE.format(
        schema=json.dumps(SCHEMA_TEMPLATE, indent=2),
        source_url=source_url or "unknown",
        text=raw_text.strip(),
    )

    print(f"Sending to Ollama ({OLLAMA_MODEL}) ...", flush=True)
    raw_response = _call_ollama(prompt)

    # Parse
    json_str = _extract_json_from_response(raw_response)
    try:
        extracted = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Model returned invalid JSON: {exc}\n\nRaw output:\n{raw_response}"
        ) from exc

    # Merge extracted data on top of schema defaults
    # (ensures every field always exists in the output, even if null)
    merged = {**SCHEMA_TEMPLATE, **extracted}

    # Validate
    merged["_validation"] = validate_university_record(merged)

    return merged


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extract university admission data using local Ollama + Qwen2.5"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", type=str,  help="Raw admission text (inline string)")
    group.add_argument("--file", type=Path, help="Path to a .txt file with admission text")
    parser.add_argument("--url",  type=str,  default=None, help="Source URL of the text")
    parser.add_argument("--save", type=Path, default=None, help="Save extracted JSON to this path")
    args = parser.parse_args()

    raw_text = args.text if args.text else args.file.read_text(encoding="utf-8")

    try:
        result = extract_university_data(raw_text, source_url=args.url)
    except (ConnectionError, RuntimeError, ValueError) as exc:
        print(exc)
        sys.exit(1)

    validation = result.pop("_validation", {})

    print("\n-- Extracted Record --\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    print("\n-- Validation --")
    print(f"Valid:    {validation.get('valid')}")
    if validation.get("errors"):
        print("Errors:\n  " + "\n  ".join(validation["errors"]))
    if validation.get("warnings"):
        print("Warnings:\n  " + "\n  ".join(validation["warnings"]))

    if args.save:
        with open(args.save, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
        print(f"\nSaved to {args.save}")


def demo():
    """Prints the full prompt that would be sent to Ollama, without calling it."""
    DEMO_TEXT = """
    Master's Programme in Computer Science.
    University of Helsinki, Finland.
    Non-EU student tuition: 18,000 EUR per year.
    IELTS Academic: overall 6.5, minimum 6.0 per component.
    TOEFL iBT: 92.
    Application deadline: 17 January 2027.
    Scholarships: covers 50% or 100% of tuition for excellent students.
    Research experience preferred but not required.
    Duration: 2 years.
    """

    print(f"[DEMO MODE — Ollama model: {OLLAMA_MODEL}]\n")
    print("This is the exact prompt that will be sent:\n")
    print("-" * 60)
    prompt = f"{SYSTEM_PROMPT}\n\n" + USER_PROMPT_TEMPLATE.format(
        schema=json.dumps(SCHEMA_TEMPLATE, indent=2),
        source_url="https://www.helsinki.fi/en/admissions-and-education",
        text=DEMO_TEXT.strip(),
    )
    print(prompt[:3000], "\n...\n")
    print("-" * 60)
    print("\nTo run for real:")
    print('  python scripts/qwen_extract.py --text "your university text here"')
    print("  python scripts/qwen_extract.py --file raw_text.txt --url https://uni.edu/program")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        demo()