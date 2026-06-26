"""CALPUFF gridded-output reader used by SmokEye comparison workflows.

The reader targets CALPUFF concentration/deposition style Fortran-unformatted
binary files where pollutant grids are stored as records containing a species
label, a short level label, and nx * ny 32-bit floating point values.

The implementation is deliberately conservative: it exposes record metadata,
keeps raw values unchanged, and leaves physical unit conversion to the caller.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, List, Optional

import numpy as np

from smokeye.downscaler import orient_grid_array

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalpuffGridRecord:
    """One gridded CALPUFF species/group/time record."""

    species: str
    level: Optional[str]
    group: str
    start: Optional[datetime]
    end: Optional[datetime]
    array: np.ndarray
    record_index: int = 0

    def as_summary(self) -> dict:
        valid = np.isfinite(self.array)
        return {
            "record_index": self.record_index,
            "species": self.species,
            "level": self.level,
            "group": self.group,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "min": float(np.nanmin(self.array)) if valid.any() else None,
            "max": float(np.nanmax(self.array)) if valid.any() else None,
            "mean": float(np.nanmean(self.array)) if valid.any() else None,
        }


def _safe_datetime(year: int, jday: int, hour: int, second: int) -> Optional[datetime]:
    if not (1900 <= year <= 2200 and 1 <= jday <= 366 and 0 <= hour <= 24):
        return None
    try:
        base = datetime(year, 1, 1) + timedelta(days=jday - 1)
        if hour == 24:
            base += timedelta(days=1)
            hour = 0
        return base.replace(hour=hour, minute=0, second=0) + timedelta(seconds=second)
    except ValueError:
        return None


def _detect_fortran_endian(path: Path) -> str:
    with path.open("rb") as f:
        marker = f.read(4)
    if len(marker) != 4:
        raise ValueError(f"{path} is too short to be a Fortran-unformatted file")
    candidates = []
    for endian in (">", "<"):
        n = struct.unpack(endian + "i", marker)[0]
        if 0 < n < 500_000_000:
            candidates.append((endian, n))
    if not candidates:
        raise ValueError(f"Could not detect Fortran record endian format for {path}")
    if len(candidates) > 1:
        logger.warning("Ambiguous Fortran endian detection for %s; using big-endian", path)
        return ">"
    return candidates[0][0]


def iter_fortran_records(path: Path) -> Iterator[bytes]:
    """Yield payloads from a sequential Fortran-unformatted binary file."""
    endian = _detect_fortran_endian(path)
    with path.open("rb") as f:
        while True:
            marker = f.read(4)
            if not marker:
                return
            if len(marker) != 4:
                raise ValueError(f"Truncated Fortran record marker in {path}")
            n = struct.unpack(endian + "i", marker)[0]
            if n <= 0 or n > 500_000_000:
                raise ValueError(f"Implausible Fortran record length {n} in {path}")
            payload = f.read(n)
            trailer = f.read(4)
            if len(payload) != n or len(trailer) != 4:
                raise ValueError(f"Truncated Fortran record in {path}")
            n2 = struct.unpack(endian + "i", trailer)[0]
            if n2 != n:
                raise ValueError(f"Fortran record length mismatch in {path}: {n} != {n2}")
            yield payload


def _looks_like_time_record(payload: bytes, endian: str = ">") -> bool:
    if len(payload) != 32:
        return False
    vals = struct.unpack(endian + "8i", payload)
    start = _safe_datetime(vals[0], vals[1], vals[2], vals[3])
    end = _safe_datetime(vals[4], vals[5], vals[6], vals[7])
    return start is not None and end is not None


def _parse_time_record(payload: bytes, endian: str = ">") -> tuple[Optional[datetime], Optional[datetime]]:
    vals = struct.unpack(endian + "8i", payload)
    return (
        _safe_datetime(vals[0], vals[1], vals[2], vals[3]),
        _safe_datetime(vals[4], vals[5], vals[6], vals[7]),
    )


def _parse_group_record(payload: bytes) -> str:
    # Observed CALPUFF group records are usually int, int, char16, float, float.
    if len(payload) != 32:
        return ""
    return payload[8:24].decode("ascii", errors="ignore").strip()


def read_calpuff_grid_records(
    path: str | Path,
    nx: int,
    ny: int,
    *,
    array_origin: str = "lower",
) -> List[CalpuffGridRecord]:
    """Read gridded CALPUFF records and return arrays in raster row order.

    Parameters
    ----------
    path:
        CALPUFF `.con`, `.dry`, `.wet`, or compatible output file.
    nx, ny:
        Target grid dimensions from GEO.DAT.
    array_origin:
        Source row order. Use `lower` for south-to-north CALPUFF/CALMET order,
        which is flipped to north-up raster row order. Use `upper` if the file is
        already north-to-south.
    """
    path = Path(path)
    endian = _detect_fortran_endian(path)
    expected_bytes = nx * ny * 4
    current_start: Optional[datetime] = None
    current_end: Optional[datetime] = None
    current_group = "UNKNOWN"
    records: List[CalpuffGridRecord] = []

    for record_index, payload in enumerate(iter_fortran_records(path)):
        if _looks_like_time_record(payload, endian):
            current_start, current_end = _parse_time_record(payload, endian)
            current_group = "UNKNOWN"
            continue

        group = _parse_group_record(payload)
        if group:
            current_group = group
            continue

        if len(payload) == 15 + expected_bytes:
            species = payload[:12].decode("ascii", errors="ignore").strip()
            level = payload[12:15].decode("ascii", errors="ignore").strip()
            values = np.frombuffer(payload[15:], dtype=endian + "f4").astype(np.float32, copy=True)
            array = orient_grid_array(values, nx, ny, array_origin, dtype=np.float32)
            records.append(
                CalpuffGridRecord(
                    species=species,
                    level=level,
                    group=current_group,
                    start=current_start,
                    end=current_end,
                    array=array,
                    record_index=record_index,
                )
            )

    if not records:
        raise ValueError(f"No gridded CALPUFF records matching GEO.DAT shape {(ny, nx)} were found in {path}")
    return records


def summarize_records(records: List[CalpuffGridRecord]) -> list[dict]:
    return [record.as_summary() for record in records]
