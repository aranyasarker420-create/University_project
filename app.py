"""
app.py  —  University Admission Recommendation System
------------------------------------------------------
Run:  streamlit run app.py
"""

import sqlite3
import json
import sys
from pathlib import Path
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
DB_PATH  = BASE_DIR / "data" / "universities.db"

sys.path.insert(0, str(BASE_DIR / "scripts"))
from match_student import score_program, admission_band

# ──────────────────────────────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="UniMatch AI",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────────
# Styling
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Main layout */
    .main .block-container { padding-top: 2rem; max-width: 1200px; }
    h1 { font-size: 2.2rem !important; font-weight: 700 !important; letter-spacing: -0.5px; color: #1e293b; }
    h2 { font-size: 1.5rem !important; font-weight: 600 !important; color: #334155; }
    h3 { font-size: 1.1rem !important; font-weight: 600 !important; }

    /* Score badges with gradient */
    .score-badge {
        display: inline-block;
        padding: 6px 16px;
        border-radius: 20px;
        font-size: 0.9rem;
        font-weight: 700;
        letter-spacing: 0.5px;
        text-align: center;
        min-width: 100px;
    }
    .score-excellent { 
        background: linear-gradient(135deg, #10b981 0%, #059669 100%); 
        color: white; 
        box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
    }
    .score-high { 
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); 
        color: white;
        box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
    }
    .score-good { 
        background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%); 
        color: white;
        box-shadow: 0 2px 8px rgba(139, 92, 246, 0.3);
    }
    .score-moderate { 
        background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); 
        color: white;
        box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
    }
    .score-low { 
        background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); 
        color: white;
        box-shadow: 0 2px 8px rgba(239, 68, 68, 0.3);
    }

    /* Enhanced university cards */
    .uni-card {
        background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
        border: 1px solid #e2e8f0;
        border-left: 5px solid #6366f1;
        border-radius: 12px;
        padding: 1.4rem 1.6rem;
        margin-bottom: 1.2rem;
        transition: all 0.3s ease;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    }
    .uni-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
    }
    .uni-card h3 { 
        margin: 0 0 6px 0; 
        font-size: 1.2rem; 
        font-weight: 700; 
        color: #1e293b;
    }
    .uni-card p { 
        margin: 0; 
        color: #64748b; 
        font-size: 0.92rem;
        line-height: 1.5;
    }

    /* Pill badges for criteria */
    .pill-pass { 
        background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%); 
        border: 1px solid #86efac; 
        color: #166534;
        border-radius: 8px; 
        padding: 5px 12px; 
        font-size: 0.85rem;
        font-weight: 500;
        display: inline-block; 
        margin: 3px;
    }
    .pill-fail { 
        background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); 
        border: 1px solid #fca5a5; 
        color: #991b1b;
        border-radius: 8px; 
        padding: 5px 12px; 
        font-size: 0.85rem;
        font-weight: 500;
        display: inline-block; 
        margin: 3px;
    }
    .pill-neutral { 
        background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); 
        border: 1px solid #cbd5e1; 
        color: #475569;
        border-radius: 8px; 
        padding: 5px 12px; 
        font-size: 0.85rem;
        display: inline-block; 
        margin: 3px;
    }

    /* Metric cards */
    .metric-card {
        background: white;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        border: 1px solid #e2e8f0;
        text-align: center;
        box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #6366f1;
    }
    .metric-label {
        font-size: 0.85rem;
        color: #64748b;
        margin-top: 0.3rem;
    }

    /* Info banner */
    .info-banner {
        background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
        border-left: 4px solid #3b82f6;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin-bottom: 1.5rem;
        color: #1e40af;
    }

    /* Sidebar styling */
    .sidebar-content {
        background: #f8fafc;
        border-radius: 10px;
        padding: 1rem;
    }
    
    /* Section headers */
    .section-header {
        font-size: 0.95rem;
        font-weight: 600;
        color: #475569;
        margin: 1.2rem 0 0.6rem 0;
        padding-bottom: 0.3rem;
        border-bottom: 2px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Data helpers
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)   # refresh every 30s so new inserts appear quickly
def load_programs() -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM university_programs")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@st.cache_data(ttl=30)
def load_countries() -> list[str]:
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT DISTINCT country FROM university_programs WHERE country IS NOT NULL ORDER BY country"
    ).fetchall()
    conn.close()
    return ["Any"] + [r[0] for r in rows]


@st.cache_data(ttl=30)
def load_programs_list() -> list[str]:
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT DISTINCT program FROM university_programs WHERE program IS NOT NULL ORDER BY program"
    ).fetchall()
    conn.close()
    return ["Any"] + [r[0] for r in rows]


def chance_badge(chance: str) -> str:
    cls = {
        "Excellent": "score-excellent",
        "High":      "score-high",
        "Good":      "score-good",
        "Moderate":  "score-moderate",
        "Low":       "score-low",
    }.get(chance, "score-low")
    return f'<span class="score-badge {cls}">{chance}</span>'


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar — student profile
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding: 1rem 0;">
        <h2 style="color:#6366f1; margin-bottom:0.5rem;">🎓 Your Profile</h2>
        <p style="color:#64748b; font-size:0.9rem;">Fill in your details for personalized matches</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="section-header">📚 Degree & Program</div>', unsafe_allow_html=True)
    target_degree   = st.selectbox("Target Degree", ["Masters", "Bachelors", "PhD"], index=0)
    target_category = st.selectbox("Program Category", [
        "Engineering & Technology",
        "Business & Management",
        "Computer Science",
        "Medicine & Health",
        "Social Sciences",
        "Arts & Humanities",
        "Data Science",
        "Natural Sciences",
    ], index=0)

    st.markdown('<div class="section-header">🌍 Destination</div>', unsafe_allow_html=True)

    countries = load_countries()
    preferred_country_select = st.selectbox(
        "Preferred Country",
        countries,
        index=0,
    )
    preferred_country_text = st.text_input(
        "Or type a country not in the list", ""
    )
    preferred_country = preferred_country_text.strip() if preferred_country_text.strip() else (
        "" if preferred_country_select == "Any" else preferred_country_select
    )

    st.markdown('<div class="section-header">📊 Academic Scores</div>', unsafe_allow_html=True)
    cgpa       = st.number_input("CGPA",    min_value=0.0, max_value=4.0,  value=3.5, step=0.05, format="%.2f")
    cgpa_scale = st.selectbox("CGPA Scale", [4.0, 5.0, 10.0], index=0)
    ielts      = st.number_input("IELTS",   min_value=0.0, max_value=9.0,  value=7.0, step=0.5,  format="%.1f")
    toefl      = st.number_input("TOEFL iBT (0 = not taken)", min_value=0, max_value=120, value=0)
    gre_score  = st.number_input("GRE Score (optional, 0 = not taken)", min_value=0, max_value=340, value=0)
    gmat_score = st.number_input("GMAT Score (optional, 0 = not taken)", min_value=0, max_value=800, value=0)

    st.markdown('<div class="section-header">🔬 Research & Experience</div>', unsafe_allow_html=True)
    research_exp   = st.checkbox("Have research experience", value=False)
    research_years = st.number_input("Research experience (years)", 0.0, 10.0, 0.0, 0.5) if research_exp else 0.0
    papers         = st.number_input("Published papers", 0, 50, 0)
    work_exp       = st.number_input("Work experience (years)", 0.0, 20.0, 0.0, 0.5)

    st.markdown('<div class="section-header">💰 Financial</div>', unsafe_allow_html=True)
    budget             = st.number_input("Annual budget (USD)", 0, 150_000, 35_000, 5_000)
    scholarship_needed = st.checkbox("Scholarship required", value=True)

    st.markdown('<div class="section-header">🔍 Filters</div>', unsafe_allow_html=True)
    max_tuition    = st.slider("Max tuition/yr (USD)", 0, 80_000, 60_000, 2_000)
    min_pr         = st.slider("Min PR friendliness score", 0, 10, 0)
    scholarship_filter = st.checkbox("Show only universities with scholarship")
    top_n = st.slider("Show top N results", 5, 30, 10)

    st.markdown("---")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Build student dict
# ──────────────────────────────────────────────────────────────────────────────
student = {
    "target_degree":             target_degree,
    "target_program_category":   target_category,
    "preferred_country":         preferred_country,
    "cgpa":                      cgpa,
    "cgpa_scale":                cgpa_scale,
    "ielts_score":               ielts,
    "toefl_score":               toefl if toefl > 0 else None,
    "gre_score":                 gre_score if gre_score > 0 else None,
    "gmat_score":                gmat_score if gmat_score > 0 else None,
    "budget_usd_per_year":       budget,
    "research_experience":       research_exp,
    "research_experience_years": research_years,
    "published_paper_count":     papers,
    "work_experience_years":     work_exp,
    "scholarship_needed":        scholarship_needed,
}


# ──────────────────────────────────────────────────────────────────────────────
# Main content
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center; padding: 1rem 0; margin-bottom: 1rem;">
    <h1 style="color:#6366f1; margin-bottom:0.5rem;">🎓 UniMatch AI</h1>
    <p style="color:#64748b; font-size:1.1rem;">Intelligent University Recommendation System</p>
</div>
""", unsafe_allow_html=True)

# Show active country filter prominently
if preferred_country:
    st.markdown(f"""
    <div class="info-banner">
        <strong>🌍 Showing results for:</strong> {preferred_country}<br>
        <small>Change in the sidebar to see other countries</small>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div class="info-banner">
        <strong>🌍 Showing results for:</strong> All Countries<br>
        <small>Select a country in the sidebar to filter</small>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

all_programs = load_programs()

# ── Apply hard filters BEFORE scoring ────────────────────────────────────────
filtered_programs = []
for prog in all_programs:
    # Country filter
    if preferred_country:
        if str(prog.get("country", "")).strip().lower() != preferred_country.strip().lower():
            continue

    # Tuition filter
    tuition = prog.get("tuition_usd")
    if tuition is not None and tuition > max_tuition:
        # Allow if scholarship available and student needs one
        if not (scholarship_needed and prog.get("scholarship_available")):
            continue

    # PR filter
    pr = prog.get("pr_friendliness_score")
    if pr is not None and float(pr) < min_pr:
        continue

    # Scholarship filter
    if scholarship_filter and not prog.get("scholarship_available"):
        continue

    filtered_programs.append(prog)

# ── Score filtered programs ───────────────────────────────────────────────────
scored = []
for prog in filtered_programs:
    score, chance, criteria = score_program(student, prog)
    scored.append((score, chance, criteria, prog))

scored.sort(key=lambda x: x[0], reverse=True)
top = scored[:top_n]

# ── Summary metrics ───────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{len(all_programs)}</div>
        <div class="metric-label">Total in DB</div>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{len(filtered_programs)}</div>
        <div class="metric-label">After Filters</div>
    </div>
    """, unsafe_allow_html=True)
with col3:
    high_count = sum(1 for s, c, _, _ in scored if c == "Excellent" or c == "High")
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{high_count}</div>
        <div class="metric-label">High Match</div>
    </div>
    """, unsafe_allow_html=True)
with col4:
    good_count = sum(1 for s, c, _, _ in scored if c == "Good")
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{good_count}</div>
        <div class="metric-label">Good Match</div>
    </div>
    """, unsafe_allow_html=True)
with col5:
    top_score = f"{top[0][0]:.0f}" if top else "—"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{top_score}</div>
        <div class="metric-label">Top Score</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# ── No results message ────────────────────────────────────────────────────────
if not top:
    st.warning(
        f"No universities found"
        + (f" in **{preferred_country}**" if preferred_country else "")
        + ". Try:\n"
        "- Selecting **Any** in the country dropdown\n"
        "- Increasing your budget or relaxing filters\n"
        "- Adding more universities to the database using the scraper"
    )
    st.stop()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_cards, tab_table = st.tabs(["📋 Detailed Cards", "📊 Score Table"])

# Cards tab
with tab_cards:
    for rank, (score, chance, criteria, prog) in enumerate(top, 1):
        tuition_str = f"${prog.get('tuition_usd'):,.0f}/yr" if prog.get("tuition_usd") else "Free / Not listed"
        rank_str    = f"QS #{prog.get('qs_ranking')}" if prog.get("qs_ranking") else "Unranked"
        schol_str   = "✓ Scholarship" if prog.get("scholarship_available") else "No scholarship"
        pr_val      = prog.get("pr_friendliness_score")
        pr_str      = f"PR {int(pr_val)}/10" if pr_val else ""

        st.markdown(f"""
<div class="uni-card">
  <div style="display:flex; justify-content:space-between; align-items:flex-start;">
    <div>
      <h3>#{rank} &nbsp; {prog.get('name')}</h3>
      <p>{prog.get('program')} &nbsp;·&nbsp; {prog.get('degree')} &nbsp;·&nbsp;
         {prog.get('city', '') or ''}{', ' if prog.get('city') else ''}{prog.get('country', '')}</p>
    </div>
    <div style="text-align:right;">
      <span style="font-size:1.6rem;font-weight:800;color:#6366f1;">{score}</span>
      <span style="color:#9ca3af;font-size:0.85rem;">/100</span><br>
      {chance_badge(chance)}
    </div>
  </div>
  <div style="margin-top:0.7rem; color:#374151; font-size:0.88rem;">
    💰 {tuition_str} &nbsp;|&nbsp; 🏆 {rank_str} &nbsp;|&nbsp; 🎁 {schol_str}
    {"&nbsp;|&nbsp; 🛂 " + pr_str if pr_str else ""}
  </div>
</div>
""", unsafe_allow_html=True)

        passed_notes = [c.note for c in criteria if c.passed and c.note]
        failed_notes = [c.note for c in criteria if not c.passed and c.note]

        with st.expander("Show full breakdown"):
            if passed_notes:
                st.markdown("**Meets:**")
                st.markdown(
                    " ".join(f'<span class="pill-pass">✓ {n}</span>' for n in passed_notes),
                    unsafe_allow_html=True
                )
            if failed_notes:
                st.markdown("**Gaps:**")
                st.markdown(
                    " ".join(f'<span class="pill-fail">✗ {n}</span>' for n in failed_notes),
                    unsafe_allow_html=True
                )
            st.bar_chart({c.label: c.earned for c in criteria}, height=180)

# Table tab
with tab_table:
    import pandas as pd

    rows = []
    for score, chance, criteria, prog in top:
        rows.append({
            "University":  prog.get("name"),
            "Country":     prog.get("country"),
            "City":        prog.get("city") or "—",
            "Program":     prog.get("program"),
            "Tuition/yr":  f"${prog.get('tuition_usd'):,.0f}" if prog.get("tuition_usd") else "Free",
            "QS Rank":     prog.get("qs_ranking") or "—",
            "IELTS Req.":  prog.get("ielts_requirement") or "—",
            "Scholarship": "✓" if prog.get("scholarship_available") else "✗",
            "PR Score":    prog.get("pr_friendliness_score") or "—",
            "Match":       score,
            "Chance":      chance,
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        height=min(100 + len(rows) * 35, 600),
        column_config={
            "Match": st.column_config.ProgressColumn(
                "Match Score", min_value=0, max_value=100, format="%d/100"
            )
        }
    )

    # Download button
    csv = df.to_csv(index=False)
    st.download_button(
        "⬇️ Download as CSV",
        data=csv,
        file_name="university_matches.csv",
        mime="text/csv",
    )

# ──────────────────────────────────────────────────────────────────────────────
# Footer
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    f"Showing {len(top)} of {len(filtered_programs)} filtered results "
    f"({len(all_programs)} total in database). "
    "Verify all requirements directly with the university."
)