"""
insert_record.py
----------------
Validates and inserts a single university record JSON file into the SQLite DB.
Safely handles list fields (serialised as JSON strings) and auto-assigns IDs.

Usage:
    python scripts/insert_record.py
    python scripts/insert_record.py --record data/new_university_record.json
    python scripts/insert_record.py --record data/new_university_record.json --db data/universities.db
"""

import sqlite3
import json
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH  = BASE_DIR / "data" / "universities.db"
DEFAULT_RECORD = BASE_DIR / "data" / "new_university_record.json"

# Add scripts/ to path so validate_record can be imported directly
sys.path.insert(0, str(Path(__file__).parent))
from validate_record import validate_university_record


# Fields that should be stored as JSON strings in SQLite
LIST_FIELDS = {"intake_months"}

# Fields that are auto-managed and should never be passed in INSERT
AUTO_FIELDS = {"id"}

# All known columns in university_programs
KNOWN_COLUMNS = {
    "name", "country", "city", "degree", "program", "program_category",
    "language", "duration_years", "tuition_usd", "cgpa_requirement",
    "cgpa_scale", "ielts_requirement", "toefl_requirement", "gre_requirement",
    "gre_quant_min", "research_required", "research_preferred",
    "research_experience_required", "minimum_research_years",
    "published_paper_required", "published_paper_preferred",
    "minimum_published_papers", "journal_paper_preferred",
    "conference_paper_preferred", "first_author_preferred",
    "indexed_publication_preferred", "research_proposal_required",
    "supervisor_contact_required", "work_experience_years",
    "scholarship_available", "scholarship_details", "application_deadline",
    "intake_months", "acceptance_rate", "qs_ranking", "work_permit_friendly",
    "pr_friendliness_score", "part_time_work_allowed",
    "living_cost_monthly_usd", "application_fee_usd", "official_website",
    "program_url", "scholarship_url", "source_url", "official_logo_url",
    "last_verified", "data_confidence_score", "notes",
}


def insert_record(record: dict, db_path: Path) -> int | None:
    """
    Validates and inserts record. Returns the new row id, or None on failure.
    """
    # Validate
    result = validate_university_record(record)

    if result["warnings"]:
        print("⚠️  Warnings:")
        for w in result["warnings"]:
            print(f"   - {w}")

    if not result["valid"]:
        print("\n❌  Record rejected — validation errors:")
        for e in result["errors"]:
            print(f"   - {e}")
        return None

    # Strip unknown / auto-managed columns
    clean = {k: v for k, v in record.items() if k in KNOWN_COLUMNS and k not in AUTO_FIELDS}

    # Serialise list fields
    for field in LIST_FIELDS:
        if field in clean and isinstance(clean[field], list):
            clean[field] = json.dumps(clean[field])

    # Build parameterised INSERT
    columns      = list(clean.keys())
    placeholders = ", ".join(["?"] * len(columns))
    col_str      = ", ".join(columns)
    values       = [clean[c] for c in columns]

    sql = f"INSERT INTO university_programs ({col_str}) VALUES ({placeholders})"

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(sql, values)
        conn.commit()
        new_id = cur.lastrowid
        print(f"\n✅  Inserted: {record.get('name')} → id = {new_id}")
        return new_id
    except sqlite3.IntegrityError as exc:
        print(f"\n❌  Database integrity error: {exc}")
        return None
    except sqlite3.Error as exc:
        print(f"\n❌  Database error: {exc}")
        return None
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Insert a university record into the database")
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD,
                        help="Path to the JSON record file")
    parser.add_argument("--db",     type=Path, default=DB_PATH,
                        help="Path to the SQLite database")
    args = parser.parse_args()

    if not args.record.exists():
        print(f"❌  Record file not found: {args.record}")
        sys.exit(1)

    with open(args.record, encoding="utf-8") as fh:
        record = json.load(fh)

    new_id = insert_record(record, args.db)
    sys.exit(0 if new_id is not None else 1)


if __name__ == "__main__":
    main()
