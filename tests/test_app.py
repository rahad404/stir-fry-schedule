"""End-to-end checks of the Streamlit pages using Streamlit's AppTest harness."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent


def _app(script: str) -> AppTest:
    at = AppTest.from_file(str(ROOT / script), default_timeout=180)
    at.run()
    return at


def _fail(at: AppTest) -> None:
    for exception in at.exception:
        raise AssertionError(f"{exception.value}\n{exception.stack_trace}")


@pytest.fixture(scope="module")
def builder() -> AppTest:
    at = _app("app.py")
    _fail(at)
    return at


def test_builder_renders(builder: AppTest):
    assert [t.value for t in builder.title] == ["Routine builder"]
    assert "1. Your courses" in [s.value for s in builder.subheader]
    assert "2. Your filters" in [s.value for s in builder.subheader]
    assert "3. Your routines" in [s.value for s in builder.subheader]


def test_builder_loads_both_tables(builder: AppTest):
    labels = {m.label: m.value for m in builder.metric}
    assert labels["Sections"] == "791"
    assert labels["Courses"] == "107"
    assert labels["Programs"] == "2"


def test_builder_needs_courses(builder: AppTest):
    assert any("Choose at least one course" in i.value for i in builder.info)


def test_builder_solves_after_picking_courses():
    at = _app("app.py")
    picker = at.multiselect[0]
    wanted = [
        option
        for option in picker.options
        if option.startswith("CSE 2213")
        or option.startswith("ENG 1011")
        or option.startswith("MATH 1151")
    ]
    assert len(wanted) == 3
    picker.set_value(wanted)
    at.run()
    _fail(at)

    assert at.tabs
    assert len(at.tabs) == 6
    labels = {m.label: m.value for m in at.metric}
    assert labels["Options"] == "6"
    assert int(labels["Campus days"]) >= 1
    assert not at.error


def test_builder_reports_impossible_requests():
    at = _app("app.py")
    picker = at.multiselect[0]
    wanted = [option for option in picker.options if option.startswith("CSE 2213")]
    picker.set_value(wanted)
    at.run()
    _fail(at)

    # Two campus days cannot hold a course that meets twice a week.
    at.slider(key=None) if False else None
    sliders = [s for s in at.slider if s.label == "Max campus days"]
    sliders[0].set_value(1)
    at.run()
    _fail(at)
    assert at.error


def test_explorer_page_renders():
    at = _app("app_pages/explorer.py")
    _fail(at)
    assert [t.value for t in at.title] == ["Course explorer"]
    assert at.dataframe


def test_guide_page_renders():
    at = _app("app_pages/guide.py")
    _fail(at)
    assert [t.value for t in at.title] == ["Filter guide"]
    assert at.dataframe
    frame = at.dataframe[0].value
    assert "Reason" in frame.columns
    assert "Extra campus day" in frame["Reason"].tolist()
