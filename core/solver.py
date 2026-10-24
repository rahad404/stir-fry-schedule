"""Conflict-free routine search.

Problem
-------
For every course the student enrols in we must pick exactly one *section*.
Two picked sections may not overlap in time, the student may not exceed a
maximum number of classes per day or a maximum number of days on campus, and
teachers must not be double booked.

Why this is fast
----------------
The published sheet only has 5 working days and a handful of time slots, so
the whole search space is small once it is expressed as bitmasks:

* every section is turned into one integer bitmask over *atomic time
  intervals* (the finest partition that no section straddles), so
  "do these two clash?" is a single ``&`` operation on a 60-bit integer;
* courses are ordered by *fewest available sections first* (MRV), which makes
  the branching factor explode only where it is harmless;
* after every placement a *forward check* verifies that each unplaced course
  still has at least one survivable section, which prunes dead branches long
  before they are fully expanded;
* a beam-search pass produces a strong incumbent set first, so the
  branch-and-bound lower bound can prune from the very first node.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from itertools import combinations, pairwise

from .model import (
    DAY_ORDER,
    TBA,
    Course,
    Feasibility,
    FilterConfig,
    Routine,
    Section,
    SolveResult,
)

# --- Objective weights -------------------------------------------------------

WEIGHTS = {
    "extra_day": 14.0,  # each campus day beyond the theoretical minimum
    "imbalance": 4.0,  # classes stacked on one day
    "window": 0.012,  # minutes between the first and last class of a day
    "early_class": 2.0,  # class starting before 09:00
    "late_class": 2.0,  # class ending after 16:00
    "faculty_miss": 6.0,  # preferred teacher not obtained
    "morning_pref": 3.0,  # afternoon class when mornings are preferred
    "evening_pref": 3.0,  # morning class when afternoons are preferred
    "day_structure": 4.0,  # scattered vs contiguous campus days
}

DIVERSITY_WEIGHT = 10.0
TIME_TARGETS = {"morning": 9 * 60 + 30, "evening": 14 * 60, "balanced": 11 * 60}


# --- Candidate preparation ---------------------------------------------------


def _section_passes(section: Section, config: FilterConfig) -> bool:
    if not all(day in config.allowed_days for day in section.days):
        return False
    if section.start < config.earliest_start or section.end > config.latest_end:
        return False
    return section.faculty not in config.excluded_faculty


def build_candidates(
    courses: list[Course], sections: list[Section], config: FilterConfig
) -> tuple[dict[str, tuple[Section, ...]], list[str]]:
    """Sections still in play for every course, plus the courses left empty."""
    by_course: dict[str, list[Section]] = {course.key: [] for course in courses}
    fixed_by_course: dict[str, set[str]] = {}
    for section in sections:
        bucket = by_course.get(section.course_key)
        if bucket is None:
            continue
        if section.key in config.fixed_sections:
            # A locked section is kept even when it falls outside the filters.
            fixed_by_course.setdefault(section.course_key, set()).add(section.key)
            bucket.append(section)
            continue
        if not _section_passes(section, config):
            continue
        if section.faculty in config.excluded_for(section.course_key):
            continue
        bucket.append(section)

    empty: list[str] = []
    result: dict[str, tuple[Section, ...]] = {}
    for course in courses:
        options = by_course.get(course.key, [])
        fixed = fixed_by_course.get(course.key)
        if fixed is not None:
            options = [section for section in options if section.key in fixed]
        if not options:
            empty.append(course.display)
            continue
        result[course.key] = tuple(
            sorted(options, key=lambda s: _candidate_order(s, course, config))
        )
    return result, empty


def _candidate_order(section: Section, course: Course, config: FilterConfig) -> tuple:
    """Cheap static ordering so the search meets good sections first."""
    preferred = config.preferred_for(course.key) | config.preferred_faculty
    faculty_rank = 0 if section.faculty in preferred else 1
    target = TIME_TARGETS.get(config.preference, TIME_TARGETS["balanced"])
    return (faculty_rank, abs(section.start - target), section.start, section.section)


# --- Feasibility pre-flight --------------------------------------------------


def check_feasibility(
    courses: list[Course],
    sections: list[Section],
    config: FilterConfig,
) -> Feasibility:
    """Explain *before* searching whether the request can possibly work."""
    candidates, empty = build_candidates(courses, sections, config)
    result = Feasibility(ok=True, empty_courses=list(empty))

    if not courses:
        result.ok = False
        result.blockers.append("Pick at least one course to build a routine.")
        return result

    for display in empty:
        result.blockers.append(
            f"No section of '{display}' survives your filters "
            "(time window, allowed days or excluded teachers)."
        )

    course_keys = {course.key for course in courses}
    fixed = [
        section
        for section in sections
        if section.key in config.fixed_sections and section.course_key in course_keys
    ]
    for section in fixed:
        outside = not _section_passes(section, config) or (
            section.faculty in config.excluded_for(section.course_key)
        )
        if outside:
            result.warnings.append(
                f"Locked section {section.label} is outside your time, day or "
                "teacher filters, but it is kept because you fixed it."
            )
    for first, second in combinations(fixed, 2):
        if first.course_key == second.course_key:
            continue
        if first.mask & second.mask:
            result.ok = False
            result.blockers.append(
                f"Locked sections {first.label} and {second.label} clash, so no "
                "routine can contain both."
            )

    sessions = sum(course.sessions for course in courses)
    result.sessions = sessions

    # A theory meeting blocks one slot on two days; a lab blocks about three.
    slot_load = sum(
        (3 if course.kind == "lab" else 1) * course.sessions for course in courses
    )
    result.slot_load = slot_load
    result.capacity = config.max_days * 6

    class_capacity = config.max_days * config.max_classes_per_day
    if sessions > class_capacity:
        result.ok = False
        result.blockers.append(
            f"Your courses need {sessions} class meetings per week, but "
            f"{config.max_days} day(s) x {config.max_classes_per_day} classes/day "
            f"only fits {class_capacity}."
        )
        result.hints.append(
            f"Raise 'max days' to {math.ceil(sessions / config.max_classes_per_day)} "
            f"or raise 'max classes per day' to "
            f"{math.ceil(sessions / config.max_days)}."
        )

    if slot_load > result.capacity:
        result.ok = False
        result.blockers.append(
            f"Your courses occupy about {slot_load} slot-hours but only "
            f"{result.capacity} are available across {config.max_days} day(s)."
        )
        result.hints.append("Give yourself one more campus day or drop a course.")

    if any(course.sessions > config.max_days for course in courses):
        result.ok = False
        worst = max(course.sessions for course in courses)
        affected = ", ".join(
            course.display for course in courses if course.sessions > config.max_days
        )
        result.blockers.append(
            f"Every course needs at least {worst} different days, but you allowed "
            f"only {config.max_days}. Affects: {affected}."
        )
        result.hints.append(f"Set 'max days' to at least {worst}.")

    if config.min_days > config.max_days:
        result.ok = False
        result.blockers.append("Minimum days is larger than maximum days.")

    if config.earliest_start >= config.latest_end:
        result.ok = False
        result.blockers.append(
            "The earliest class starts after the latest finish time, "
            "so no class can fit in your day."
        )

    if not config.allowed_days:
        result.ok = False
        result.blockers.append("Pick at least one day you are willing to come in.")

    if config.max_classes_per_day <= 1 and any(
        course.sessions > 1 for course in courses
    ):
        result.ok = False
        result.blockers.append(
            "With at most one class per day a course that meets twice a week "
            "can never be placed."
        )

    if config.min_gap_minutes and any(course.kind == "lab" for course in courses):
        result.warnings.append(
            "Labs run 2.5 hours, so a large minimum break between classes "
            "removes most of the room you have left."
        )

    fixed_course_keys = {section.course_key for section in fixed}
    thin = [
        f"{course.display} ({len(options)} section(s) left)"
        for course in courses
        if course.key not in fixed_course_keys
        for options in [candidates.get(course.key, ())]
        if 0 < len(options) <= 2
    ]
    if thin:
        result.warnings.append("Very few sections left for: " + "; ".join(thin))

    if not result.blockers and len(candidates) == len(courses):
        result.hints.append(
            "Filters look workable. Tighter filters mean fewer alternatives, "
            "so relax one if too few routines appear."
        )
    return result


# --- Scoring -----------------------------------------------------------------


def _ideal_days(sessions: int, config: FilterConfig) -> int:
    per_day = max(1, config.max_classes_per_day)
    return max(config.min_days, math.ceil(sessions / per_day))


def _balanced_per_day(sessions: int, days: int) -> int:
    return math.ceil(sessions / max(1, days))


def score_routine(
    assignments: list[Section], config: FilterConfig, sessions: int
) -> tuple[float, dict[str, float], dict[str, float]]:
    """Lower is better. Returns (total, breakdown, metrics).

    Every term of this score is *monotone*: adding a class can only make the
    score grow. That is what allows the branch-and-bound to prove optimality
    instead of merely guessing.
    """
    breakdown: dict[str, float] = {name: 0.0 for name in WEIGHTS}
    metrics: dict[str, float] = {}

    per_day: dict[int, list[Section]] = {}
    for section in assignments:
        for day_index, _, _ in section.intervals:
            per_day.setdefault(day_index, []).append(section)

    days_used = len(per_day)
    metrics["days_used"] = days_used
    metrics["weekly_minutes"] = sum(s.duration for s in assignments)
    metrics["classes_total"] = len(assignments)

    ideal = _ideal_days(sessions, config)
    metrics["ideal_days"] = ideal
    breakdown["extra_day"] = WEIGHTS["extra_day"] * max(0, days_used - ideal)

    if days_used:
        balanced = _balanced_per_day(sessions, days_used)
        metrics["max_classes_in_day"] = max(
            (len(v) for v in per_day.values()), default=0
        )
        metrics["balanced_classes_per_day"] = balanced
        breakdown["imbalance"] = WEIGHTS["imbalance"] * sum(
            max(0, len(v) - balanced) for v in per_day.values()
        )

    # "Window" is the span from the first class to the last class of a day.
    # It only ever grows, so it doubles as an idle-time proxy and as a bound.
    window_total = 0
    idle_total = 0
    for sections in per_day.values():
        starts = [s.start for s in sections]
        ends = [s.end for s in sections]
        window_total += max(ends) - min(starts)
        idle_total += (max(ends) - min(starts)) - sum(s.duration for s in sections)
    metrics["window_minutes"] = window_total
    metrics["gap_minutes"] = idle_total
    breakdown["window"] = WEIGHTS["window"] * window_total

    for section in assignments:
        if section.start < 9 * 60:
            breakdown["early_class"] += WEIGHTS["early_class"]
        if section.end > 16 * 60:
            breakdown["late_class"] += WEIGHTS["late_class"]
        preferred = config.preferred_faculty | config.preferred_for(section.course_key)
        if preferred and section.faculty not in preferred:
            breakdown["faculty_miss"] += WEIGHTS["faculty_miss"]
        if config.preference == "morning" and section.start >= 12 * 60:
            breakdown["morning_pref"] += WEIGHTS["morning_pref"]
        elif config.preference == "evening" and section.end <= 12 * 60:
            breakdown["evening_pref"] += WEIGHTS["evening_pref"]

    used = sorted(per_day)
    if len(used) > 1:
        gaps = sum(1 for a, b in pairwise(used) if b - a > 1)
        adjacency = sum(1 for a, b in pairwise(used) if b - a == 1)
        metrics["day_gaps"] = gaps
        metrics["adjacent_days"] = adjacency
        if config.preference == "compact":
            breakdown["day_structure"] = WEIGHTS["day_structure"] * gaps
        elif config.preference == "spread":
            breakdown["day_structure"] = WEIGHTS["day_structure"] * adjacency

    total = sum(breakdown.values())
    return total, breakdown, metrics


# --- Search state ------------------------------------------------------------


@dataclass
class _State:
    occ: int = 0
    day_counts: list[int] = field(default_factory=lambda: [0] * len(DAY_ORDER))
    day_minutes: list[int] = field(default_factory=lambda: [0] * len(DAY_ORDER))
    day_intervals: list[list[tuple[int, int]]] = field(
        default_factory=lambda: [[] for _ in DAY_ORDER]
    )
    day_first_start: list[int | None] = field(
        default_factory=lambda: [None] * len(DAY_ORDER)
    )
    day_last_end: list[int] = field(default_factory=lambda: [0] * len(DAY_ORDER))
    faculty_occ: dict[str, int] = field(default_factory=dict)
    used_days: set[int] = field(default_factory=set)
    assignment: list[Section] = field(default_factory=list)
    lower_bound: float = 0.0

    def clone(self) -> _State:
        return _State(
            occ=self.occ,
            day_counts=list(self.day_counts),
            day_minutes=list(self.day_minutes),
            day_intervals=[list(x) for x in self.day_intervals],
            day_first_start=list(self.day_first_start),
            day_last_end=list(self.day_last_end),
            faculty_occ=dict(self.faculty_occ),
            used_days=set(self.used_days),
            assignment=list(self.assignment),
            lower_bound=self.lower_bound,
        )

    def window_total(self) -> int:
        """Minutes between the first and the last class of every busy day."""
        total = 0
        for day_index in self.used_days:
            first = self.day_first_start[day_index]
            if first is not None:
                total += self.day_last_end[day_index] - first
        return total


# --- The search --------------------------------------------------------------


class _BudgetReached(Exception):
    pass


class _Solver:
    def __init__(
        self,
        courses: list[Course],
        candidates: dict[str, tuple[Section, ...]],
        config: FilterConfig,
        *,
        pool_size: int,
        node_budget: int,
        time_budget: float,
        beam_width: int = 160,
    ) -> None:
        self.config = config
        self.candidates = candidates
        self.pool: list[Routine] = []
        self.pool_limit = pool_size
        self.node_budget = node_budget
        self.deadline = time.perf_counter() + time_budget
        self.nodes = 0
        self.sessions = sum(course.sessions for course in courses)

        # Fewest options first: the tightest course decides the branch.
        self.order: list[str] = sorted(
            candidates, key=lambda key: (len(candidates[key]), key)
        )
        self.courses = {course.key: course for course in courses}

        self.state = _State()
        self._max_classes = config.max_classes_per_day
        self._max_minutes = config.max_minutes_per_day
        self._min_gap = config.min_gap_minutes
        self._restrict_run = config.max_consecutive_days < len(DAY_ORDER)
        self._max_consecutive = config.max_consecutive_days
        self._preferred_global = config.preferred_faculty
        self._pref_mode = config.preference
        self.beam_width = beam_width

        # Cheapest possible contribution of every course that is still unplaced.
        suffix = [0.0] * (len(self.order) + 1)
        sessions_suffix = [0] * (len(self.order) + 1)
        shortest_suffix = [0] * (len(self.order) + 1)
        for index in range(len(self.order) - 1, -1, -1):
            course_key = self.order[index]
            options = self.candidates[course_key]
            suffix[index] = suffix[index + 1] + min(
                (self._class_penalty(c) for c in options), default=0.0
            )
            sessions_suffix[index] = (
                sessions_suffix[index + 1] + self.courses[course_key].sessions
            )
            shortest = min((c.duration for c in options), default=0)
            shortest_suffix[index] = min(shortest_suffix[index + 1], shortest)
        self._min_penalty_remaining = suffix
        self._sessions_remaining = sessions_suffix
        self._shortest_remaining = shortest_suffix

    # -- pool ---------------------------------------------------------------

    def _add(self, routine: Routine) -> None:
        self.pool.append(routine)
        if len(self.pool) > self.pool_limit * 2:
            self.pool.sort(key=lambda r: r.score)
            del self.pool[self.pool_limit :]

    @property
    def _best(self) -> float:
        if not self.pool:
            return math.inf
        return min(r.score for r in self.pool)

    # -- constraint checks ---------------------------------------------------

    def _fits(self, state: _State, section: Section) -> bool:
        if section.mask & state.occ:
            return False
        counts = state.day_counts
        minutes = state.day_minutes
        for day_index, start, end in section.intervals:
            if counts[day_index] + 1 > self._max_classes:
                return False
            if minutes[day_index] + (end - start) > self._max_minutes:
                return False
            if self._min_gap:
                for other_start, other_end in state.day_intervals[day_index]:
                    if other_start >= end:
                        gap = other_start - end
                    elif other_end <= start:
                        gap = start - other_end
                    else:
                        continue
                    if 0 < gap < self._min_gap:
                        return False
        faculty = section.faculty
        if (
            faculty
            and faculty != TBA
            and section.mask & state.faculty_occ.get(faculty, 0)
        ):
            return False
        if (
            len(state.used_days | {d for d, _, _ in section.intervals})
            > self.config.max_days
        ):
            return False
        if self._restrict_run:
            days = state.used_days | {d for d, _, _ in section.intervals}
            if self._longest_run(days) > self._max_consecutive:
                return False
        return True

    @staticmethod
    def _longest_run(days: set[int]) -> int:
        if not days:
            return 0
        best = run = 1
        ordered = sorted(days)
        for previous, current in pairwise(ordered):
            run = run + 1 if current - previous == 1 else 1
            best = max(best, run)
        return best

    def _viable(self, state: _State, course_key: str) -> bool:
        """Forward check: does this course still have a survivable section?"""
        occ = state.occ
        counts = state.day_counts
        minutes = state.day_minutes
        for candidate in self.candidates[course_key]:
            if candidate.mask & occ:
                continue
            ok = True
            for day_index, start, end in candidate.intervals:
                if counts[day_index] + 1 > self._max_classes or (
                    minutes[day_index] + (end - start) > self._max_minutes
                ):
                    ok = False
                    break
            if ok:
                return True
        return False

    # -- placement -----------------------------------------------------------

    def _place(self, state: _State, section: Section) -> None:
        state.occ |= section.mask
        for day_index, start, end in section.intervals:
            state.day_counts[day_index] += 1
            state.day_minutes[day_index] += end - start
            state.day_intervals[day_index].append((start, end))
            first = state.day_first_start[day_index]
            if first is None or start < first:
                state.day_first_start[day_index] = start
            state.day_last_end[day_index] = max(state.day_last_end[day_index], end)
            state.used_days.add(day_index)
        faculty = section.faculty
        if faculty and faculty != TBA:
            state.faculty_occ[faculty] = (
                state.faculty_occ.get(faculty, 0) | section.mask
            )
        state.assignment.append(section)
        state.lower_bound += self._class_penalty(section)

    def _unplace(self, state: _State, section: Section) -> None:
        state.occ &= ~section.mask
        for day_index, start, end in section.intervals:
            state.day_counts[day_index] -= 1
            state.day_minutes[day_index] -= end - start
            state.day_intervals[day_index].remove((start, end))
            if state.day_intervals[day_index]:
                state.day_first_start[day_index] = min(
                    s for s, _ in state.day_intervals[day_index]
                )
                state.day_last_end[day_index] = max(
                    e for _, e in state.day_intervals[day_index]
                )
            else:
                state.day_first_start[day_index] = None
                state.day_last_end[day_index] = 0
        faculty = section.faculty
        if faculty and faculty != TBA:
            state.faculty_occ[faculty] &= ~section.mask
        state.assignment.pop()
        state.lower_bound -= self._class_penalty(section)

    def _class_penalty(self, section: Section) -> float:
        """Per-class part of the score. Monotone, so it is a valid lower bound."""
        config = self.config
        penalty = 0.0
        if section.start < 9 * 60:
            penalty += WEIGHTS["early_class"]
        if section.end > 16 * 60:
            penalty += WEIGHTS["late_class"]
        preferred = self._preferred_global | config.preferred_for(section.course_key)
        if preferred and section.faculty not in preferred:
            penalty += WEIGHTS["faculty_miss"]
        if self._pref_mode == "morning" and section.start >= 12 * 60:
            penalty += WEIGHTS["morning_pref"]
        elif self._pref_mode == "evening" and section.end <= 12 * 60:
            penalty += WEIGHTS["evening_pref"]
        return penalty

    def _state_bound(self, state: _State, depth: int) -> float:
        """Admissible lower bound on the final score of this partial schedule.

        Every term of the score is monotone, so the current value of each term
        is already a lower bound on its final value. The only exception is the
        balance term: more campus days mean a *smaller* target per day, so the
        bound uses the most generous target the final schedule could have.
        """
        ideal = _ideal_days(self.sessions, self.config)
        bound = state.lower_bound

        # Capacity argument: the classes that are still unplaced need room.
        # Busy days only have so much room left, whatever is left over forces
        # at least this many extra campus days.
        days_used = len(state.used_days)
        placed = sum(state.day_counts)
        remaining = self._sessions_remaining[depth] if depth < len(self.order) else 0
        room_left = days_used * self._max_classes - placed
        extra_days = 0
        if remaining > room_left:
            extra_days = math.ceil((remaining - room_left) / max(1, self._max_classes))
        bound += WEIGHTS["extra_day"] * max(0, days_used + extra_days - ideal)

        balanced = _balanced_per_day(self.sessions, days_used)
        bound += WEIGHTS["imbalance"] * sum(
            max(0, count - balanced) for count in state.day_counts
        )
        bound += WEIGHTS["window"] * state.window_total()
        if extra_days:
            bound += WEIGHTS["window"] * extra_days * self._shortest_remaining[depth]

        if depth < len(self.order):
            bound += self._min_penalty_remaining[depth]
        return bound

    # -- recording -----------------------------------------------------------

    def _record(self, state: _State) -> None:
        assignments = sorted(
            state.assignment, key=lambda s: (s.days[0], s.start, s.course_code)
        )
        score, breakdown, metrics = score_routine(
            assignments, self.config, self.sessions
        )
        self._add(
            Routine(
                assignments=assignments,
                score=score,
                breakdown=breakdown,
                metrics=metrics,
            )
        )

    # -- beam pass -----------------------------------------------------------

    def beam_pass(self, width: int) -> None:
        """Quickly gather a strong incumbent set so the DFS can prune hard."""
        beam: list[_State] = [_State()]
        for depth, course_key in enumerate(self.order):
            nxt: list[_State] = []
            for state in beam:
                for candidate in self.candidates[course_key]:
                    if not self._fits(state, candidate):
                        continue
                    child = state.clone()
                    self._place(child, candidate)
                    nxt.append(child)
            if not nxt:
                return
            if len(nxt) > width:
                nxt.sort(key=lambda s: self._beam_key(s, depth))
                nxt = nxt[:width]
            beam = nxt
        for state in beam:
            self._record(state)

    def _beam_key(self, state: _State, depth: int) -> tuple:
        """Rank partial schedules: promising, balanced, and using few days."""
        return (self._state_bound(state, depth), len(state.used_days))

    # -- depth-first pass ----------------------------------------------------

    def search(self) -> tuple[list[Routine], bool]:
        """Beam first (fast, diverse), then a branch-and-bound proof."""
        self.beam_pass(self.beam_width)
        exhaustive = True
        try:
            self._recurse(0)
        except _BudgetReached:
            exhaustive = False
        pool = sorted(self.pool, key=lambda r: r.score)
        return pool[: self.pool_limit], exhaustive

    def _recurse(self, depth: int) -> None:
        self.nodes += 1
        if self.nodes > self.node_budget or time.perf_counter() > self.deadline:
            raise _BudgetReached

        state = self.state
        if depth == len(self.order):
            self._record(state)
            return

        threshold = self._best
        course_key = self.order[depth]
        for candidate in self.candidates[course_key]:
            if not self._fits(state, candidate):
                continue
            self._place(state, candidate)

            if self._state_bound(state, depth) <= threshold and self._forward_check(
                state, depth
            ):
                self._recurse(depth + 1)

            self._unplace(state, candidate)

    def _forward_check(self, state: _State, depth: int) -> bool:
        for remaining in self.order[depth + 1 :]:
            if not self._viable(state, remaining):
                return False
        return True


# --- Diversity ---------------------------------------------------------------


def _similarity(a: Routine, b: Routine) -> float:
    """1.0 means "the same routine", 0.0 means "nothing in common"."""
    sections_a, sections_b = a.section_keys, b.section_keys
    union = len(sections_a | sections_b)
    section_jaccard = len(sections_a & sections_b) / union if union else 1.0

    times_a = {(d, s.start) for s in a.assignments for d in s.days}
    times_b = {(d, s.start) for s in b.assignments for d in s.days}
    union_t = len(times_a | times_b)
    time_jaccard = len(times_a & times_b) / union_t if union_t else 1.0

    return 0.5 * section_jaccard + 0.5 * time_jaccard


def select_diverse(routines: list[Routine], count: int) -> list[Routine]:
    """Pick `count` routines that are good *and* meaningfully different."""
    if not routines:
        return []
    ranked = sorted(routines, key=lambda r: r.score)
    chosen = [ranked[0]]
    remaining = ranked[1:]
    while remaining and len(chosen) < count:
        best_index = 0
        best_value = None
        for index, candidate in enumerate(remaining):
            closeness = max(_similarity(candidate, picked) for picked in chosen)
            value = candidate.score + DIVERSITY_WEIGHT * closeness
            if best_value is None or value < best_value:
                best_value = value
                best_index = index
        chosen.append(remaining.pop(best_index))
    return chosen


# --- Public API --------------------------------------------------------------


def solve(
    courses: list[Course],
    sections: list[Section],
    config: FilterConfig,
    *,
    max_routines: int = 6,
    pool_size: int = 240,
    node_budget: int = 400_000,
    time_budget: float = 4.0,
    beam_width: int = 160,
) -> SolveResult:
    """Return the best conflict-free routines for the requested courses."""
    started = time.perf_counter()
    candidates, empty = build_candidates(courses, sections, config)
    notes: list[str] = []

    if empty:
        notes.append(
            "No sections left for: "
            + "; ".join(empty)
            + ". Those courses were skipped."
        )
    if not candidates:
        return SolveResult(
            routines=[],
            exhaustive=True,
            nodes=0,
            elapsed=time.perf_counter() - started,
            pool_size=0,
            candidate_counts={},
            notes=notes,
        )

    solver = _Solver(
        courses,
        candidates,
        config,
        pool_size=pool_size,
        node_budget=node_budget,
        time_budget=time_budget,
        beam_width=beam_width,
    )
    solver.beam_pass(beam_width)
    found, exhaustive = solver.search()
    selected = select_diverse(found, max_routines)

    if not exhaustive:
        notes.append(
            "The search hit its budget, so these are the best routines found "
            "rather than a proven optimum. Loosen a filter or pick fewer "
            "courses to get a guaranteed optimum."
        )
    if not selected:
        notes.append(
            "No conflict-free combination exists for these courses and filters."
        )

    return SolveResult(
        routines=selected,
        exhaustive=exhaustive,
        nodes=solver.nodes,
        elapsed=time.perf_counter() - started,
        pool_size=len(found),
        candidate_counts={key: len(value) for key, value in candidates.items()},
        notes=notes,
    )


def verify_routine(routine: Routine) -> list[str]:
    """Re-check a produced routine independently of the search."""
    problems: list[str] = []
    for day_index, day in enumerate(DAY_ORDER):
        blocks = sorted(
            (s.start, s.end, s.label)
            for s in routine.assignments
            for d, start, end in s.intervals
            if d == day_index
        )
        for (start_a, end_a, label_a), (start_b, end_b, label_b) in pairwise(blocks):
            if start_b < end_a:
                problems.append(f"{label_a} overlaps {label_b} on {day}.")
    return problems
