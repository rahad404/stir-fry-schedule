"""Course explorer: browse every section before you build a routine."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from core.data import find_csv_files, load_routine_data

ROOT = Path(__file__).resolve().parent.parent


@st.cache_data(show_spinner=False, max_entries=8)
def _load(paths: tuple[str, ...]):
    frame, sections, courses = load_routine_data(list(paths))
    return frame, tuple(sections), tuple(courses)


def render() -> None:
    paths = tuple(str(p) for p in find_csv_files(ROOT))
    if not paths:
        st.error("No routine CSV found next to the app.")
        return
    _frame, sections, _courses = _load(paths)

    st.title("Course explorer")
    st.caption(
        "Every course in the merged sheets, with the sections, teachers and "
        "time slots you can pick from."
    )

    df = pd.DataFrame(
        [
            {
                "Program": s.program,
                "Course": s.course_code,
                "Title": s.title,
                "Section": s.section,
                "Type": s.kind,
                "Days": ", ".join(s.days),
                "Time": s.time_label,
                "Teacher": s.faculty,
            }
            for s in sections
        ]
    )

    col_a, col_b, col_c = st.columns([2, 2, 1])
    with col_a:
        program = st.selectbox(
            "Program",
            options=["All"] + sorted(df["Program"].unique().tolist()),
        )
    with col_b:
        course_code = st.selectbox(
            "Course",
            options=["All"] + sorted(df["Course"].unique().tolist()),
        )
    with col_c:
        kind = st.selectbox("Type", options=["All", "theory", "lab"])

    view = df
    if program != "All":
        view = view[view["Program"] == program]
    if course_code != "All":
        view = view[view["Course"] == course_code]
    if kind != "All":
        view = view[view["Type"] == kind]

    text = st.text_input("Search", placeholder="Course code, title or teacher…")
    if text:
        needle = text.lower()
        view = view[
            view["Course"].str.lower().str.contains(needle, na=False)
            | view["Title"].str.lower().str.contains(needle, na=False)
            | view["Teacher"].str.lower().str.contains(needle, na=False)
        ]

    st.caption(f"{len(view)} section(s) shown")
    st.dataframe(view, hide_index=True, width="stretch")

    st.download_button(
        "Download this list (CSV)",
        view.to_csv(index=False),
        file_name="sections.csv",
        mime="text/csv",
        icon=":material/download:",
    )


render()
