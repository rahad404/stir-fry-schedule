"""Loading, merging and normalising the published class-routine sheets."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .model import (
    DAY_INDEX,
    DAY_STRIDE,
    FIRST_SLOT,
    LAB_MINUTES,
    TBA,
    Course,
    Section,
    parse_clock,
)

_RAW_SECTION = re.compile(r"\s*\(\s*if\s*require.*$", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


def find_csv_files(directory: str | Path) -> list[Path]:
    """Every routine-looking CSV sitting next to the app."""
    root = Path(directory)
    files = sorted(
        p
        for p in root.glob("*.csv")
        if "routine" in p.name.lower() or "table" in p.name.lower()
    )
    return files or sorted(root.glob("*.csv"))


def _clean_section(text: object) -> str:
    """'Z (if require' -> 'Z'."""
    raw = _SPACES.sub(" ", str(text).strip())
    return _RAW_SECTION.sub("", raw).strip() or raw


def _clean_faculty(text: object) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return TBA
    raw = _SPACES.sub(" ", str(text).strip())
    if not raw or raw.lower() == "nan":
        return TBA
    return raw


def read_tables(paths: list[str | Path]) -> pd.DataFrame:
    """Merge every CSV into one raw frame (the two sheets are the same shape)."""
    frames = []
    for path in paths:
        df = pd.read_csv(path)
        df.columns = [str(c).strip() for c in df.columns]
        df["__source"] = Path(path).name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    return merged


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn the raw merged frame into a tidy, typed frame."""
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]

    for column in ("Program", "Course Code", "Title", "Section", "Time1"):
        if column in df.columns:
            df[column] = df[column].astype("string").str.strip()

    df["Section"] = df["Section"].map(_clean_section)
    df["Faculty Name"] = (
        df["Faculty Name"].map(_clean_faculty) if "Faculty Name" in df else TBA
    )

    split = df["Time1"].astype("string").str.strip().str.split(" - ", expand=True)
    df["Start"] = split[0].map(parse_clock)
    df["End"] = split[1].map(parse_clock)
    df["Duration"] = df["End"] - df["Start"]

    df["Kind"] = df["Duration"].map(lambda d: "lab" if d >= LAB_MINUTES else "theory")

    days: list[tuple[str, ...]] = []
    day1 = df["Day1"].tolist() if "Day1" in df else [None] * len(df)
    day2 = df["Day2"].tolist() if "Day2" in df else [None] * len(df)
    for a, b in zip(day1, day2):
        days.append(tuple(d for d in (a, b) if isinstance(d, str) and d.strip()))
    df["Days"] = days

    df["Course Key"] = df["Program"].astype(str) + "|" + df["Course Code"].astype(str)
    df = df.drop_duplicates(
        subset=["Course Key", "Section", "Days", "Start", "End"], keep="first"
    )
    return df


class TimeGrid:
    """Finest partition of the day that no section straddles.

    Two classes clash exactly when they share at least one atomic interval,
    so a whole week fits in a single small integer bitmask.
    """

    def __init__(self, starts: set[int], ends: set[int]) -> None:
        self.boundaries = sorted(starts | ends)
        self.index = {value: i for i, value in enumerate(self.boundaries)}
        self.width = max(1, len(self.boundaries) - 1)

    def mask(self, day_index: int, start: int, end: int) -> int:
        low = self.index[start]
        high = self.index[end]
        if high <= low:
            return 0
        return ((1 << (high - low)) - 1) << (day_index * self.width + low)


def to_sections(df: pd.DataFrame) -> list[Section]:
    """Build the immutable :class:`Section` objects used by the solver."""
    grid = TimeGrid(set(df["Start"].tolist()), set(df["End"].tolist()))
    sections: list[Section] = []
    for row in df.to_dict("records"):
        days = tuple(row["Days"])
        if not days:
            continue
        intervals: list[tuple[int, int, int]] = []
        mask = 0
        start_raw = int(row["Start"])
        end_raw = int(row["End"])
        for day in days:
            day_index = DAY_INDEX.get(day)
            if day_index is None:
                continue
            start = max(start_raw, FIRST_SLOT)
            end = min(end_raw, FIRST_SLOT + DAY_STRIDE)
            if end <= start:
                continue
            intervals.append((day_index, start, end))
            mask |= grid.mask(day_index, start, end)
        if not intervals:
            continue
        sections.append(
            Section(
                key=f"{row['Course Key']}|{row['Section']}|{'+'.join(days)}|{start_raw}",
                program=str(row["Program"]),
                course_code=str(row["Course Code"]),
                title=str(row["Title"]),
                section=str(row["Section"]),
                faculty=_clean_faculty(row.get("Faculty Name", TBA)),
                days=days,
                start=start_raw,
                end=end_raw,
                kind=str(row["Kind"]),
                mask=mask,
                intervals=tuple(intervals),
            )
        )
    return sections


def course_catalog(df: pd.DataFrame) -> list[Course]:
    """One :class:`Course` per (program, course code) with its section counts."""
    grouped = df.groupby(["Program", "Course Code", "Title", "Kind"], dropna=False)
    courses: list[Course] = []
    for (program, code, title, kind), group in grouped:
        sessions = int(group["Days"].map(len).max())
        courses.append(
            Course(
                key=f"{program}|{code}",
                program=str(program),
                course_code=str(code),
                title=str(title),
                kind=str(kind),
                sessions=sessions,
                section_count=len(group),
            )
        )
    courses.sort(key=lambda c: (c.program, c.course_code))
    return courses


def build_from_frames(
    frames: list[pd.DataFrame],
) -> tuple[pd.DataFrame, list[Section], list[Course]]:
    """Same as :func:`load_routine_data` but from frames the caller already read."""
    if not frames:
        return pd.DataFrame(), [], []
    raw = pd.concat(frames, ignore_index=True)
    df = normalize(raw)
    return df, to_sections(df), course_catalog(df)


def load_routine_data(
    paths: list[str | Path],
) -> tuple[pd.DataFrame, list[Section], list[Course]]:
    """One-stop helper: merged frame + sections + course catalogue."""
    raw = read_tables(paths)
    df = normalize(raw)
    return df, to_sections(df), course_catalog(df)
