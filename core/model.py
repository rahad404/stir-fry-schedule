"""Domain model for routine building.

The published routine sheets are *section lists*: every row is one running
section of one course, with the days it meets, the time slot, and the teacher.
A student picks exactly one section per course, so the whole problem is a
constraint-satisfaction problem over "choose one section per course".
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

DAY_ORDER: tuple[str, ...] = ("Sat", "Sun", "Mon", "Tue", "Wed")
DAY_INDEX: dict[str, int] = {day: i for i, day in enumerate(DAY_ORDER)}

FIRST_SLOT = 8 * 60 + 30  # 08:30
LAST_SLOT = 16 * 60 + 30  # 16:30
DAY_STRIDE = 512  # bits reserved per day on the occupancy mask

LAB_MINUTES = 120  # a meeting at least this long is a lab block
TBA = "TBA"


def parse_clock(text: object) -> int:
    """'08:30:AM' -> 510 minutes after midnight."""
    raw = str(text).strip().upper()
    pm = raw.endswith("PM")
    if raw.endswith(("AM", "PM")):
        raw = raw[:-2]
    parts = raw.split(":")
    hour = int(parts[0]) % 12
    minute = int(parts[1]) if len(parts) > 1 else 0
    if pm:
        hour += 12
    return hour * 60 + minute


def format_clock(minutes: int) -> str:
    """510 -> '08:30 AM'."""
    hour, minute = divmod(int(minutes), 60)
    suffix = "AM" if hour < 12 else "PM"
    return f"{(hour % 12) or 12:02d}:{minute:02d} {suffix}"


@dataclass(frozen=True)
class Section:
    """One running section of one course."""

    key: str
    program: str
    course_code: str
    title: str
    section: str
    faculty: str
    days: tuple[str, ...]
    start: int
    end: int
    kind: str  # "theory" | "lab"
    mask: int  # occupancy bitmask over the whole week
    intervals: tuple[tuple[int, int, int], ...]  # (day_index, start, end)

    @property
    def course_key(self) -> str:
        return f"{self.program}|{self.course_code}"

    @property
    def duration(self) -> int:
        return self.end - self.start

    @property
    def time_label(self) -> str:
        return f"{format_clock(self.start)} - {format_clock(self.end)}"

    @property
    def label(self) -> str:
        return f"{self.course_code}-{self.section}"


@dataclass(frozen=True)
class Course:
    """A course the student can enrol in (one section must be picked)."""

    key: str
    program: str
    course_code: str
    title: str
    kind: str
    sessions: int  # class meetings per week
    section_count: int

    @property
    def display(self) -> str:
        return f"{self.course_code} — {self.title}"


@dataclass(frozen=True)
class FilterConfig:
    """Every knob the user can turn when shaping the routine."""

    # Time window
    earliest_start: int = FIRST_SLOT
    latest_end: int = LAST_SLOT
    allowed_days: tuple[str, ...] = DAY_ORDER

    # Faculty
    excluded_faculty: frozenset[str] = frozenset()
    preferred_faculty: frozenset[str] = frozenset()
    excluded_by_course: tuple[tuple[str, frozenset[str]], ...] = ()
    preferred_by_course: tuple[tuple[str, frozenset[str]], ...] = ()

    # Workload
    max_classes_per_day: int = 4
    max_days: int = 5
    min_days: int = 1
    max_minutes_per_day: int = 8 * 60
    max_consecutive_days: int = 5
    min_gap_minutes: int = 0

    # Objective
    preference: str = "balanced"  # balanced | morning | evening | compact | spread

    def excluded_for(self, course_key: str) -> frozenset[str]:
        for key, names in self.excluded_by_course:
            if key == course_key:
                return names
        return frozenset()

    def preferred_for(self, course_key: str) -> frozenset[str]:
        for key, names in self.preferred_by_course:
            if key == course_key:
                return names
        return frozenset()


@dataclass
class Routine:
    """A complete, conflict-free assignment of one section per course."""

    assignments: list[Section]
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def days_used(self) -> int:
        return int(self.metrics.get("days_used", 0))

    @property
    def section_keys(self) -> frozenset[str]:
        return frozenset(s.key for s in self.assignments)

    def by_day(self) -> dict[str, list[Section]]:
        out: dict[str, list[Section]] = {day: [] for day in DAY_ORDER}
        for section in self.assignments:
            for day in section.days:
                out[day].append(section)
        for day in out:
            out[day].sort(key=lambda s: (s.start, s.course_code))
        return out

    def timetable_rows(self) -> list[tuple[tuple[int, int], dict[str, Section]]]:
        """Rows of the weekly grid: a shared time block plus its per-day class."""
        blocks = sorted({(s.start, s.end) for s in self.assignments})
        rows = []
        for start, end in blocks:
            cells: dict[str, Section] = {}
            for section in self.assignments:
                if (section.start, section.end) == (start, end):
                    for day in section.days:
                        cells[day] = section
            rows.append(((start, end), cells))
        return rows

    def detail_rows(self) -> list[dict[str, str]]:
        rows = []
        for section in sorted(self.assignments, key=lambda s: (s.days[0], s.start)):
            for day in section.days:
                rows.append(
                    {
                        "Day": day,
                        "Time": section.time_label,
                        "Course": section.course_code,
                        "Title": section.title,
                        "Section": section.section,
                        "Faculty": section.faculty,
                        "Program": section.program,
                    }
                )
        return rows


@dataclass
class SolveResult:
    routines: list[Routine]
    exhaustive: bool
    nodes: int
    elapsed: float
    pool_size: int
    candidate_counts: dict[str, int]
    notes: list[str] = field(default_factory=list)


@dataclass
class Feasibility:
    """Pre-flight check telling the user *why* a request may be impossible."""

    ok: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    empty_courses: list[str] = field(default_factory=list)
    sessions: int = 0
    slot_load: int = 0
    capacity: int = 0


__all__ = [
    "DAY_ORDER",
    "DAY_INDEX",
    "FIRST_SLOT",
    "LAST_SLOT",
    "DAY_STRIDE",
    "LAB_MINUTES",
    "TBA",
    "Section",
    "Course",
    "FilterConfig",
    "Routine",
    "SolveResult",
    "Feasibility",
    "parse_clock",
    "format_clock",
    "replace",
]
