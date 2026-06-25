"""Heuristic CALPUFF Fortran-unformatted grid record reader."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

import numpy as np

from smokeye.temporal import parse_datetime


@dataclass(frozen=True)
class CalpuffGridRecord:
    species: str
    level: Optional[str]
    group: str
    start: Optional[datetime]
    end: Optional[datetime]
    array: np.ndarray


def _detect_endian(path: Path) -> str:
    with Path(path).open("rb") as f:
        head = f.read(4)
    if len(head) != 4:
        raise ValueError(f"Empty or invalid CALPUFF file: {path}")
    for endian in (">", "<"):
        reclen = struct.unpack(endian + "i", head)[0]
        if 0 < reclen < 500_000_000:
            return endian
    raise ValueError("Could not determine CALPUFF Fortran record endian/order")


def iter_fortran_records(path: Path, max_record_length: int = 500_000_000) -> Iterable[bytes]:
    path = Path(path)
    endian = _detect_endian(path)
    with path.open("rb") as f:
        index = 0
        while True:
            head = f.read(4)
            if len(head) == 0:
                break
            if len(head) != 4:
                raise ValueError(f"Truncated CALPUFF record marker at record {index}")
            reclen = struct.unpack(endian + "i", head)[0]
            if reclen <= 0 or reclen > max_record_length:
                raise ValueError(f"Implausible CALPUFF record length {reclen} at record {index}")
            payload = f.read(reclen)
            tail = f.read(4)
            if len(payload) != reclen or len(tail) != 4:
                raise ValueError(f"Truncated CALPUFF payload at record {index}")
            tail_len = struct.unpack(endian + "i", tail)[0]
            if tail_len != reclen:
                raise ValueError(f"CALPUFF Fortran marker mismatch at record {index}: {reclen} != {tail_len}")
            yield payload
            index += 1


def _ascii_prefix(payload: bytes, array_bytes: int) -> str:
    prefix = payload[:-array_bytes] if len(payload) > array_bytes else payload[: min(len(payload), 512)]
    return prefix.decode("ascii", errors="ignore").replace("\x00", " ")


def _token_after(text: str, keys: tuple[str, ...]) -> Optional[str]:
    for key in keys:
        match = re.search(rf"\b{key}\b\s*[:=]?\s*([A-Za-z0-9_.+\-]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _time_after(text: str, keys: tuple[str, ...]) -> Optional[datetime]:
    for key in keys:
        match = re.search(rf"\b{key}\b\s*[:=]?\s*([0-9]{{4}}[-/][0-9]{{2}}[-/][0-9]{{2}}[T ][0-9:]+(?:Z|[+-][0-9:]+)?)", text, re.IGNORECASE)
        if match:
            value = match.group(1).replace("/", "-").replace(" ", "T")
            try:
                return parse_datetime(value)
            except ValueError:
                continue
    return None


def _infer_metadata(text: str) -> tuple[str, Optional[str], str, Optional[datetime], Optional[datetime]]:
    compact = " ".join(text.split())
    species = _token_after(compact, ("SPECIES", "SPEC", "POLLUTANT")) or "UNKNOWN"
    level = _token_after(compact, ("LEVEL", "LEV"))
    group = _token_after(compact, ("GROUP", "SRCGRP", "SOURCE", "SRC")) or "TOTAL"
    start = _time_after(compact, ("START", "TIME_START", "BEGIN"))
    end = _time_after(compact, ("END", "TIME_END", "STOP"))
    return species.upper(), level, group.upper(), start, end


def _array_from_payload(payload: bytes, nx: int, ny: int, endian: str) -> Optional[np.ndarray]:
    n = nx * ny
    array_bytes = 4 * n
    if len(payload) < array_bytes:
        return None
    raw = payload[-array_bytes:]
    arr = np.frombuffer(raw, dtype=endian + "f4", count=n)
    if arr.size != n:
        return None
    arr = arr.astype(np.float32).reshape((ny, nx))
    if not np.isfinite(arr).any():
        return None
    return arr


def read_calpuff_grid_records(path: Path, nx: int, ny: int, array_origin: str = "lower") -> List[CalpuffGridRecord]:
    path = Path(path)
    endian = _detect_endian(path)
    records: List[CalpuffGridRecord] = []
    array_bytes = 4 * nx * ny
    for payload in iter_fortran_records(path):
        arr = _array_from_payload(payload, nx, ny, endian)
        if arr is None:
            continue
        if array_origin == "lower":
            arr = np.flipud(arr)
        elif array_origin != "upper":
            raise ValueError(f"Unsupported array origin: {array_origin}")
        text = _ascii_prefix(payload, array_bytes)
        species, level, group, start, end = _infer_metadata(text)
        records.append(CalpuffGridRecord(species=species, level=level, group=group, start=start, end=end, array=arr))
    if not records:
        raise ValueError(f"No CALPUFF grid records matching GEO.DAT shape {(ny, nx)} were found in {path}")
    return records


def summarize_records(records: Iterable[CalpuffGridRecord]) -> list[dict]:
    rows = []
    for index, record in enumerate(records):
        arr = record.array.astype(float)
        finite = arr[np.isfinite(arr)]
        rows.append(
            {
                "record": index,
                "species": record.species,
                "level": record.level,
                "group": record.group,
                "start": record.start.isoformat() if record.start else None,
                "end": record.end.isoformat() if record.end else None,
                "min": float(np.min(finite)) if finite.size else None,
                "max": float(np.max(finite)) if finite.size else None,
                "mean": float(np.mean(finite)) if finite.size else None,
            }
        )
    return rows
