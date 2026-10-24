"""Filter guide: what every knob does and how to get a better routine."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render() -> None:
    st.title("Filter guide")
    st.caption(
        "How the routine builder scores and ranks options, and what to change "
        "when the results are not what you hoped for."
    )

    st.subheader("How a routine is ranked")
    st.markdown(
        "Every combination of sections is scored, and the **lowest score wins**. "
        "The score is a penalty, so zero means a perfect week."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Reason": "Extra campus day",
                    "What it means": "You need one more day on campus than your "
                    "class load actually requires.",
                    "Penalty": "14 per extra day",
                },
                {
                    "Reason": "Classes stacked on one day",
                    "What it means": "One day holds more classes than a fair "
                    "share of the week.",
                    "Penalty": "4 per class over the fair share",
                },
                {
                    "Reason": "Spread within a day",
                    "What it means": "The gap between your first and last class "
                    "on a day, so back-to-back days feel shorter.",
                    "Penalty": "0.012 per minute",
                },
                {
                    "Reason": "Class before 09:00",
                    "What it means": "Early starts you may want to avoid.",
                    "Penalty": "2 per class",
                },
                {
                    "Reason": "Class after 16:00",
                    "What it means": "Late finishes.",
                    "Penalty": "2 per class",
                },
                {
                    "Reason": "Preferred teacher not obtained",
                    "What it means": "You asked for a teacher but no section of "
                    "that course could keep them.",
                    "Penalty": "6 per class",
                },
                {
                    "Reason": "Morning or afternoon goal",
                    "What it means": "Classes on the wrong half of the day for "
                    "the goal you picked.",
                    "Penalty": "3 per class",
                },
                {
                    "Reason": "Scattered campus days",
                    "What it means": "Campus days split up instead of sitting "
                    "next to each other.",
                    "Penalty": "4 per split",
                },
            ]
        ),
        hide_index=True,
        width="stretch",
    )

    st.subheader("Getting a better routine")
    st.markdown(
        """
1. **Start loose, then tighten.** Run with every filter open to see how many
   routines exist at all. Only then remove days, tighten the time window or
   cut teachers.

2. **Fewer campus days beats longer days.** Allowing one more day usually
   removes the "extra day" penalty, which is worth 14 points. Letting five
   classes pile into one day costs more than that.

3. **The time window is the strongest lever.** Every published slot is between
   08:30 and 16:30. Moving your earliest start to 09:00 or your latest finish
   to 15:00 throws away whole slots and makes tight weeks possible.

4. **Watch the section count.** If a course is down to one or two sections
   left, your routine has no room to move. The builder warns you about this.

5. **Teacher filters shrink the pool.** A preferred teacher is only a
   tie-breaker; an excluded teacher removes a section for good. Use exclusions
   for teachers you truly cannot attend. The per-course lists only show the
   teachers who actually take that course, so nothing irrelevant is offered.

6. **Fix a section when you already know it.** A fixed section is placed first
   and every other course is arranged around it. It overrides the time, day and
   teacher filters for that one section; two fixed sections that clash stop the
   routine from being built.

7. **Raise the search effort if you need a proven optimum.** The builder tells
   you when the search finished every possibility, and when it simply ran out
   of budget.
"""
    )

    st.subheader("What the builder guarantees")
    st.markdown(
        """
- **No clashes.** Every section of every course is checked against the others
  on a shared timeline, so two classes can never overlap on the same day.
- **One section per course.** You get exactly one section for every course
  you picked.
- **Your filters are respected.** Days, time window, teacher rules, class load
  and campus-day limits are hard constraints, not suggestions.
- **Fixed sections stay put.** A section you lock is in every routine you get
  back, even when it would otherwise be filtered out.
- **Honest about certainty.** When the builder says a routine is optimal it
  has checked every remaining combination; otherwise it says so.
"""
    )

    st.subheader("Appearance")
    st.markdown(
        """
Use **Appearance** at the bottom of the sidebar — or **☰ → Appearance** in the
top-right menu — to switch between **System**, **Light** and **Dark**. The app
remembers your choice in the browser, and the results grid follows it.
"""
    )


render()
