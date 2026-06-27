"""
validate_record.py
------------------
Validates a university record dict before it is inserted into the database.
Checks required fields, numeric ranges, date format, and logical consistency.

Can also be imported and used in other scripts:
    from scripts.validate_record import validate_university_record
"""

from datetime import datetime
from typing import Any


REQUIRED_FIELDS = ["name", "country", "degree", "program"]

DEGREE_OPTIONS = {"bachelors", "masters", "phd", "diploma", "certificate"}

VALID_BOOLEAN_FIELDS = [
    "research_required", "research_preferred", "research_experience_required",
    "published_paper_required", "published_paper_preferred",
    "journal_paper_preferred", "conference_paper_preferred",
    "first_author_preferred", "indexed_publication_preferred",
    "research_proposal_required", "supervisor_contact_required",
    "scholarship_available", "work_permit_friendly", "part_time_work_allowed",
]


def _check_range(val: Any, lo: float, hi: float, field: str, errors: list) -> bool:
    if val is None:
        return True  # optional fields are allowed to be null
    try:
        v = float(val)
        if not (lo <= v <= hi):
            errors.append(f"'{field}' must be between {lo} and {hi}, got {v}")
            return False
        return True
    except (TypeError, ValueError):
        errors.append(f"'{field}' must be a number, got {type(val).__name__}")
        return False


def validate_university_record(record: dict) -> dict:
    """
    Returns {"valid": bool, "errors": list[str], "warnings": list[str]}.
    """
    errors   = []
    warnings = []

    # ── Required fields ────────────────────────────────────────────────────
    for field in REQUIRED_FIELDS:
        val = record.get(field)
        if not val or (isinstance(val, str) and not val.strip()):
            errors.append(f"Missing required field: '{field}'")

    # ── Degree vocabulary ──────────────────────────────────────────────────
    degree = str(record.get("degree", "")).strip().lower()
    if degree and degree not in DEGREE_OPTIONS:
        warnings.append(f"Unusual degree value '{record['degree']}'. Expected one of: {', '.join(DEGREE_OPTIONS)}")

    # ── Numeric ranges ─────────────────────────────────────────────────────
    _check_range(record.get("ielts_requirement"),       0,   9,   "ielts_requirement",       errors)
    _check_range(record.get("toefl_requirement"),       0,   120, "toefl_requirement",       errors)
    _check_range(record.get("cgpa_scale"),              1,   10,  "cgpa_scale",              errors)
    _check_range(record.get("duration_years"),          0.5, 10,  "duration_years",          warnings)
    _check_range(record.get("acceptance_rate"),         0,   100, "acceptance_rate",         errors)
    _check_range(record.get("pr_friendliness_score"),   0,   10,  "pr_friendliness_score",   errors)
    _check_range(record.get("data_confidence_score"),   0,   1,   "data_confidence_score",   errors)
    _check_range(record.get("minimum_research_years"),  0,   10,  "minimum_research_years",  warnings)
    _check_range(record.get("minimum_published_papers"),0,   100, "minimum_published_papers",warnings)

    if record.get("tuition_usd") is not None:
        try:
            t = float(record["tuition_usd"])
            if t < 0:
                errors.append("'tuition_usd' cannot be negative")
            elif t > 200_000:
                warnings.append(f"'tuition_usd' ({t:,.0f}) looks very high — verify it is in USD per year")
        except (TypeError, ValueError):
            errors.append("'tuition_usd' must be a number")

    if record.get("living_cost_monthly_usd") is not None:
        try:
            lc = float(record["living_cost_monthly_usd"])
            if lc < 0:
                errors.append("'living_cost_monthly_usd' cannot be negative")
        except (TypeError, ValueError):
            errors.append("'living_cost_monthly_usd' must be a number")

    # ── CGPA vs CGPA scale ─────────────────────────────────────────────────
    cgpa  = record.get("cgpa_requirement")
    scale = record.get("cgpa_scale")
    if cgpa is not None and scale is not None:
        try:
            if float(cgpa) > float(scale):
                errors.append(f"'cgpa_requirement' ({cgpa}) cannot exceed 'cgpa_scale' ({scale})")
        except (TypeError, ValueError):
            pass  # already caught above

    # ── Date format ────────────────────────────────────────────────────────
    deadline = record.get("application_deadline")
    if deadline:
        try:
            datetime.strptime(str(deadline), "%Y-%m-%d")
        except ValueError:
            errors.append(f"'application_deadline' must be YYYY-MM-DD, got '{deadline}'")

    last_verified = record.get("last_verified")
    if last_verified:
        try:
            datetime.strptime(str(last_verified), "%Y-%m-%d")
        except ValueError:
            errors.append(f"'last_verified' must be YYYY-MM-DD, got '{last_verified}'")

    # ── Boolean field hygiene ──────────────────────────────────────────────
    for bf in VALID_BOOLEAN_FIELDS:
        val = record.get(bf)
        if val is not None and not isinstance(val, (bool, int)):
            warnings.append(f"'{bf}' should be true/false, got '{val}'")

    # ── intake_months type ─────────────────────────────────────────────────
    im = record.get("intake_months")
    if im is not None and not isinstance(im, (list, str)):
        errors.append("'intake_months' must be a list or JSON string")

    # ── Logical consistency checks ─────────────────────────────────────────
    if record.get("published_paper_required") and not record.get("minimum_published_papers"):
        warnings.append("'published_paper_required' is True but 'minimum_published_papers' is 0 or null")

    if record.get("research_experience_required") and not record.get("minimum_research_years"):
        warnings.append("'research_experience_required' is True but 'minimum_research_years' is 0 or null")

    return {
        "valid":    len(errors) == 0,
        "errors":   errors,
        "warnings": warnings,
    }


if __name__ == "__main__":
    import json, sys

    sample = {
        "name": "Example University",
        "country": "Finland",
        "degree": "Masters",
        "program": "Computer Science",
        "program_category": "Engineering & Technology",
        "ielts_requirement": 6.5,
        "toefl_requirement": 92,
        "cgpa_requirement": 3.0,
        "cgpa_scale": 4.0,
        "application_deadline": "2027-01-15",
        "data_confidence_score": 0.85,
        "published_paper_required": True,
        "minimum_published_papers": 0,   # intentional warning trigger
    }

    result = validate_university_record(sample)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)
