"""Routine builder: pick courses, tune the filters, get conflict-free routines."""

from __future__ import annotations

import io
from datetime import time
from pathlib import Path

import pandas as pd
import streamlit as st

from core.appearance import APPEARANCE_OPTIONS, theme_script
from core.data import build_from_frames, find_csv_files, load_routine_data
from core.export import (
    grid_html,
    routine_csv,
    routines_csv,
    routines_excel,
    score_breakdown_frame,
)
from core.model import DAY_ORDER, FIRST_SLOT, LAST_SLOT, FilterConfig
from core.solver import check_feasibility, solve

ROOT = Path(__file__).resolve().parent.parent

EFFORTS = {"Quick": 1.5, "Standard": 4.0, "Thorough": 12.0}
PREFERENCES = {
    "Balanced": "balanced",
    "Mornings": "morning",
    "Afternoons": "evening",
    "Compact week": "compact",
    "Spread out": "spread",
}


# --- Data ---------------------------------------------------------------------


@st.cache_data(show_spinner=False, max_entries=8)
def _load_local(paths: tuple[str, ...]):
    frame, sections, courses = load_routine_data(list(paths))
    return frame, tuple(sections), tuple(courses)


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@st.cache_data(show_spinner=False, max_entries=8)
def _load_uploaded(payload: tuple[tuple[str, bytes], ...]):
    frames = []
    for name, blob in payload:
        if len(blob) > MAX_UPLOAD_BYTES:
            raise ValueError(f"{name} is larger than 10 MB.")
        frames.append(
            pd.read_csv(io.StringIO(blob.decode("utf-8-sig", errors="replace")))
        )
    frame, sections, courses = build_from_frames(frames)
    return frame, tuple(sections), tuple(courses)


@st.cache_data(show_spinner=False, max_entries=64)
def _run_solver(
    courses: tuple,
    sections: tuple,
    config: FilterConfig,
    max_routines: int,
    budget: float,
):
    return solve(
        list(courses),
        list(sections),
        config,
        max_routines=max_routines,
        time_budget=budget,
    )


MAX_OPTIONS = 10


def _clock_to_minutes(value: time | None, fallback: int) -> int:
    if value is None:
        return fallback
    return value.hour * 60 + value.minute


# --- Sidebar ------------------------------------------------------------------


def _sidebar() -> tuple[tuple, tuple, str]:
    with st.sidebar:
        st.header("Routine sheet")
        st.caption("Both published tables are merged automatically.")

        uploaded = st.file_uploader(
            "Or upload your own sheets",
            type=["csv"],
            accept_multiple_files=True,
            help="CSV files with the same columns as the published tables.",
        )

        if uploaded:
            payload = tuple((f.name, f.getvalue()) for f in uploaded)
            try:
                _frame, sections, courses = _load_uploaded(payload)
            except Exception as error:  # noqa: BLE001 - surfaced to the user
                st.error(f"Could not read the uploaded sheet: {error}")
                st.stop()
            source = ", ".join(f.name for f in uploaded)
        else:
            paths = tuple(str(p) for p in find_csv_files(ROOT))
            if not paths:
                st.error("No routine CSV found next to the app.")
                st.stop()
            _frame, sections, courses = _load_local(paths)
            source = ", ".join(Path(p).name for p in paths)

        st.caption(f"Loaded from {source}")
        a, b, c = st.columns(3)
        a.metric("Sections", f"{len(sections):,}")
        b.metric("Courses", f"{len(courses)}")
        programs = sorted({course.program for course in courses})
        c.metric("Programs", len(programs))

        st.divider()
        _appearance_control()

    return sections, courses, source


def _appearance_control() -> None:
    """Light/dark switch, wired to Streamlit's own appearance menu."""
    choice = st.segmented_control(
        "Appearance",
        APPEARANCE_OPTIONS,
        default="System",
        key="appearance",
        help="Applies straight away. The menu in the top right does the same.",
    )
    if not choice:
        return
    if "appearance_applied" not in st.session_state:
        st.session_state["appearance_applied"] = choice
        return
    if choice != st.session_state["appearance_applied"]:
        script = theme_script(choice)
        if script:
            st.html(script, unsafe_allow_javascript=True)
        st.session_state["appearance_applied"] = choice


# --- Rendering helpers --------------------------------------------------------


def _course_label(course, program_count: dict[str, int]) -> str:
    tag = " · lab" if course.kind == "lab" else ""
    if program_count.get(course.course_code, 1) > 1:
        return f"{course.course_code} — {course.title} ({course.program}){tag}"
    return f"{course.course_code} — {course.title}{tag}"


def _course_heading(course, program_count: dict[str, int]) -> str:
    """Title-first name, used where the course code would only add noise."""
    tag = " (lab)" if course.kind == "lab" else ""
    if program_count.get(course.course_code, 1) > 1:
        return f"{course.title} ({course.program}){tag}"
    return f"{course.title}{tag}"


def _faculty_by_course(sections) -> dict[str, list[str]]:
    """Teachers who actually take each course, sorted and without TBA."""
    grouped: dict[str, set[str]] = {}
    for section in sections:
        if section.faculty and section.faculty != "TBA":
            grouped.setdefault(section.course_key, set()).add(section.faculty)
    return {key: sorted(names) for key, names in grouped.items()}


def _sections_by_course(sections) -> dict[str, list]:
    """Every section of each course, ordered by start time then section name."""
    grouped: dict[str, list] = {}
    for section in sections:
        grouped.setdefault(section.course_key, []).append(section)
    for options in grouped.values():
        options.sort(key=lambda s: (s.start, s.section))
    return grouped


def _section_label(section) -> str:
    return (
        f"Section {section.section} · {', '.join(section.days)} · "
        f"{section.time_label} · {section.faculty}"
    )


def _grid(routine) -> str:
    return grid_html(routine, dark=st.context.theme.type == "dark")


def _option_metrics(routine) -> dict[str, str]:
    metrics = routine.metrics
    return {
        "Campus days": f"{int(metrics.get('days_used', 0))}",
        "Busiest day": f"{int(metrics.get('max_classes_in_day', 0))} classes",
        "Idle time": f"{int(metrics.get('gap_minutes', 0))} min",
        "Score": f"{routine.score:.1f}",
    }


def _render_option(routine, index: int) -> None:
    metrics = _option_metrics(routine)
    cols = st.columns(4)
    for col, (label, value) in zip(cols, metrics.items()):
        col.metric(
            label, value, help="Lower score is better" if label == "Score" else None
        )

    st.html(_grid(routine))

    left, right = st.columns([3, 2])
    with left:
        st.download_button(
            "Download this routine (CSV)",
            routine_csv(routine),
            file_name=f"routine_option_{index}.csv",
            mime="text/csv",
            icon=":material/download:",
            key=f"dl_csv_{index}",
        )
    with right:
        st.download_button(
            "Download all options (Excel)",
            routines_excel([routine]),
            file_name=f"routine_option_{index}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            key=f"dl_xlsx_{index}",
        )

    with st.expander("Class details and score breakdown"):
        st.dataframe(
            pd.DataFrame(routine.detail_rows()),
            hide_index=True,
            width="stretch",
        )
        st.markdown("**Why this routine scored the way it did**")
        st.dataframe(score_breakdown_frame(routine), hide_index=True, width="stretch")


# --- Page ---------------------------------------------------------------------


def render() -> None:
    sections, courses, _source = _sidebar()
    catalogue = list(courses)
    by_key = {course.key: course for course in catalogue}
    program_count: dict[str, int] = {}
    for course in catalogue:
        program_count[course.course_code] = program_count.get(course.course_code, 0) + 1
    labels = {course.key: _course_label(course, program_count) for course in catalogue}
    faculty_names = sorted(
        {s.faculty for s in sections if s.faculty and s.faculty != "TBA"}
    )

    st.title("Routine builder")
    st.caption(
        "Pick your courses, set the limits you can live with, and get "
        "conflict-free weekly routines ranked by how good they are."
    )

    # -- Step 1: courses ---------------------------------------------------
    st.subheader("1. Your courses")
    chosen_keys = st.multiselect(
        "Courses in your routine",
        options=[course.key for course in catalogue],
        format_func=lambda key: labels[key],
        placeholder="Search by course code or title…",
        help="One section of every course you pick is placed in the routine.",
    )
    chosen = [by_key[key] for key in chosen_keys]

    if chosen:
        sessions = sum(course.sessions for course in chosen)
        labs = sum(1 for course in chosen if course.kind == "lab")
        m1, m2, m3 = st.columns(3)
        m1.metric("Class meetings a week", sessions)
        m2.metric("Lab courses", labs)
        m3.metric("Theory courses", len(chosen) - labs)
    else:
        st.info("Choose at least one course to start building a routine.")

    # -- Step 2: filters ---------------------------------------------------
    st.subheader("2. Your filters")
    with st.container(border=True):
        col_time, col_load, col_goal = st.columns(3)

        with col_time:
            st.markdown("**When you can come in**")
            earliest = st.time_input(
                "Earliest class start",
                value=time(FIRST_SLOT // 60, FIRST_SLOT % 60),
                format="12h",
            )
            latest = st.time_input(
                "Latest class finish",
                value=time(LAST_SLOT // 60, LAST_SLOT % 60),
                format="12h",
            )
            days = st.pills(
                "Days you can attend",
                options=list(DAY_ORDER),
                selection_mode="multi",
                default=list(DAY_ORDER),
            )

        with col_load:
            st.markdown("**How much you can handle**")
            max_classes = st.slider("Max classes in a day", 1, 6, 4)
            max_days = st.slider("Max campus days", 1, 5, 5)
            min_days = st.slider("Min campus days", 1, 5, 1)
            max_hours = st.slider("Max hours on campus a day", 2, 8, 8)
            min_gap = st.slider(
                "Minimum break between classes (min)", 0, 60, 0, step=10
            )

        with col_goal:
            st.markdown("**What matters most**")
            preference_label = st.segmented_control(
                "Goal",
                options=list(PREFERENCES),
                default="Balanced",
                selection_mode="single",
            )
            preference = PREFERENCES.get(preference_label, "balanced")
            routines_wanted = st.slider("Routines to show", 5, 10, 6)
            effort_label = st.selectbox(
                "Search effort",
                options=list(EFFORTS),
                index=1,
                help="More effort means a longer search and a proven optimum.",
            )
            budget = EFFORTS[effort_label]

    # -- Teachers ----------------------------------------------------------
    with st.expander("Teacher preferences (optional)"):
        st.caption(
            "Exclude a teacher from every course, or from one course only. "
            "Preferred teachers are used as a tie-breaker when a choice is free."
        )
        global_excluded = st.multiselect(
            "Never with these teachers",
            options=faculty_names,
            placeholder="Search a teacher name…",
        )
        global_preferred = st.multiselect(
            "Prefer these teachers",
            options=faculty_names,
            placeholder="Search a teacher name…",
        )

        excluded_by_course: list[tuple[str, frozenset[str]]] = []
        preferred_by_course: list[tuple[str, frozenset[str]]] = []
        if chosen:
            teachers = _faculty_by_course(sections)
            for course in chosen:
                options = teachers.get(course.key, [])
                heading = _course_heading(course, program_count)
                if not options:
                    st.caption(f"No named teachers are listed for {heading}.")
                    continue
                row_a, row_b = st.columns(2)
                with row_a:
                    names = st.multiselect(
                        f"Skip teachers in {heading}",
                        options=options,
                        key=f"skip_{course.key}",
                        placeholder="No restriction",
                    )
                with row_b:
                    names_p = st.multiselect(
                        f"Prefer teachers in {heading}",
                        options=options,
                        key=f"pref_{course.key}",
                        placeholder="No preference",
                    )
                if names:
                    excluded_by_course.append((course.key, frozenset(names)))
                if names_p:
                    preferred_by_course.append((course.key, frozenset(names_p)))

    # -- Fixed sections ----------------------------------------------------
    fixed_sections: list[str] = []
    with st.expander("Fixed sections (optional)"):
        st.caption(
            "Lock a specific section and every routine will be built around it. "
            "A locked section is kept even when it falls outside the time, day "
            "or teacher filters above."
        )
        if not chosen:
            st.caption("Pick your courses first to choose sections to lock.")
        else:
            sections_by_course = _sections_by_course(sections)
            for course in chosen:
                options = sections_by_course.get(course.key, [])
                if not options:
                    continue
                lookup = {section.key: section for section in options}
                widget_key = f"fixed_{course.key}"
                current = st.session_state.get(widget_key)
                if current and current not in lookup:
                    st.session_state[widget_key] = ""
                choice = st.selectbox(
                    f"Fix a section in {_course_heading(course, program_count)}",
                    options=["", *lookup],
                    format_func=lambda key, lookup=lookup: (
                        "No fixed section" if not key else _section_label(lookup[key])
                    ),
                    key=widget_key,
                )
                if choice:
                    fixed_sections.append(choice)

    config = FilterConfig(
        earliest_start=_clock_to_minutes(earliest, FIRST_SLOT),
        latest_end=_clock_to_minutes(latest, LAST_SLOT),
        allowed_days=tuple(days) if days else (),
        excluded_faculty=frozenset(global_excluded),
        preferred_faculty=frozenset(global_preferred),
        excluded_by_course=tuple(excluded_by_course),
        preferred_by_course=tuple(preferred_by_course),
        fixed_sections=frozenset(fixed_sections),
        max_classes_per_day=max_classes,
        max_days=max_days,
        min_days=min_days,
        max_minutes_per_day=max_hours * 60,
        max_consecutive_days=5,
        min_gap_minutes=min_gap,
        preference=preference,
    )

    # -- Step 3: results ---------------------------------------------------
    st.subheader("3. Your routines")
    if not chosen:
        st.caption("Your routines will appear here once you pick your courses.")
        return

    feasibility = check_feasibility(chosen, list(sections), config)
    for blocker in feasibility.blockers:
        st.error(blocker)
    for warning in feasibility.warnings:
        st.warning(warning)
    for hint in feasibility.hints:
        st.caption(f"Tip: {hint}")

    if not feasibility.ok:
        st.stop()

    with st.spinner("Building routines…"):
        result = _run_solver(
            tuple(chosen),
            tuple(sections),
            config,
            MAX_OPTIONS,
            budget,
        )
    result.routines = result.routines[:routines_wanted]

    for note in result.notes:
        st.info(note)

    if not result.routines:
        st.error(
            "No conflict-free routine exists for this combination. "
            "Relax a filter, such as the number of campus days or the class "
            "time window."
        )
        return

    best = result.routines[0]
    st.success(
        f"Found {len(result.routines)} routines. "
        + (
            "The best one is proven optimal for these filters."
            if result.exhaustive
            else "The best one is the best found within the search budget."
        )
    )

    overview = st.columns([4, 1, 1, 1])
    with overview[0]:
        st.markdown("**Best option at a glance**")
        st.markdown(
            f"Campus days **{int(best.metrics.get('days_used', 0))}** · "
            f"Busiest day **{int(best.metrics.get('max_classes_in_day', 0))} classes** · "
            f"Idle time **{int(best.metrics.get('gap_minutes', 0))} minutes** · "
            f"Score **{best.score:.1f}**"
        )
    with overview[1]:
        st.metric("Options", len(result.routines))
    with overview[2]:
        st.metric("Searched", f"{result.nodes:,}")
    with overview[3]:
        st.metric("Time", f"{result.elapsed:.1f}s")

    tabs = st.tabs(
        [f"Option {i + 1}" for i in range(len(result.routines))],
        on_change="rerun",
    )
    for index, (tab, routine) in enumerate(zip(tabs, result.routines), start=1):
        if tab.open:
            with tab:
                _render_option(routine, index)

    with st.expander("Compare every option"):
        rows = []
        for index, routine in enumerate(result.routines, start=1):
            rows.append(
                {
                    "Option": index,
                    "Campus days": int(routine.metrics.get("days_used", 0)),
                    "Busiest day": int(routine.metrics.get("max_classes_in_day", 0)),
                    "Idle minutes": int(routine.metrics.get("gap_minutes", 0)),
                    "Score": round(routine.score, 2),
                    "Teachers": ", ".join(
                        sorted({s.faculty for s in routine.assignments if s.faculty})
                    ),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.download_button(
        "Download all options (CSV)",
        routines_csv(result.routines),
        file_name="routine_options.csv",
        mime="text/csv",
        icon=":material/download:",
        key="dl_all_csv",
    )
    st.download_button(
        "Download all options (Excel)",
        routines_excel(result.routines),
        file_name="routine_options.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        key="dl_all_xlsx",
    )


render()
