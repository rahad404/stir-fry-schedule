"""Core logic for the routine maker: data loading, solving, exporting."""

from .data import (
    build_from_frames,
    course_catalog,
    find_csv_files,
    load_routine_data,
    normalize,
    read_tables,
    to_sections,
)
from .export import (
    grid_frame,
    grid_html,
    grid_markdown,
    routine_csv,
    routines_csv,
    routines_excel,
    score_breakdown_frame,
)
from .model import (
    DAY_ORDER,
    Course,
    Feasibility,
    FilterConfig,
    Routine,
    Section,
    SolveResult,
    format_clock,
    parse_clock,
)
from .solver import (
    build_candidates,
    check_feasibility,
    score_routine,
    solve,
    verify_routine,
)

__all__ = [
    "DAY_ORDER",
    "Course",
    "Feasibility",
    "FilterConfig",
    "Routine",
    "Section",
    "SolveResult",
    "build_candidates",
    "build_from_frames",
    "check_feasibility",
    "course_catalog",
    "find_csv_files",
    "format_clock",
    "grid_frame",
    "grid_html",
    "grid_markdown",
    "load_routine_data",
    "normalize",
    "parse_clock",
    "read_tables",
    "routine_csv",
    "routines_csv",
    "routines_excel",
    "score_breakdown_frame",
    "score_routine",
    "solve",
    "to_sections",
    "verify_routine",
]
