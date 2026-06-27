# University Admission AI

A local AI-powered system that matches student profiles to universities,
extracts new university data using Qwen2.5, validates it, and stores it
in a SQLite database.

---

## Project Structure

```
university_admission_ai/
│
├── data/
│   ├── universities.json           ← seed dataset (40 universities)
│   ├── universities.db             ← SQLite database
│   ├── student_profile.json        ← example student profile
│   └── new_university_record.json  ← example record for insert testing
│
├── scripts/
│   ├── match_student.py    ← matching engine (CLI)
│   ├── qwen_extract.py     ← Qwen2.5 extraction pipeline
│   ├── validate_record.py  ← record validator
│   └── insert_record.py    ← validated insert into SQLite
│
├── app.py                  ← Streamlit web UI
├── requirements.txt
└── README.md
```

---

## Setup

```bash
pip install -r requirements.txt
```

For Qwen2.5 (7B recommended, smaller models work on CPU):

```bash
# HuggingFace will auto-download on first run
# Or download manually:
# https://huggingface.co/Qwen/Qwen2.5-7B-Instruct
```

---

## Running

### 1. Test the matching engine (CLI)

```bash
python scripts/match_student.py
```

Or with a custom profile:

```bash
python scripts/match_student.py --profile data/student_profile.json --top 5
```

### 2. Validate a record

```bash
python scripts/validate_record.py
```

### 3. Insert a new university record

```bash
python scripts/insert_record.py --record data/new_university_record.json
```

### 4. Extract data from text using Qwen2.5

```bash
# From inline text
python scripts/qwen_extract.py --text "Masters in CS, University of Helsinki, IELTS 6.5..."

# From a file
python scripts/qwen_extract.py --file raw_text.txt --url https://university.edu/program --save data/extracted.json
```

### 5. Launch the web app

```bash
streamlit run app.py
```

---

## Daily Workflow

```
1. Copy raw text from a university's official admissions page
2. python scripts/qwen_extract.py --file raw.txt --url <url> --save data/extracted.json
3. Review extracted.json — check critical fields manually
4. python scripts/insert_record.py --record data/extracted.json
5. Refresh the Streamlit app — new university appears immediately
```

---

## Scoring Weights

The raw criterion points below are normalised to a final 0–100 score.

| Criterion         | Points |
|-------------------|--------|
| Degree match      | 15     |
| Category match    | 15     |
| CGPA              | 15     |
| Country preference| 10     |
| Language test     | 10     |
| Budget            | 10     |
| Scholarship       | 10     |
| Research          | 10     |
| Publications      | 10     |
| Work experience   |  5     |
| PR pathway bonus  |  5     |

Raw total = 115; final score = raw score / 115 × 100.

Score ≥ 80 → High | 60–79 → Good | 40–59 → Moderate | < 40 → Low

---

## Next Steps

- [ ] Collect 500+ real university records via Qwen extraction
- [ ] Add FastAPI backend so the UI can run separately from the DB
- [ ] Build fine-tuning dataset from validated extraction examples
- [ ] Fine-tune Qwen on the university extraction task (1000+ examples recommended)
- [ ] Add country-specific PR/visa rule engine
