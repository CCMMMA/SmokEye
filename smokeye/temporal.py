"""Temporal consistency helpers shared by SmokEye workflows."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Tuple


COMMON_START_TAGS = (
    "time_start",
    "start_time",
    "datetime_start",
    "valid_time_start",
    "sensing_time_start",
    "sensing_start",
    "time_coverage_start",
    "acquisition_start",
)
COMMON_END_TAGS = (
    "time_end",
    "end_time",
    "datetime_end",
    "valid_time_end",
    "sensing_time_end",
    "sensing_end",
    "time_coverage_end",
    "acquisition_end",
)
COMMON_INSTANT_TAGS = (
    "datetime",
    "time",
    "valid_time",
    "sensing_time",
    "timestamp",
    "acquisition_time",
)


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def validate_window(
    start: Optional[datetime],
    end: Optional[datetime],
    label: str,
    *,
    allow_instant: bool = False,
) -> None:
    if (start is None) != (end is None):
        raise ValueError(f"{label}: start and end must be supplied together")
    if start is None or end is None:
        return
    if allow_instant and end == start:
        return
    if end <= start:
        raise ValueError(f"{label}: end must be after start")


def expand_instant(
    start: Optional[datetime],
    end: Optional[datetime],
    duration_minutes: Optional[float],
) -> tuple[Optional[datetime], Optional[datetime]]:
    if start is None or end is None or start != end:
        return start, end
    if duration_minutes is None:
        return start, end
    if duration_minutes <= 0:
        raise ValueError("satellite instant duration must be positive")
    half = timedelta(minutes=duration_minutes / 2.0)
    return start - half, end + half


def overlap_seconds(
    a_start: Optional[datetime],
    a_end: Optional[datetime],
    b_start: Optional[datetime],
    b_end: Optional[datetime],
) -> float:
    if None in (a_start, a_end, b_start, b_end):
        return 0.0
    start = max(a_start, b_start)  # type: ignore[arg-type]
    end = min(a_end, b_end)  # type: ignore[arg-type]
    return max(0.0, (end - start).total_seconds())


def discover_time_from_tags(
    tag_sets: Iterable[dict],
    instant_duration_minutes: Optional[float],
) -> tuple[Optional[datetime], Optional[datetime], str]:
    """Try common GeoTIFF tag names for start/end or instant timestamps."""
    tags = {}
    for group in tag_sets:
        tags.update({str(k).lower(): v for k, v in group.items()})
    start = next((parse_datetime(tags[k]) for k in COMMON_START_TAGS if k in tags), None)
    end = next((parse_datetime(tags[k]) for k in COMMON_END_TAGS if k in tags), None)
    if start is not None or end is not None:
        validate_window(start, end, "GeoTIFF time")
        return start, end, "geotiff_metadata"

    for key in COMMON_INSTANT_TAGS:
        if key in tags:
            instant = parse_datetime(tags[key])
            if instant is None:
                continue
            start, end = expand_instant(instant, instant, instant_duration_minutes)
            return start, end, "geotiff_metadata"

    # Last resort: parse ISO-like stamp from filename-like metadata if present.
    for key, value in tags.items():
        m = re.search(r"(20\d{2}-?\d{2}-?\d{2})[T_ -]?(\d{2}:?\d{2}:?\d{2})", str(value))
        if m:
            date = m.group(1).replace("-", "")
            time = m.group(2).replace(":", "")
            instant = datetime.strptime(date + time, "%Y%m%d%H%M%S")
            start, end = expand_instant(instant, instant, instant_duration_minutes)
            return start, end, "geotiff_metadata"

    return None, None, "missing"


def time_check_report(
    cal_start: Optional[datetime],
    cal_end: Optional[datetime],
    sat_start: Optional[datetime],
    sat_end: Optional[datetime],
    satellite_time_source: str,
    *,
    policy: str = "strict",
    min_fraction: float = 0.95,
    allow_untimed_satellite: bool = False,
) -> dict:
    validate_window(cal_start, cal_end, "CALPUFF comparison time")
    validate_window(sat_start, sat_end, "satellite time", allow_instant=True)

    report = {
        "satellite_time_source": satellite_time_source,
        "satellite_time_start": iso(sat_start),
        "satellite_time_end": iso(sat_end),
        "calpuff_comparison_time_start": iso(cal_start),
        "calpuff_comparison_time_end": iso(cal_end),
        "time_overlap_seconds": None,
        "time_overlap_fraction_of_satellite": None,
        "min_time_overlap_fraction": min_fraction,
        "time_overlap_policy": policy,
        "time_consistency": "unknown",
    }

    if sat_start is None or sat_end is None:
        if policy == "ignore" or allow_untimed_satellite:
            report["time_consistency"] = "ignored"
            return report
        report["time_consistency"] = "failed"
        if policy == "strict":
            raise ValueError("Satellite/reference time is missing; provide --satellite-time-start/--satellite-time-end or --allow-untimed-satellite")
        report["time_consistency"] = "warning"
        return report

    if cal_start is None or cal_end is None:
        report["time_consistency"] = "failed"
        if policy == "strict":
            raise ValueError("CALPUFF comparison time window is required for time-consistent comparison")
        report["time_consistency"] = "warning" if policy == "warn" else "ignored"
        return report

    overlap = overlap_seconds(cal_start, cal_end, sat_start, sat_end)
    sat_duration = max((sat_end - sat_start).total_seconds(), 0.0)
    fraction = overlap / sat_duration if sat_duration > 0 else (1.0 if overlap > 0 else 0.0)
    report["time_overlap_seconds"] = float(overlap)
    report["time_overlap_fraction_of_satellite"] = float(fraction)

    if policy == "ignore":
        report["time_consistency"] = "ignored"
    elif fraction >= min_fraction:
        report["time_consistency"] = "ok"
    elif policy == "strict":
        report["time_consistency"] = "failed"
        raise ValueError(
            f"Time overlap fraction {fraction:.3f} is below required {min_fraction:.3f}"
        )
    else:
        report["time_consistency"] = "warning"
    return report
