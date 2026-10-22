"""Core checks for the routine solver and the data pipeline."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from core.data import find_csv_files, load_routine_data
from core.export import (
    grid_frame,
    grid_html,
    grid_markdown,
    routines_csv,
    routines_excel,
)
from core.model import DAY_ORDER, FilterConfig, Routine, Section
from core.solver import check_feasibility, score_routine, solve, verify_routine

ROOT = Path(__file__).resolve().parent.parent
FILES = find_csv_files(ROOT)


@pytest.fixture(scope="module")
def data():
    frame, sections, courses = load_routine_data(FILES)
    return frame, sections, courses


@pytest.fixture(scope="module")
def catalogue(data):
    _, _, courses = data
    return {course.key: course for course in courses}


def _pick(catalogue, codes, program="BSCSE"):
    return [catalogue[f"{program}|{code}"] for code in codes]


def test_both_tables_are_merged(data):
    frame, sections, courses = data
    assert len(frame) > 700
    assert len(sections) > 700
    assert len(courses) > 90
    programs = {course.program for course in courses}
    assert programs == {"BSCSE", "BSDS"}


def test_sections_are_sane(data):
    _, sections, _ = data
    for section in sections:
        assert section.days
        assert all(day in DAY_ORDER for day in section.days)
        assert 8 * 60 <= section.start < section.end <= 17 * 60
        assert section.kind in {"theory", "lab"}
        assert section.faculty
        assert section.title


def test_courses_have_the_right_shape(data):
    _, _, courses = data
    for course in courses:
        assert course.sessions >= 1
        assert course.sessions <= 2
        assert course.section_count >= 1


def test_solver_returns_conflict_free_routines(data, catalogue):
    _, sections, _ = data
    chosen = _pick(
        catalogue, ["CSE 2213", "ENG 1011", "MATH 1151", "CSE 1110", "PHY 2105"]
    )
    result = solve(chosen, sections, FilterConfig(), max_routines=6, time_budget=4.0)
    assert result.routines
    for routine in result.routines:
        assert verify_routine(routine) == []
        assert len(routine.assignments) == len(chosen)
        assert {s.course_key for s in routine.assignments} == {c.key for c in chosen}


def test_solver_respects_the_limits(data, catalogue):
    _, sections, _ = data
    chosen = _pick(
        catalogue, ["CSE 2213", "ENG 1011", "MATH 1151", "CSE 1110", "PHY 2105"]
    )
    config = FilterConfig(max_classes_per_day=2, max_days=3)
    result = solve(chosen, sections, config, max_routines=5, time_budget=4.0)
    for routine in result.routines:
        assert routine.metrics["days_used"] <= 3
        assert routine.metrics["max_classes_in_day"] <= 2


def test_solver_respects_the_time_window(data, catalogue):
    _, sections, _ = data
    chosen = _pick(catalogue, ["CSE 2213", "ENG 1011", "MATH 1151"])
    config = FilterConfig(earliest_start=11 * 60, latest_end=16 * 60 + 30)
    result = solve(chosen, sections, config, max_routines=5, time_budget=4.0)
    assert result.routines
    for routine in result.routines:
        for section in routine.assignments:
            assert section.start >= 11 * 60
            assert section.end <= 16 * 60 + 30


def test_solver_respects_excluded_teachers(data, catalogue):
    _, sections, _ = data
    chosen = _pick(catalogue, ["CSE 2213", "ENG 1011", "MATH 1151"])
    banned = {s.faculty for s in sections if s.course_code == "CSE 2213"}
    config = FilterConfig(excluded_faculty=frozenset(banned))
    result = solve(chosen, sections, config, max_routines=5, time_budget=4.0)
    for routine in result.routines:
        assert not {s.faculty for s in routine.assignments} & banned


def test_solver_respects_allowed_days(data, catalogue):
    _, sections, _ = data
    chosen = _pick(catalogue, ["CSE 2213", "ENG 1011", "MATH 1151"])
    config = FilterConfig(allowed_days=("Sat", "Tue"))
    result = solve(chosen, sections, config, max_routines=5, time_budget=4.0)
    assert result.routines
    for routine in result.routines:
        for section in routine.assignments:
            assert set(section.days) <= {"Sat", "Tue"}


def test_options_are_different(data, catalogue):
    _, sections, _ = data
    chosen = _pick(
        catalogue, ["CSE 2213", "ENG 1011", "MATH 1151", "CSE 1110", "PHY 2105"]
    )
    result = solve(chosen, sections, FilterConfig(), max_routines=6, time_budget=4.0)
    assert len({routine.section_keys for routine in result.routines}) == len(
        result.routines
    )


def test_scores_are_ordered(data, catalogue):
    _, sections, _ = data
    chosen = _pick(catalogue, ["CSE 2213", "ENG 1011", "MATH 1151"])
    result = solve(chosen, sections, FilterConfig(), max_routines=5, time_budget=4.0)
    scores = [routine.score for routine in result.routines]
    assert scores == sorted(scores)


def test_impossible_requests_are_reported(data, catalogue):
    _, sections, _ = data
    chosen = _pick(catalogue, ["CSE 2213", "ENG 1011", "MATH 1151", "CSE 1110"])
    config = FilterConfig(max_classes_per_day=1, max_days=2)
    check = check_feasibility(chosen, sections, config)
    assert not check.ok
    assert check.blockers


def test_empty_time_window_is_reported(data, catalogue):
    _, sections, _ = data
    chosen = _pick(catalogue, ["CSE 2213"])
    config = FilterConfig(earliest_start=14 * 60, latest_end=9 * 60)
    assert not check_feasibility(chosen, sections, config).ok


def test_scoring_is_deterministic(data, catalogue):
    _, sections, _ = data
    chosen = _pick(catalogue, ["CSE 2213", "ENG 1011", "MATH 1151"])
    config = FilterConfig()
    result = solve(chosen, sections, config, max_routines=3, time_budget=4.0)
    routine = result.routines[0]
    total, breakdown, metrics = score_routine(
        routine.assignments, config, sum(c.sessions for c in chosen)
    )
    assert math.isclose(total, routine.score, abs_tol=1e-6)
    assert breakdown == routine.breakdown
    assert metrics == routine.metrics


def test_export_shapes(data, catalogue):
    _, sections, _ = data
    chosen = _pick(catalogue, ["CSE 2213", "ENG 1011", "MATH 1151"])
    result = solve(chosen, sections, FilterConfig(), max_routines=5, time_budget=4.0)
    routine = result.routines[0]

    grid = grid_frame(routine)
    assert list(grid.columns) == ["Time", *DAY_ORDER]

    markdown = grid_markdown(routine)
    assert markdown.count("\n") >= len(routine.timetable_rows())

    csv_text = routines_csv(result.routines)
    assert "Routine" in csv_text

    workbook = routines_excel(result.routines)
    assert workbook[:2] == b"PK"


def test_grid_html_escapes_injected_markup():
    """Titles come from user-uploadable CSVs, so they must never reach the DOM raw."""
    section = Section(
        key="k",
        program="BSCSE",
        course_code="<script>alert(1)</script>",
        title="<img src=x onerror=alert(2)>",
        section="A&B",
        faculty="<b>Dr. X</b>",
        days=("Sat",),
        start=510,
        end=590,
        kind="theory",
        mask=0,
        intervals=((0, 510, 590),),
    )
    routine = Routine(
        assignments=[section],
        score=0.0,
        breakdown={},
        metrics={"days_used": 1, "max_classes_in_day": 1, "gap_minutes": 0},
    )
    html = grid_html(routine)
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x onerror=alert(2)&gt;" in html
    assert "A&amp;B" in html
