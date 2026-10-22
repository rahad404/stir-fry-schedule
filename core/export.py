"""Turning routines into things a student can actually use: grids, CSV, Excel."""

from __future__ import annotations

import html
import io

import pandas as pd

from .model import DAY_ORDER, Routine, format_clock

GRID_HEADER = "Time | " + " | ".join(DAY_ORDER)


def routine_frame(routine: Routine) -> pd.DataFrame:
    """One row per class meeting."""
    return pd.DataFrame(routine.detail_rows())


def grid_frame(routine: Routine) -> pd.DataFrame:
    """A day x time-slot matrix, one column per weekday."""
    rows = routine.timetable_rows()
    data: dict[str, list[str]] = {"Time": []}
    for day in DAY_ORDER:
        data[day] = []
    for (start, end), cells in rows:
        data["Time"].append(f"{format_clock(start)} - {format_clock(end)}")
        for day in DAY_ORDER:
            section = cells.get(day)
            data[day].append(
                f"{section.course_code}-{section.section}\n{section.faculty}"
                if section
                else ""
            )
    return pd.DataFrame(data)


def grid_markdown(routine: Routine) -> str:
    """The weekly grid as a markdown table."""
    lines = [
        "| Time | " + " | ".join(DAY_ORDER) + " |",
        "| --- | " + " | ".join(["---"] * len(DAY_ORDER)) + " |",
    ]
    for (start, end), cells in routine.timetable_rows():
        time_cell = f"{format_clock(start)} - {format_clock(end)}"
        row = [time_cell]
        for day in DAY_ORDER:
            section = cells.get(day)
            if section is None:
                row.append("")
            else:
                row.append(
                    f"**{section.course_code}**-{section.section}<br>"
                    f"{_escape(section.title)}<br>"
                    f"<sub>{_escape(section.faculty)}</sub>"
                )
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _escape(text: str) -> str:
    """Make a value safe to drop into a markdown table cell."""
    return (
        str(text)
        .replace("|", "/")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("`", "'")
    )


def _escape_html(text: str) -> str:
    """Make a value safe to drop into the raw HTML grid."""
    return html.escape(str(text), quote=True)


_PALETTE = {
    "light": {
        "border": "#D8E2DD",
        "row": "#EFF4F1",
        "muted": "#5A6B65",
        "accent": "#0B6E4F",
        "accent_bg": "#F0F8F4",
        "accent_text": "#0B3D2C",
        "text": "#12211C",
    },
    "dark": {
        "border": "#2C3A35",
        "row": "#18211D",
        "muted": "#A7B5B0",
        "accent": "#4EC49A",
        "accent_bg": "#1D2C27",
        "accent_text": "#CDEEE0",
        "text": "#EAF2EE",
    },
}


def _grid_css(palette: dict[str, str]) -> str:
    """CSS for the grid table.

    The plain rules use one fixed palette so the table stays readable in
    browsers without ``light-dark()``. The ``@supports`` block then swaps
    every colour for a ``light-dark()`` pair, which resolves against the
    colour scheme Streamlit puts on the page - so the grid follows the app
    theme (light/dark) without the app having to know which one is active.
    """
    light = _PALETTE["light"]
    dark = _PALETTE["dark"]
    return f"""
    <style>
    .rgrid {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
    .rgrid th {{ text-align: left; padding: 7px 9px; color: {palette["muted"]};
                 border-bottom: 1px solid {palette["border"]}; font-weight: 600; }}
    .rgrid td {{ padding: 6px 5px; border-bottom: 1px solid {palette["row"]};
                 vertical-align: top; color: {palette["text"]}; }}
    .rgrid td.t {{ white-space: nowrap; color: {palette["muted"]};
                   font-variant-numeric: tabular-nums; padding-left: 0; }}
    .rgrid .c {{ border-left: 3px solid {palette["accent"]};
                 background: {palette["accent_bg"]}; border-radius: 5px;
                 padding: 5px 8px; }}
    .rgrid .code {{ font-weight: 700; color: {palette["accent_text"]}; }}
    .rgrid .ttl {{ display: block; }}
    .rgrid .fac {{ display: block; color: {palette["muted"]}; font-size: 0.92em; }}
    @supports (color: light-dark(#ffffff, #000000)) {{
      .rgrid th {{ color: light-dark({light["muted"]}, {dark["muted"]});
                   border-bottom-color: light-dark({light["border"]}, {dark["border"]}); }}
      .rgrid td {{ color: light-dark({light["text"]}, {dark["text"]});
                   border-bottom-color: light-dark({light["row"]}, {dark["row"]}); }}
      .rgrid td.t {{ color: light-dark({light["muted"]}, {dark["muted"]}); }}
      .rgrid .c {{ border-left-color: light-dark({light["accent"]}, {dark["accent"]});
                   background: light-dark({light["accent_bg"]}, {dark["accent_bg"]}); }}
      .rgrid .code {{ color: light-dark({light["accent_text"]}, {dark["accent_text"]}); }}
      .rgrid .fac {{ color: light-dark({light["muted"]}, {dark["muted"]}); }}
    }}
    </style>
    """


def grid_html(routine: Routine, dark: bool = False) -> str:
    """The weekly grid as a styled HTML table."""
    palette = _PALETTE["dark" if dark else "light"]
    head = "".join(f"<th>{day}</th>" for day in DAY_ORDER)
    rows: list[str] = []
    for (start, end), cells in routine.timetable_rows():
        cells_html = []
        for day in DAY_ORDER:
            section = cells.get(day)
            if section is None:
                cells_html.append("<td></td>")
                continue
            cells_html.append(
                "<td><div class='c'>"
                f"<span class='code'>{_escape_html(section.course_code)}"
                f"-{_escape_html(section.section)}</span>"
                f"<span class='ttl'>{_escape_html(section.title)}</span>"
                f"<span class='fac'>{_escape_html(section.faculty)}</span>"
                "</div></td>"
            )
        rows.append(
            "<tr>"
            f"<td class='t'>{format_clock(start)} &ndash; {format_clock(end)}</td>"
            + "".join(cells_html)
            + "</tr>"
        )
    style = _grid_css(palette)
    return (
        f"{style}<table class='rgrid'><thead><tr><th>Time</th>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def routines_csv(routines: list[Routine]) -> str:
    """Every routine in one CSV, tagged with the routine number."""
    frames = []
    for index, routine in enumerate(routines, start=1):
        frame = routine_frame(routine)
        frame.insert(0, "Routine", f"Option {index}")
        frames.append(frame)
    if not frames:
        return ""
    return pd.concat(frames, ignore_index=True).to_csv(index=False)


def routine_csv(routine: Routine) -> str:
    return routine_frame(routine).to_csv(index=False)


def routines_excel(routines: list[Routine]) -> bytes:
    """One sheet per routine plus a summary sheet."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary = []
        for index, routine in enumerate(routines, start=1):
            name = f"Option {index}"
            grid = grid_frame(routine)
            grid.to_excel(writer, sheet_name=name, startrow=0, index=False)
            detail = routine_frame(routine)
            detail.to_excel(
                writer, sheet_name=name, startrow=len(grid) + 3, index=False
            )
            summary.append(
                {
                    "Option": name,
                    "Campus days": routine.metrics.get("days_used"),
                    "Max classes in a day": routine.metrics.get("max_classes_in_day"),
                    "Idle minutes": routine.metrics.get("gap_minutes"),
                    "Score": round(routine.score, 2),
                    "Courses": ", ".join(
                        sorted({s.course_code for s in routine.assignments})
                    ),
                }
            )
        pd.DataFrame(summary).to_excel(writer, sheet_name="Summary", index=False)
    return buffer.getvalue()


def score_breakdown_frame(routine: Routine) -> pd.DataFrame:
    """How the routine scored, term by term."""
    labels = {
        "extra_day": "Extra campus day",
        "imbalance": "Classes stacked on one day",
        "window": "Spread of classes within a day",
        "early_class": "Class before 09:00",
        "late_class": "Class after 16:00",
        "faculty_miss": "Preferred teacher not obtained",
        "morning_pref": "Afternoon class (mornings preferred)",
        "evening_pref": "Morning class (afternoons preferred)",
        "day_structure": "Scattered vs contiguous days",
    }
    rows = [
        {"Reason": labels.get(name, name), "Penalty": round(value, 2)}
        for name, value in routine.breakdown.items()
        if value
    ]
    rows.append(
        {"Reason": "Total score (lower is better)", "Penalty": round(routine.score, 2)}
    )
    return pd.DataFrame(rows)
