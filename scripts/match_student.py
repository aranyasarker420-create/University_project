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
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH   = BASE_DIR / "data" / "universities.db"
DEFAULT_PROFILE = BASE_DIR / "data" / "student_profile.json"


# ──────────────────────────────────────────────────────────────────────────────
# Scoring weights  (raw weights are normalised to a 0–100 final score)
# Enhanced weights for better matching accuracy
# ──────────────────────────────────────────────────────────────────────────────
WEIGHTS = {
    # Core academic fit (40%)
    "degree_match":          12,
    "category_match":        12,
    "cgpa":                  16,
    
    # Language & standardized tests (15%)
    "language_test":         10,
    "gre_gmat":               5,
    
    # Financial fit (15%)
    "budget":                10,
    "scholarship":           10,
    "affordability_bonus":    5,
    
    # Research & experience (15%)
    "research":               8,
    "publication":            7,
    "work_experience":        5,
    
    # Strategic factors (15%)
    "country_preference":     8,
    "university_ranking":     7,
    "pr_pathway":             5,
    "deadline_feasibility":   5,
}

MAX_RAW_SCORE = sum(WEIGHTS.values())

ADMISSION_BANDS = {
    (85, 100): "Excellent",
    (70,  84): "High",
    (55,  69): "Good",
    (40,  54): "Moderate",
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
    """
    Enhanced scoring algorithm with multi-factor matching.
    
    Scoring categories:
    1. Core Academic Fit (40%): Degree match, category match, CGPA
    2. Language & Tests (15%): IELTS/TOEFL, GRE/GMAT
    3. Financial Fit (15%): Budget, scholarship, affordability
    4. Research & Experience (15%): Research, publications, work exp
    5. Strategic Factors (15%): Country preference, ranking, PR pathway, deadlines
    """
    criteria: list[CriterionResult] = []
    total = 0.0

    def add(label, earned, max_pts, passed, note=""):
        nonlocal total
        criteria.append(CriterionResult(label, earned, max_pts, passed, note))
        total += earned

    # ──────────────────────────────────────────────────────────────────────
    # 1. CORE ACADEMIC FIT (40%)
    # ──────────────────────────────────────────────────────────────────────
    
    # 1.1 Degree match (12 points)
    s_deg = str(student.get("target_degree", "")).strip().lower()
    p_deg = str(program.get("degree", "")).strip().lower()
    if s_deg == p_deg:
        add("Degree Match", WEIGHTS["degree_match"], WEIGHTS["degree_match"], True, 
            f"{p_deg.title()} program matches your target")
    elif _is_related_degree(s_deg, p_deg):
        pts = WEIGHTS["degree_match"] * 0.6
        add("Degree Match", pts, WEIGHTS["degree_match"], True, 
            f"{p_deg.title()} is related to your {s_deg.title()} background")
    else:
        add("Degree Match", 0, WEIGHTS["degree_match"], False, 
            f"Program requires {p_deg.title()}, you have {s_deg.title()} background")

    # 1.2 Program category match (12 points)
    s_cat = str(student.get("target_program_category", "")).strip().lower()
    p_cat = str(program.get("program_category", "")).strip().lower()
    if s_cat == p_cat:
        add("Category Match", WEIGHTS["category_match"], WEIGHTS["category_match"], True, 
            f"{program.get('program_category')} ✓")
    elif _is_related_category(s_cat, p_cat):
        pts = WEIGHTS["category_match"] * 0.5
        add("Category Match", pts, WEIGHTS["category_match"], True, 
            f"{program.get('program_category')} is related to your interest")
    else:
        add("Category Match", 0, WEIGHTS["category_match"], False, 
            f"Program is in {program.get('program_category')}, you selected {s_cat}")

    # 1.3 CGPA evaluation (16 points) - Most important academic factor
    s_cgpa  = _f(student.get("cgpa"))
    s_scale = _f(student.get("cgpa_scale"), 4.0)
    r_cgpa  = _f(program.get("cgpa_requirement"))
    r_scale = _f(program.get("cgpa_scale"), 4.0)
    
    # Normalize to 4.0 scale
    s_norm = (s_cgpa / s_scale) * 4.0 if s_scale > 0 else 0
    r_norm = (r_cgpa / r_scale) * 4.0 if r_scale > 0 and r_cgpa > 0 else 0
    
    if r_cgpa == 0 or r_norm == 0:
        # No minimum stated - give partial credit based on absolute CGPA
        if s_norm >= 3.5:
            pts = WEIGHTS["cgpa"]
            note = f"Strong CGPA {s_cgpa:.2f}/{s_scale:.0f} (no minimum stated)"
        elif s_norm >= 3.0:
            pts = WEIGHTS["cgpa"] * 0.7
            note = f"Good CGPA {s_cgpa:.2f}/{s_scale:.0f}"
        else:
            pts = WEIGHTS["cgpa"] * 0.4
            note = f"CGPA {s_cgpa:.2f}/{s_scale:.0f} may limit options"
        add("CGPA", pts, WEIGHTS["cgpa"], pts >= WEIGHTS["cgpa"] * 0.5, note)
    else:
        gap = s_norm - r_norm
        if gap >= 0.3:
            pts = WEIGHTS["cgpa"]
            note = f"Excellent: {s_cgpa:.2f}/{s_scale:.0f} exceeds {r_cgpa}/{r_scale:.0f} by {gap:.2f}"
        elif gap >= 0:
            pts = WEIGHTS["cgpa"] * 0.85
            note = f"Meets requirement: {s_cgpa:.2f}/{s_scale:.0f} ≥ {r_cgpa}/{r_scale:.0f}"
        elif gap >= -0.2:
            pts = WEIGHTS["cgpa"] * 0.5
            note = f"Borderline: {s_cgpa:.2f}/{s_scale:.0f} vs {r_cgpa}/{r_scale:.0f} (gap: {abs(gap):.2f})"
        elif gap >= -0.5:
            pts = WEIGHTS["cgpa"] * 0.2
            note = f"Below requirement: {s_cgpa:.2f}/{s_scale:.0f} vs {r_cgpa}/{r_scale:.0f}"
        else:
            pts = 0
            note = f"Significantly below: {s_cgpa:.2f}/{s_scale:.0f} vs {r_cgpa}/{r_scale:.0f}"
        add("CGPA", pts, WEIGHTS["cgpa"], pts >= WEIGHTS["cgpa"] * 0.5, note)

    # ──────────────────────────────────────────────────────────────────────
    # 2. LANGUAGE & STANDARDIZED TESTS (15%)
    # ──────────────────────────────────────────────────────────────────────
    
    # 2.1 Language test (IELTS/TOEFL) - 10 points
    s_ielts = _f(student.get("ielts_score"))
    s_toefl = _f(student.get("toefl_score"))
    r_ielts = _f(program.get("ielts_requirement"))
    r_toefl = _f(program.get("toefl_requirement"))
    
    lang_pts = 0
    lang_note = ""
    
    if r_ielts == 0 and r_toefl == 0:
        lang_pts = WEIGHTS["language_test"]
        lang_note = "No language test requirement"
    elif r_ielts > 0 and s_ielts > 0:
        if s_ielts >= r_ielts:
            lang_pts = WEIGHTS["language_test"]
            lang_note = f"IELTS {s_ielts} meets {r_ielts} ✓"
        elif s_ielts >= r_ielts - 0.5:
            lang_pts = WEIGHTS["language_test"] * 0.6
            lang_note = f"Close: IELTS {s_ielts} vs {r_ielts} required (consider retaking)"
        else:
            lang_pts = 0
            lang_note = f"IELTS {s_ielts} below {r_ielts} requirement"
    elif r_toefl > 0 and s_toefl > 0:
        if s_toefl >= r_toefl:
            lang_pts = WEIGHTS["language_test"]
            lang_note = f"TOEFL {int(s_toefl)} meets {int(r_toefl)} ✓"
        elif s_toefl >= r_toefl - 10:
            lang_pts = WEIGHTS["language_test"] * 0.6
            lang_note = f"Close: TOEFL {int(s_toefl)} vs {int(r_toefl)} required"
        else:
            lang_pts = 0
            lang_note = f"TOEFL {int(s_toefl)} below {int(r_toefl)} requirement"
    elif r_ielts > 0 and s_ielts == 0:
        lang_note = f"IELTS {r_ielts} required, not provided"
    elif r_toefl > 0 and s_toefl == 0:
        lang_note = f"TOEFL {int(r_toefl)} required, not provided"
    
    add("Language Test", lang_pts, WEIGHTS["language_test"], lang_pts > 0, lang_note)

    # 2.2 GRE/GMAT (5 points) - Bonus for strong scores
    s_gre = _f(student.get("gre_score"))
    s_gmat = _f(student.get("gmat_score"))
    r_gre = _f(program.get("gre_requirement"))
    r_gmat = _f(program.get("gmat_requirement"))
    r_gre_quant = _f(program.get("gre_quant_min"))
    
    gre_pts = 0
    gre_note = ""
    
    if r_gre == 0 and r_gmat == 0 and r_gre_quant == 0:
        gre_pts = WEIGHTS["gre_gmat"]
        gre_note = "GRE/GMAT not required"
    elif r_gre > 0 or r_gre_quant > 0:
        if s_gre > 0:
            if s_gre >= r_gre or (r_gre_quant > 0 and s_gre >= r_gre_quant):
                gre_pts = WEIGHTS["gre_gmat"]
                gre_note = f"GRE {int(s_gre)} meets requirement ✓"
            elif s_gre >= r_gre * 0.9:
                gre_pts = WEIGHTS["gre_gmat"] * 0.5
                gre_note = f"GRE {int(s_gre)} close to requirement"
            else:
                gre_note = f"GRE {int(s_gre)} below {max(r_gre, r_gre_quant)} required"
        elif r_gre > 0:
            gre_note = f"GRE {int(r_gre)} required, not provided"
    elif r_gmat > 0:
        if s_gmat > 0:
            if s_gmat >= r_gmat:
                gre_pts = WEIGHTS["gre_gmat"]
                gre_note = f"GMAT {int(s_gmat)} meets requirement ✓"
            else:
                gre_note = f"GMAT {int(s_gmat)} below {int(r_gmat)} required"
        else:
            gre_note = f"GMAT {int(r_gmat)} required, not provided"
    
    add("GRE/GMAT", gre_pts, WEIGHTS["gre_gmat"], gre_pts > 0, gre_note)

    # ──────────────────────────────────────────────────────────────────────
    # 3. FINANCIAL FIT (15%)
    # ──────────────────────────────────────────────────────────────────────
    
    # 3.1 Budget vs tuition (10 points)
    budget  = _f(student.get("budget_usd_per_year"))
    tuition = _f(program.get("tuition_usd"))
    scholarship = _b(program.get("scholarship_available"))
    living_cost = _f(program.get("living_cost_monthly_usd"))
    total_cost = tuition + (living_cost * 12) if living_cost > 0 else tuition
    
    if tuition == 0:
        add("Budget", WEIGHTS["budget"], WEIGHTS["budget"], True, "Free / no tuition listed")
    elif budget >= total_cost:
        add("Budget", WEIGHTS["budget"], WEIGHTS["budget"], True, 
            f"${total_cost:,.0f}/yr total cost within your ${budget:,.0f} budget")
    elif budget >= tuition:
        if scholarship:
            add("Budget", WEIGHTS["budget"] * 0.8, WEIGHTS["budget"], True, 
                f"Tuition covered, scholarship helps with living costs")
        else:
            add("Budget", WEIGHTS["budget"] * 0.6, WEIGHTS["budget"], True, 
                f"Tuition covered but living costs may be tight")
    elif scholarship and budget >= tuition * 0.7:
        add("Budget", WEIGHTS["budget"] * 0.5, WEIGHTS["budget"], True, 
            f"Scholarship available - ${tuition:,.0f} → ~${tuition*0.6:,.0f}/yr")
    else:
        over = tuition - budget
        add("Budget", 0, WEIGHTS["budget"], False, 
            f"${over:,.0f}/yr over budget, {'scholarship may help' if scholarship else 'no scholarship'}")

    # 3.2 Scholarship match (10 points)
    needs_scholarship = _b(student.get("scholarship_needed"))
    scholarship_details = program.get("scholarship_details", "")
    
    if needs_scholarship:
        if scholarship:
            if scholarship_details:
                add("Scholarship", WEIGHTS["scholarship"], WEIGHTS["scholarship"], True, 
                    f"✓ {scholarship_details[:50]}...")
            else:
                add("Scholarship", WEIGHTS["scholarship"], WEIGHTS["scholarship"], True, 
                    "Scholarship available ✓")
        else:
            add("Scholarship", 0, WEIGHTS["scholarship"], False, 
                "Scholarship needed but not available")
    else:
        add("Scholarship", WEIGHTS["scholarship"], WEIGHTS["scholarship"], True, 
            "Not required - full financial flexibility")

    # 3.3 Affordability bonus (5 points) - Extra points for great value
    if tuition > 0 and budget > 0:
        value_ratio = tuition / budget
        if value_ratio <= 0.5:
            add("Value", WEIGHTS["affordability_bonus"], WEIGHTS["affordability_bonus"], True,
                "Excellent value - well under budget")
        elif value_ratio <= 0.75:
            add("Value", WEIGHTS["affordability_bonus"] * 0.6, WEIGHTS["affordability_bonus"], True,
                "Good value - comfortably within budget")
        elif value_ratio <= 1.0:
            add("Value", WEIGHTS["affordability_bonus"] * 0.3, WEIGHTS["affordability_bonus"], True,
                "Fair value - within budget")
        else:
            add("Value", 0, WEIGHTS["affordability_bonus"], False,
                "Over budget")
    else:
        add("Value", WEIGHTS["affordability_bonus"] * 0.5, WEIGHTS["affordability_bonus"], True,
            "Cost information incomplete")

    # ──────────────────────────────────────────────────────────────────────
    # 4. RESEARCH & EXPERIENCE (15%)
    # ──────────────────────────────────────────────────────────────────────
    
    # 4.1 Research experience (8 points)
    s_has_research  = _b(student.get("research_experience"))
    s_research_yrs  = _f(student.get("research_experience_years"))
    p_res_required  = _b(program.get("research_experience_required"))
    p_res_preferred = _b(program.get("research_preferred"))
    p_min_yrs       = _f(program.get("minimum_research_years"))
    
    if p_res_required:
        if s_has_research and s_research_yrs >= p_min_yrs:
            add("Research", WEIGHTS["research"], WEIGHTS["research"], True,
                f"{s_research_yrs}yr experience meets {p_min_yrs}yr requirement ✓")
        elif s_has_research and s_research_yrs >= p_min_yrs * 0.7:
            add("Research", WEIGHTS["research"] * 0.6, WEIGHTS["research"], True,
                f"{s_research_yrs}yr close to {p_min_yrs}yr requirement")
        else:
            add("Research", 0, WEIGHTS["research"], False,
                f"Research required ({p_min_yrs}yr), you have {'none' if not s_has_research else f'{s_research_yrs}yr'}")
    elif p_res_preferred and s_has_research:
        bonus = min(WEIGHTS["research"], WEIGHTS["research"] * 0.5 + s_research_yrs * 0.1)
        add("Research", bonus, WEIGHTS["research"], True,
            f"{s_research_yrs}yr experience gives competitive edge")
    else:
        add("Research", WEIGHTS["research"] * 0.3, WEIGHTS["research"], True,
            "Not required or not applicable")

    # 4.2 Publications (7 points)
    s_papers = _f(student.get("published_paper_count"))
    p_paper_req      = _b(program.get("published_paper_required"))
    p_paper_pref     = _b(program.get("published_paper_preferred"))
    p_min_papers     = _f(program.get("minimum_published_papers"))
    first_author_pref = _b(program.get("first_author_preferred"))
    
    if p_paper_req:
        if s_papers >= p_min_papers:
            author_bonus = 1.2 if first_author_pref else 1.0
            add("Publications", min(WEIGHTS["publication"] * author_bonus, WEIGHTS["publication"]), 
                WEIGHTS["publication"], True,
                f"{int(s_papers)} papers meets {int(p_min_papers)} requirement ✓")
        else:
            add("Publications", 0, WEIGHTS["publication"], False,
                f"Need {int(p_min_papers)} papers, you have {int(s_papers)}")
    elif p_paper_pref and s_papers > 0:
        base_bonus = min(WEIGHTS["publication"] * 0.6, s_papers * (WEIGHTS["publication"] * 0.25))
        author_bonus = WEIGHTS["publication"] * 0.15 if first_author_pref else 0
        add("Publications", base_bonus + author_bonus, WEIGHTS["publication"], True,
            f"{int(s_papers)} paper(s) preferred — competitive advantage{' + first author bonus' if first_author_pref else ''}")
    elif s_papers > 0:
        add("Publications", WEIGHTS["publication"] * 0.3, WEIGHTS["publication"], True,
            f"{int(s_papers)} publication(s) strengthens application")
    else:
        add("Publications", WEIGHTS["publication"] * 0.3, WEIGHTS["publication"], True,
            "Not required")

    # 4.3 Work experience (5 points)
    s_work = _f(student.get("work_experience_years"))
    r_work = _f(program.get("work_experience_years"))
    
    if r_work > 0:
        if s_work >= r_work:
            add("Work Exp.", WEIGHTS["work_experience"], WEIGHTS["work_experience"], True,
                f"{s_work}yr meets {r_work}yr requirement ✓")
        elif s_work >= r_work * 0.7:
            add("Work Exp.", WEIGHTS["work_experience"] * 0.6, WEIGHTS["work_experience"], True,
                f"{s_work}yr close to {r_work}yr requirement")
        else:
            add("Work Exp.", 0, WEIGHTS["work_experience"], False,
                f"Need {r_work}yr, have {s_work}yr")
    elif s_work > 0:
        bonus = min(WEIGHTS["work_experience"], WEIGHTS["work_experience"] * 0.5 + s_work * 0.1)
        add("Work Exp.", bonus, WEIGHTS["work_experience"], True,
            f"{s_work}yr experience adds value")
    else:
        add("Work Exp.", WEIGHTS["work_experience"] * 0.5, WEIGHTS["work_experience"], True,
            "No requirement")

    # ──────────────────────────────────────────────────────────────────────
    # 5. STRATEGIC FACTORS (15%)
    # ──────────────────────────────────────────────────────────────────────
    
    # 5.1 Country preference (8 points)
    s_country = str(student.get("preferred_country", "")).strip().lower()
    p_country = str(program.get("country", "")).strip().lower()
    if not s_country or s_country == "any":
        add("Country", WEIGHTS["country_preference"], WEIGHTS["country_preference"], True, 
            "Open to all countries — maximum flexibility")
    elif s_country == p_country:
        add("Country", WEIGHTS["country_preference"], WEIGHTS["country_preference"], True, 
            f"{program.get('country')} matches your preference ✓")
    else:
        add("Country", 0, WEIGHTS["country_preference"], False, 
            f"You prefer {student.get('preferred_country')}, this is in {program.get('country')}")

    # 5.2 University ranking (7 points)
    qs_rank = _f(program.get("qs_ranking"))
    if qs_rank > 0:
        if qs_rank <= 50:
            add("Ranking", WEIGHTS["university_ranking"], WEIGHTS["university_ranking"], True,
                f"QS #{int(qs_rank)} — Top 50 globally")
        elif qs_rank <= 100:
            add("Ranking", WEIGHTS["university_ranking"] * 0.9, WEIGHTS["university_ranking"], True,
                f"QS #{int(qs_rank)} — Top 100 globally")
        elif qs_rank <= 200:
            add("Ranking", WEIGHTS["university_ranking"] * 0.75, WEIGHTS["university_ranking"], True,
                f"QS #{int(qs_rank)} — Top 200 globally")
        elif qs_rank <= 500:
            add("Ranking", WEIGHTS["university_ranking"] * 0.5, WEIGHTS["university_ranking"], True,
                f"QS #{int(qs_rank)} — Top 500 globally")
        else:
            add("Ranking", WEIGHTS["university_ranking"] * 0.3, WEIGHTS["university_ranking"], True,
                f"QS #{int(qs_rank)} — Ranked university")
    else:
        add("Ranking", WEIGHTS["university_ranking"] * 0.4, WEIGHTS["university_ranking"], True,
            "QS ranking not available")

    # 5.3 PR pathway (5 points)
    pr_score = _f(program.get("pr_friendliness_score"))
    work_permit_friendly = _b(program.get("work_permit_friendly"))
    part_time_allowed = _b(program.get("part_time_work_allowed"))
    
    if pr_score >= 8:
        pr_pts = WEIGHTS["pr_pathway"]
        pr_note = f"Score {int(pr_score)}/10 — Excellent immigration pathway"
    elif pr_score >= 6:
        pr_pts = WEIGHTS["pr_pathway"] * 0.7
        pr_note = f"Score {int(pr_score)}/10 — Good immigration pathway"
    elif pr_score >= 4:
        pr_pts = WEIGHTS["pr_pathway"] * 0.4
        pr_note = f"Score {int(pr_score)}/10 — Moderate immigration options"
    else:
        pr_pts = 0
        pr_note = f"Score {int(pr_score)}/10 — Limited PR options"
    
    if work_permit_friendly:
        pr_note += " | Work permit friendly"
    if part_time_allowed:
        pr_note += " | Part-time work allowed"
    
    add("PR Pathway", pr_pts, WEIGHTS["pr_pathway"], pr_pts >= WEIGHTS["pr_pathway"] * 0.5, pr_note)

    # 5.4 Deadline feasibility (5 points)
    deadline_str = program.get("application_deadline", "")
    intake_str = program.get("intake_months", "")
    
    if deadline_str:
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d")
            days_left = (deadline - datetime.now()).days
            
            if days_left < 0:
                add("Deadline", 0, WEIGHTS["deadline_feasibility"], False,
                    f"Deadline passed ({deadline_str})")
            elif days_left <= 14:
                add("Deadline", WEIGHTS["deadline_feasibility"] * 0.3, WEIGHTS["deadline_feasibility"], True,
                    f"Urgent: {days_left} days left until {deadline_str}")
            elif days_left <= 30:
                add("Deadline", WEIGHTS["deadline_feasibility"] * 0.6, WEIGHTS["deadline_feasibility"], True,
                    f"{days_left} days left — prepare quickly")
            elif days_left <= 60:
                add("Deadline", WEIGHTS["deadline_feasibility"], WEIGHTS["deadline_feasibility"], True,
                    f"{days_left} days left — good time to apply")
            else:
                add("Deadline", WEIGHTS["deadline_feasibility"], WEIGHTS["deadline_feasibility"], True,
                    f"Plenty of time ({days_left} days) until {deadline_str}")
        except (ValueError, TypeError):
            add("Deadline", WEIGHTS["deadline_feasibility"] * 0.5, WEIGHTS["deadline_feasibility"], True,
                f"Deadline: {deadline_str}")
    else:
        add("Deadline", WEIGHTS["deadline_feasibility"] * 0.5, WEIGHTS["deadline_feasibility"], True,
            "No specific deadline listed (rolling admissions)")

    # ──────────────────────────────────────────────────────────────────────
    # NORMALIZE FINAL SCORE
    # ──────────────────────────────────────────────────────────────────────
    normalised_total = (total / MAX_RAW_SCORE) * 100 if MAX_RAW_SCORE else 0.0
    normalised_total = max(0.0, min(100.0, normalised_total))
    
    return round(normalised_total, 1), admission_band(normalised_total), criteria


def _is_related_degree(s_deg: str, p_deg: str) -> bool:
    """Check if two degree types are related/compatible."""
    related_pairs = [
        ("bachelors", "masters"),
        ("masters", "phd"),
        ("bachelor", "master"),
        ("master", "phd"),
        ("mba", "masters"),
        ("masters", "mba"),
    ]
    for s, p in related_pairs:
        if s in s_deg and p in p_deg:
            return True
    return False


def _is_related_category(s_cat: str, p_cat: str) -> bool:
    """Check if two program categories are related."""
    # Define category relationships
    tech_cats = ["engineering & technology", "computer science", "data science"]
    business_cats = ["business & management", "finance", "economics"]
    health_cats = ["medicine & health", "nursing", "public health"]
    
    for cat_group in [tech_cats, business_cats, health_cats]:
        if s_cat in cat_group and p_cat in cat_group:
            return True
    return False


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
