# Routine maker

Build a conflict-free weekly class routine from the published UIU class-routine
sheets. Pick your courses, set the limits you can actually live with, and get
back 5–10 ranked weekly routines — with an honest statement about whether the
best one is *proven* optimal or simply the best one found.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (usually <http://localhost:8501>).

---

## What it does

| Page | Purpose |
| --- | --- |
| **Routine builder** | Pick courses → set filters → get ranked routines, grids and downloads. |
| **Course explorer** | Browse every section in the merged sheets (program, section, days, time, teacher). |
| **Filter guide** | How the routine is scored, and how to get a better result. |

## How the data is handled

Both published tables are merged with pandas and treated as one sheet:

```
Class Routine with faculty assign Fall 2026-Table 1.csv   535 rows
Class Routine with faculty assign Fall 2026-Table 2.csv   256 rows
                                   merged → 791 sections
```

After cleaning there are **791 sections** across **107 courses** (**BSCSE** 73,
**BSDS** 34), **211 teachers**, and 5 teaching days (Sat → Wed).

* A **theory** course meets twice a week (~80 min per meeting, 505 sections).
* A **lab** course meets once a week for ~2.5 hours (286 sections).
* Published slots run from **08:30 to 16:30**; theory classes use the
  (Sat, Tue) or (Sun, Wed) pattern, labs use a single day.
* Messy cells are normalised on load: `"Z (if require"` → `Z`, blank teacher →
  `TBA`, trimmed whitespace, duplicate rows removed.
* You can also **upload your own CSVs** from the sidebar; they replace the
  bundled files.

## How a routine is found

The problem is constraint satisfaction: pick exactly one section per course so
that nothing overlaps. The solver:

1. **Builds candidates** — sections that survive your filters, per course.
2. **Seeds a beam** — a wide, quick search that finds good routines fast.
3. **Runs branch-and-bound** — depth-first search over the courses that have
   the fewest sections left (MRV), with forward checking to prune dead ends.
4. **Proves optimality** — every scoring term is *monotone* (adding a class can
   only make the score worse), so a lower bound on the remaining cost can
   safely prune branches. When the search finishes every branch, the best
   routine is mathematically optimal.
5. **Selects diverse options** — the top routines are picked greedily so the
   5–10 options differ in teachers, sections and time layout, not just in
   score.

Two classes clash exactly when they share an atomic time interval, so the
whole week fits in one small integer bitmask and clash checks are instant.

### The score (lower is better)

| Reason | Penalty |
| --- | --- |
| Extra campus day beyond the minimum your load needs | 14 per day |
| Classes stacked on one day beyond a fair share | 4 per class |
| Spread between your first and last class on a day | 0.012 per minute |
| Class starting before 09:00 | 2 per class |
| Class ending after 16:00 | 2 per class |
| Preferred teacher not obtained | 6 per class |
| Class on the wrong half of the day for your goal | 3 per class |
| Campus days split instead of contiguous | 4 per split |

## The filters

All of these are **hard constraints** — a routine that breaks one is never
returned.

* **When you can come in** — earliest class start, latest class finish, and
  which of Sat/Sun/Mon/Tue/Wed you can attend.
* **How much you can handle** — max classes in a day, max and min campus days,
  max hours on campus per day, minimum break between classes.
* **Teachers** — exclude or prefer teachers globally, or per course. The
  per-course lists only contain the teachers who actually take that course.
* **Fixed sections** — lock one section of a course and every routine is built
  around it. This is a hard lock: the section is kept even if it falls outside
  the time, day or teacher filters, and locked sections that clash are reported.
* **Goal** — balanced, mornings, afternoons, compact week, or spread out.
* **Search effort** — quick (1.5 s), standard (4 s) or thorough (12 s). More
  effort means more of the search space is explored, so more requests can be
  *proven* optimal.

Before searching, the app checks whether the request is even possible and
tells you what to relax (for example: "your courses need 18 class meetings a
week, but 4 days × 4 classes only fits 16").

## Reading the results

* **Campus days** — how many days you must come to campus.
* **Busiest day** — the heaviest day, in classes.
* **Idle time** — minutes of dead time between your first and last class.
* **Score** — the penalty total; lower is better.
* **Proven optimal** vs **best found** — the app says which one you got. When
  the search exhausts its budget it says so plainly rather than pretending.

Downloads are available for a single routine (CSV), a single routine (Excel)
and for every option at once (CSV / Excel, one sheet per routine).

## Light and dark appearance

`[theme.light]` and `[theme.dark]` in `.streamlit/config.toml` define a matched
light/dark palette and turn on Streamlit's built-in appearance switch. You can
change the theme from either place:

* **Sidebar → Appearance** — System / Light / Dark, applied immediately.
* **☰ menu → Appearance** — the same three choices.

Streamlit remembers the choice in the browser, and everything follows it,
including the weekly grid on the results page (its CSS uses `light-dark()`).
The sidebar switch drives Streamlit's own menu, because Streamlit exposes no
Python API for the active theme.

## Project layout

```
app.py                 Entry point: st.navigation router + theme
app_pages/
  builder.py           Routine builder page (filters, solve, results)
  explorer.py          Course explorer page
  guide.py             Filter guide page
core/
  model.py             Section / Course / FilterConfig / Routine dataclasses
  data.py              CSV merge, cleaning, bitmask time grid
  solver.py            Candidate build, feasibility, scoring, search
  export.py            HTML grid, CSV and Excel writers
  appearance.py        Sidebar light/dark switch script
tests/
  test_core.py         Solver, filter and export checks
  test_app.py          Page-level checks via Streamlit's AppTest
.streamlit/config.toml Theme and server settings
```

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

The suite verifies that routines are conflict-free, that every filter is
respected, that the options really differ from each other, that impossible
requests are reported instead of hanging, and that all three pages render.

## Notes and limits

* Only the published slots exist, so tightening the time window can remove a
  course entirely — the app warns you when that happens.
* Titles are truncated in the source sheets ("…Algorithms I Laborator").
* Labs are long by nature, so a large minimum break between classes removes
  most of the remaining room.
* With 10 or more courses the search space is large; the app will report the
  best routine it found rather than an optimum.
