"""
match_student.py
----------------
Core matching engine. Loads a student profile and scores every university
program in the database. Returns ranked results with per-criterion breakdown.

Usage:
    python scripts/match_student.py
    python scripts/match_student.py --profile data/student_profile.json
    python scripts/match_student.py --top 5
"""

import sqlite3
import json
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH   = BASE_DIR / "data" / "universities.db"
DEFAULT_PROFILE = BASE_DIR / "data" / "student_profile.json"


# ──────────────────────────────────────────────────────────────────────────────
# Scoring weights  (raw weights are normalised to a 0–100 final score)
# ──────────────────────────────────────────────────────────────────────────────
WEIGHTS = {
    "degree_match":          15,
    "category_match":        15,
    "country_preference":    10,
    "cgpa":                  15,
    "language_test":         10,
    "budget":                10,
    "scholarship":           10,
    "research":              10,
    "publication":           10,
    "work_experience":        5,
    "pr_bonus":               5,
}

MAX_RAW_SCORE = sum(WEIGHTS.values())

ADMISSION_BANDS = {
    (80, 100): "High",
    (60,  79): "Good",
    (40,  59): "Moderate",
    (0,   39): "Low",
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _f(value, default: float = 0.0) -> float:
    """Safely cast to float, returning default on None or failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _b(value) -> bool:
    """Safely cast to bool."""
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes")
    return bool(value)


def admission_band(score: float) -> str:
    for (lo, hi), label in ADMISSION_BANDS.items():
        if lo <= score <= hi:
            return label
    return "Low"


# ──────────────────────────────────────────────────────────────────────────────
# Data loading
# ──────────────────────────────────────────────────────────────────────────────

def load_student(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_programs(db: Path) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM university_programs")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CriterionResult:
    label: str
    earned: float
    max_points: float
    passed: bool
    note: str = ""


def score_program(student: dict, program: dict) -> tuple[float, str, list[CriterionResult]]:
    criteria: list[CriterionResult] = []
    total = 0.0

    def add(label, earned, max_pts, passed, note=""):
        nonlocal total
        criteria.append(CriterionResult(label, earned, max_pts, passed, note))
        total += earned

    # 1. Degree match
    s_deg = str(student.get("target_degree", "")).strip().lower()
    p_deg = str(program.get("degree", "")).strip().lower()
    if s_deg == p_deg:
        add("Degree", WEIGHTS["degree_match"], WEIGHTS["degree_match"], True, f"{p_deg.title()} ✓")
    else:
        add("Degree", 0, WEIGHTS["degree_match"], False, f"Needs {p_deg.title()}, you applied for {s_deg.title()}")

    # 2. Program category
    s_cat = str(student.get("target_program_category", "")).strip().lower()
    p_cat = str(program.get("program_category", "")).strip().lower()
    if s_cat == p_cat:
        add("Category", WEIGHTS["category_match"], WEIGHTS["category_match"], True, f"{program.get('program_category')} ✓")
    else:
        add("Category", 0, WEIGHTS["category_match"], False, f"Program is listed under {program.get('program_category')}")

    # 3. Country preference
    s_country = str(student.get("preferred_country", "")).strip().lower()
    p_country = str(program.get("country", "")).strip().lower()
    if not s_country or s_country == "any":
        add("Country", WEIGHTS["country_preference"] // 2, WEIGHTS["country_preference"], True, "No preference — neutral score")
    elif s_country == p_country:
        add("Country", WEIGHTS["country_preference"], WEIGHTS["country_preference"], True, f"{program.get('country')} ✓")
    else:
        add("Country", 0, WEIGHTS["country_preference"], False, f"Preferred {student.get('preferred_country')}, this is {program.get('country')}")

    # 4. CGPA
    s_cgpa  = _f(student.get("cgpa"))
    s_scale = _f(student.get("cgpa_scale"), 4.0)
    r_cgpa  = _f(program.get("cgpa_requirement"))
    r_scale = _f(program.get("cgpa_scale"), 4.0)

    if r_cgpa == 0:
        add("CGPA", WEIGHTS["cgpa"], WEIGHTS["cgpa"], True, "No minimum stated")
    else:
        # Normalise both to 4.0 scale for comparison
        s_norm = (s_cgpa / s_scale) * 4.0
        r_norm = (r_cgpa / r_scale) * 4.0
        gap = s_norm - r_norm
        if gap >= 0:
            pts = WEIGHTS["cgpa"]
            note = f"Your {s_cgpa:.2f}/{s_scale:.0f} meets {r_cgpa}/{r_scale:.0f} ✓"
        elif gap >= -0.15:          # within 0.15 — borderline
            pts = WEIGHTS["cgpa"] * 0.5
            note = f"Borderline: {s_cgpa:.2f}/{s_scale:.0f} vs {r_cgpa}/{r_scale:.0f}"
        else:
            pts = 0
            note = f"Below: {s_cgpa:.2f}/{s_scale:.0f} vs required {r_cgpa}/{r_scale:.0f}"
        add("CGPA", pts, WEIGHTS["cgpa"], pts > 0, note)

    # 5. Language test (IELTS preferred; TOEFL as fallback)
    s_ielts = _f(student.get("ielts_score"))
    s_toefl = _f(student.get("toefl_score"))
    r_ielts = _f(program.get("ielts_requirement"))
    r_toefl = _f(program.get("toefl_requirement"))

    lang_pts = 0
    lang_note = ""
    if r_ielts == 0 and r_toefl == 0:
        lang_pts = WEIGHTS["language_test"]
        lang_note = "No language test requirement"
    elif r_ielts > 0 and s_ielts >= r_ielts:
        lang_pts = WEIGHTS["language_test"]
        lang_note = f"IELTS {s_ielts} meets {r_ielts} ✓"
    elif r_toefl > 0 and s_toefl >= r_toefl:
        lang_pts = WEIGHTS["language_test"]
        lang_note = f"TOEFL {int(s_toefl)} meets {int(r_toefl)} ✓"
    elif r_ielts > 0:
        gap = r_ielts - s_ielts
        lang_note = f"IELTS short by {gap:.1f} (need {r_ielts}, have {s_ielts or 'none'})"
    add("Language Test", lang_pts, WEIGHTS["language_test"], lang_pts > 0, lang_note)

    # 6. Budget vs tuition
    budget  = _f(student.get("budget_usd_per_year"))
    tuition = _f(program.get("tuition_usd"))
    scholarship = _b(program.get("scholarship_available"))
    if tuition == 0:
        add("Budget", WEIGHTS["budget"], WEIGHTS["budget"], True, "Free / no tuition listed")
    elif budget >= tuition:
        add("Budget", WEIGHTS["budget"], WEIGHTS["budget"], True, f"${tuition:,.0f}/yr within your ${budget:,.0f} budget")
    elif scholarship:
        add("Budget", WEIGHTS["budget"] * 0.7, WEIGHTS["budget"], True, f"Tuition ${tuition:,.0f} exceeds budget, but scholarship available")
    else:
        over = tuition - budget
        add("Budget", 0, WEIGHTS["budget"], False, f"${over:,.0f}/yr over budget, no scholarship")

    # 7. Scholarship
    needs_scholarship = _b(student.get("scholarship_needed"))
    if needs_scholarship:
        if scholarship:
            add("Scholarship", WEIGHTS["scholarship"], WEIGHTS["scholarship"], True, "Scholarship available ✓")
        else:
            add("Scholarship", 0, WEIGHTS["scholarship"], False, "Scholarship needed but not available")
    else:
        add("Scholarship", WEIGHTS["scholarship"] // 2, WEIGHTS["scholarship"], True, "Not required")

    # 8. Research
    s_has_research  = _b(student.get("research_experience"))
    s_research_yrs  = _f(student.get("research_experience_years"))
    p_res_required  = _b(program.get("research_experience_required"))
    p_res_preferred = _b(program.get("research_preferred"))
    p_min_yrs       = _f(program.get("minimum_research_years"))

    if p_res_required:
        if s_has_research and s_research_yrs >= p_min_yrs:
            add("Research", WEIGHTS["research"], WEIGHTS["research"], True,
                f"{s_research_yrs}yr experience meets {p_min_yrs}yr requirement ✓")
        else:
            add("Research", 0, WEIGHTS["research"], False,
                f"Research required ({p_min_yrs}yr), you have {'none' if not s_has_research else f'{s_research_yrs}yr'}")
    elif p_res_preferred and s_has_research:
        add("Research", WEIGHTS["research"] * 0.6, WEIGHTS["research"], True, "Preferred — your experience gives an edge")
    else:
        add("Research", WEIGHTS["research"] * 0.3, WEIGHTS["research"], True, "Not required or not applicable")

    # 9. Publications
    s_papers = _f(student.get("published_paper_count"))
    p_paper_req      = _b(program.get("published_paper_required"))
    p_paper_pref     = _b(program.get("published_paper_preferred"))
    p_min_papers     = _f(program.get("minimum_published_papers"))

    if p_paper_req:
        if s_papers >= p_min_papers:
            add("Publications", WEIGHTS["publication"], WEIGHTS["publication"], True,
                f"{int(s_papers)} papers meets {int(p_min_papers)} requirement ✓")
        else:
            add("Publications", 0, WEIGHTS["publication"], False,
                f"Need {int(p_min_papers)} papers, you have {int(s_papers)}")
    elif p_paper_pref and s_papers > 0:
        bonus = min(WEIGHTS["publication"] * 0.7, s_papers * (WEIGHTS["publication"] * 0.2))
        add("Publications", bonus, WEIGHTS["publication"], True,
            f"{int(s_papers)} paper(s) preferred — gives advantage")
    else:
        add("Publications", WEIGHTS["publication"] * 0.3, WEIGHTS["publication"], True, "Not required")

    # 10. Work experience
    s_work = _f(student.get("work_experience_years"))
    r_work = _f(program.get("work_experience_years"))
    if s_work >= r_work:
        add("Work Exp.", WEIGHTS["work_experience"], WEIGHTS["work_experience"], True,
            f"{s_work}yr meets {r_work}yr requirement ✓" if r_work > 0 else "No requirement")
    else:
        add("Work Exp.", 0, WEIGHTS["work_experience"], False,
            f"Need {r_work}yr, have {s_work}yr")

    # 11. PR bonus
    pr_score = _f(program.get("pr_friendliness_score"))
    if pr_score >= 8:
        add("PR Pathway", WEIGHTS["pr_bonus"], WEIGHTS["pr_bonus"], True, f"Score {int(pr_score)}/10 — strong immigration pathway")
    elif pr_score >= 6:
        add("PR Pathway", WEIGHTS["pr_bonus"] * 0.6, WEIGHTS["pr_bonus"], True, f"Score {int(pr_score)}/10 — decent pathway")
    else:
        add("PR Pathway", 0, WEIGHTS["pr_bonus"], False, f"Score {int(pr_score)}/10 — limited PR options")

    # Normalise raw score to a 0–100 percentage
    normalised_total = (total / MAX_RAW_SCORE) * 100 if MAX_RAW_SCORE else 0.0
    normalised_total = max(0.0, min(100.0, normalised_total))
    return round(normalised_total, 1), admission_band(normalised_total), criteria


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

def run_matching(profile_path: Path, db_path: Path, top_n: int = 10) -> list[dict]:
    student  = load_student(profile_path)
    programs = load_programs(db_path)

    results = []
    for prog in programs:
        score, chance, criteria = score_program(student, prog)
        results.append({
            "university":           prog.get("name"),
            "country":              prog.get("country"),
            "city":                 prog.get("city"),
            "degree":               prog.get("degree"),
            "program":              prog.get("program"),
            "tuition_usd":          prog.get("tuition_usd"),
            "scholarship_available":_b(prog.get("scholarship_available")),
            "qs_ranking":           prog.get("qs_ranking"),
            "pr_friendliness_score":prog.get("pr_friendliness_score"),
            "match_score":          score,
            "admission_chance":     chance,
            "criteria":             criteria,
        })

    results.sort(key=lambda x: x["match_score"], reverse=True)
    return results[:top_n]


def print_results(results: list[dict]) -> None:
    print(f"\n{'─'*70}")
    print(f"  TOP {len(results)} UNIVERSITY MATCHES")
    print(f"{'─'*70}\n")

    for i, r in enumerate(results, 1):
        tuition_str = f"${r['tuition_usd']:,.0f}/yr" if r["tuition_usd"] else "Free"
        rank_str    = f"QS #{r['qs_ranking']}" if r["qs_ranking"] else "Unranked"
        schol_str   = "✓ Scholarship" if r["scholarship_available"] else "No scholarship"

        print(f"  {i:02d}. {r['university']}  [{r['country']}]")
        print(f"      {r['program']} · {r['degree']}")
        print(f"      {tuition_str}  ·  {rank_str}  ·  {schol_str}")
        print(f"      Match Score: {r['match_score']}/100   Chance: {r['admission_chance']}")
        print()

        passed  = [c for c in r["criteria"] if c.passed]
        failed  = [c for c in r["criteria"] if not c.passed]

        if passed:
            print("      ✅  " + " | ".join(c.note for c in passed if c.note))
        if failed:
            print("      ⚠️   " + " | ".join(c.note for c in failed if c.note))
        print()

    print(f"{'─'*70}\n")


def main():
    parser = argparse.ArgumentParser(description="University matching engine")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--db",      type=Path, default=DB_PATH)
    parser.add_argument("--top",     type=int,  default=10)
    args = parser.parse_args()

    results = run_matching(args.profile, args.db, args.top)
    print_results(results)


if __name__ == "__main__":
    main()
