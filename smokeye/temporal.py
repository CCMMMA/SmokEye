"""Temporal parsing, aggregation, and consistency checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Tuple


COMMON_START_TAGS = (
    "time_start",
    "start_time",
    "datetime_start",
    "sensing_start",
    "time_coverage_start",
    "acquisition_start",
    "valid_time_start",
)
COMMON_END_TAGS = (
    "time_end",
    "end_time",
    "datetime_end",
    "sensing_end",
    "time_coverage_end",
    "acquisition_end",
    "valid_time_end",
)
COMMON_INSTANT_TAGS = ("datetime", "time", "timestamp", "acquisition_time", "sensing_time")


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def validate_window(start: Optional[datetime], end: Optional[datetime], label: str, allow_instant: bool = False) -> None:
    if (start is None) != (end is None):
        raise ValueError(f"{label} start and end must be supplied together")
    if start is None or end is None:
        return
    if allow_instant and end == start:
        return
    if end <= start:
        raise ValueError(f"{label} end must be greater than start")


def expand_instant(start: datetime, end: datetime, duration_minutes: Optional[float]) -> Tuple[datetime, datetime]:
    if start != end or duration_minutes is None:
        return start, end
    half = timedelta(minutes=float(duration_minutes) / 2.0)
    return start - half, end + half


def overlap_seconds(a_start: Optional[datetime], a_end: Optional[datetime], b_start: Optional[datetime], b_end: Optional[datetime]) -> float:
    if None in (a_start, a_end, b_start, b_end):
        return 0.0
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return max(0.0, (end - start).total_seconds())


def discover_time_from_tags(tag_sets: Iterable[dict], instant_duration_minutes: Optional[float]) -> Tuple[Optional[datetime], Optional[datetime], str]:
    tags = {}
    for tag_set in tag_sets:
        tags.update({str(k).lower(): v for k, v in tag_set.items()})
    start = next((parse_datetime(tags[k]) for k in COMMON_START_TAGS if k in tags), None)
    end = next((parse_datetime(tags[k]) for k in COMMON_END_TAGS if k in tags), None)
    if start is not None or end is not None:
        validate_window(start, end, "satellite time", allow_instant=True)
        if start is not None and end is not None:
            start, end = expand_instant(start, end, instant_duration_minutes)
        return start, end, "geotiff_metadata"
    instant = next((parse_datetime(tags[k]) for k in COMMON_INSTANT_TAGS if k in tags), None)
    if instant is None:
        return None, None, "missing"
    if instant_duration_minutes is None:
        return instant, instant, "geotiff_metadata"
    start, end = expand_instant(instant, instant, instant_duration_minutes)
    return start, end, "geotiff_metadata"


def time_check_report(
    calpuff_start: Optional[datetime],
    calpuff_end: Optional[datetime],
    satellite_start: Optional[datetime],
    satellite_end: Optional[datetime],
    source: str,
    *,
    policy: str,
    min_fraction: float,
    allow_untimed_satellite: bool,
) -> dict:
    missing_sat = satellite_start is None or satellite_end is None
    if missing_sat:
        status = "ok" if allow_untimed_satellite else "failed"
        if policy == "ignore":
            status = "ignored"
        elif policy == "warn" and not allow_untimed_satellite:
            status = "warning"
        report = {
            "satellite_time_source": source,
            "satellite_time_start": None,
            "satellite_time_end": None,
            "calpuff_comparison_time_start": iso(calpuff_start),
            "calpuff_comparison_time_end": iso(calpuff_end),
            "time_overlap_seconds": 0.0,
            "time_overlap_fraction_of_satellite": None,
            "min_time_overlap_fraction": min_fraction,
            "time_consistency": status,
        }
        if status == "failed":
            raise ValueError("Satellite/reference time window is missing; pass times, use --allow-untimed-satellite, or change --time-overlap-policy")
        return report

    overlap = overlap_seconds(calpuff_start, calpuff_end, satellite_start, satellite_end)
    sat_duration = max(0.0, (satellite_end - satellite_start).total_seconds())
    fraction = 1.0 if sat_duration == 0.0 and overlap == 0.0 and calpuff_start == satellite_start else (overlap / sat_duration if sat_duration > 0.0 else 0.0)
    ok = fraction >= min_fraction
    status = "ok" if ok else "failed"
    if policy == "ignore":
        status = "ignored"
    elif policy == "warn" and not ok:
        status = "warning"
    report = {
        "satellite_time_source": source,
        "satellite_time_start": iso(satellite_start),
        "satellite_time_end": iso(satellite_end),
        "calpuff_comparison_time_start": iso(calpuff_start),
        "calpuff_comparison_time_end": iso(calpuff_end),
        "time_overlap_seconds": overlap,
        "time_overlap_fraction_of_satellite": fraction,
        "min_time_overlap_fraction": min_fraction,
        "time_consistency": status,
    }
    if status == "failed":
        raise ValueError(f"CALPUFF/reference time overlap fraction {fraction:.3f} is below required {min_fraction:.3f}")
    return report
