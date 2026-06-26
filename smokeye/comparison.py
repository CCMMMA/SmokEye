"""CALPUFF-to-reference GeoTIFF comparison workflow."""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from smokeye.calpuff_reader import CalpuffGridRecord, read_calpuff_grid_records, summarize_records
from smokeye.downscaler import GeoDATReader
from smokeye.temporal import discover_time_from_tags, expand_instant, overlap_seconds, parse_datetime, time_check_report, validate_window
from smokeye.unit_conversion import apply_linear_conversion, unit_report
from smokeye.logging_utils import configure_cli_logging


logger = logging.getLogger(__name__)


SCIENTIFIC_CAVEATS = [
    "Grid alignment does not make two products physically equivalent.",
    "CALPUFF near-surface concentration and satellite column products require documented unit/physics conversion before comparison.",
    "Background levels must be chosen from measurements, product metadata, or a documented assumption.",
    "Temporal mismatch can dominate apparent model/satellite differences.",
    "Deposition outputs (.dry, .wet) may have different physical units and should not be compared to concentration or column products without explicit conversion.",
]


def add_compare_calpuff_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--calpuff", type=Path, required=True)
    parser.add_argument("--geo", type=Path, required=True)
    parser.add_argument("--satellite", type=Path, default=None)
    parser.add_argument("--satellite-band", type=int, default=1)
    parser.add_argument("--species", default="NO2")
    parser.add_argument("--group", default="TOTAL")
    parser.add_argument("--level", default=None)
    parser.add_argument("--list-records", action="store_true")
    parser.add_argument("--time-start", default=None)
    parser.add_argument("--time-end", default=None)
    parser.add_argument("--satellite-time-start", default=None)
    parser.add_argument("--satellite-time-end", default=None)
    parser.add_argument("--satellite-instant-duration-minutes", type=float, default=None)
    parser.add_argument("--time-overlap-policy", choices=["strict", "warn", "ignore"], default="strict")
    parser.add_argument("--min-time-overlap-fraction", type=float, default=0.95)
    parser.add_argument("--allow-untimed-satellite", action="store_true")
    parser.add_argument("--time-agg", choices=["mean", "sum", "first", "last", "max"], default="mean")
    parser.add_argument("--time-selection", choices=["overlap", "closest"], default="closest", help="Select overlapping CALPUFF records, or the closest available record when no overlap exists. Defaults to closest.")
    parser.add_argument("--max-closest-time-delta-minutes", type=float, default=60.0, help="Maximum allowed midpoint delta when --time-selection closest is used. Use a negative value to disable the limit.")
    parser.add_argument("--calpuff-unit", default="ug_m3")
    parser.add_argument("--calpuff-scale", type=float, default=1.0)
    parser.add_argument("--calpuff-offset", type=float, default=0.0)
    parser.add_argument("--satellite-unit", default="ug_m3")
    parser.add_argument("--satellite-scale", type=float, default=1.0)
    parser.add_argument("--satellite-offset", type=float, default=0.0)
    parser.add_argument("--target-unit", default="ug_m3")
    parser.add_argument("--background", type=float, default=0.0)
    parser.add_argument("--array-origin", choices=["lower", "upper"], default="lower")
    parser.add_argument("--resampling", choices=["nearest", "bilinear", "average"], default="bilinear")
    parser.add_argument("--out-prefix", type=Path, default=None)


def _filter_records(records: List[CalpuffGridRecord], species: str, group: str, level: Optional[str]) -> List[CalpuffGridRecord]:
    selected = [r for r in records if r.species.upper() == species.upper() and r.group.upper() == group.upper()]
    if level is not None:
        selected = [r for r in selected if (r.level or "").upper() == level.upper()]
    if not selected:
        raise ValueError(f"No CALPUFF records matched species={species!r}, group={group!r}, level={level!r}")
    return selected


def _midpoint(start: Optional[datetime], end: Optional[datetime]) -> Optional[datetime]:
    if start is None or end is None:
        return None
    return start + (end - start) / 2


def _record_midpoint(record: CalpuffGridRecord) -> Optional[datetime]:
    return _midpoint(record.start, record.end)


def select_records_for_window(records: List[CalpuffGridRecord], start, end, time_selection: str, max_closest_delta_seconds: Optional[float] = 3600.0) -> Tuple[List[CalpuffGridRecord], np.ndarray, dict]:
    validate_window(start, end, "CALPUFF comparison time")
    overlaps = np.array([overlap_seconds(start, end, r.start, r.end) if r.start and r.end else 0.0 for r in records], dtype=float)
    timed = overlaps > 0.0
    if not timed.any() and all(r.start is None or r.end is None for r in records):
        chosen = list(records)
        return chosen, np.ones(len(chosen), dtype=float), {
            "time_selection": "untimed",
            "time_selection_rule": "all selected records have no usable timestamps; records were aggregated in file order",
            "selected_record_count": len(chosen),
            "selected_record_times": [_record_time_dict(r, None) for r in chosen],
        }
    if not timed.any():
        if time_selection != "closest":
            raise ValueError("No selected CALPUFF records overlap the requested comparison window")
        requested_mid = _midpoint(start, end)
        distances = []
        for index, record in enumerate(records):
            record_mid = _record_midpoint(record)
            if requested_mid is None or record_mid is None:
                distances.append((float("inf"), index))
            else:
                distances.append((abs((record_mid - requested_mid).total_seconds()), index))
        distance, index = min(distances, key=lambda item: (item[0], item[1]))
        if not np.isfinite(distance):
            raise ValueError("No selected CALPUFF records overlap the requested comparison window and no closest timestamp can be determined")
        if max_closest_delta_seconds is not None and distance > max_closest_delta_seconds:
            raise ValueError(
                f"Closest CALPUFF record midpoint is {distance:.0f} seconds from the requested window midpoint, "
                f"exceeding the allowed {max_closest_delta_seconds:.0f} seconds"
            )
        chosen = [records[index]]
        return chosen, np.ones(1, dtype=float), {
            "time_selection": "closest",
            "time_selection_rule": "no overlapping CALPUFF record was available; selected the record with the nearest midpoint timestamp, breaking ties by file order",
            "closest_time_delta_seconds": float(distance),
            "max_closest_time_delta_seconds": max_closest_delta_seconds,
            "selected_record_count": 1,
            "selected_record_times": [_record_time_dict(chosen[0], float(distance))],
        }
    chosen = [r for r, keep in zip(records, timed) if keep]
    weights = overlaps[timed]
    return chosen, weights, {
        "time_selection": "overlap",
        "time_selection_rule": "selected CALPUFF records with positive overlap against the requested comparison window",
        "selected_record_count": len(chosen),
        "selected_record_times": [_record_time_dict(r, float(w)) for r, w in zip(chosen, weights)],
    }


def _record_time_dict(record: CalpuffGridRecord, metric: Optional[float]) -> dict:
    row = {
        "species": record.species,
        "group": record.group,
        "level": record.level,
        "start": record.start.isoformat() if record.start else None,
        "end": record.end.isoformat() if record.end else None,
    }
    if metric is not None:
        row["overlap_or_delta_seconds"] = metric
    return row


def aggregate_selected_records(chosen: List[CalpuffGridRecord], weights: np.ndarray, method: str) -> np.ndarray:
    if method == "first":
        return chosen[0].array.astype(np.float32)
    if method == "last":
        return chosen[-1].array.astype(np.float32)
    stack = np.stack([r.array.astype(np.float32) for r in chosen])
    if method == "max":
        return np.nanmax(stack, axis=0).astype(np.float32)
    if method == "sum":
        durations = np.array([(r.end - r.start).total_seconds() if r.start and r.end else 1.0 for r in chosen], dtype=float)
        frac = np.divide(weights, durations, out=np.ones_like(weights), where=durations > 0.0)
        return np.nansum(stack * frac[:, None, None], axis=0).astype(np.float32)
    weights = np.where(weights > 0.0, weights, 1.0)
    return np.average(stack, axis=0, weights=weights).astype(np.float32)


def aggregate_records(records: List[CalpuffGridRecord], start, end, method: str, time_selection: str = "closest", max_closest_delta_seconds: Optional[float] = 3600.0) -> np.ndarray:
    chosen, weights, _ = select_records_for_window(records, start, end, time_selection, max_closest_delta_seconds)
    return aggregate_selected_records(chosen, weights, method)


def _stats(model: np.ndarray, satellite: np.ndarray) -> dict:
    valid = np.isfinite(model) & np.isfinite(satellite)
    if not valid.any():
        return {"n_valid": 0}
    m = model[valid].astype(float)
    s = satellite[valid].astype(float)
    diff = m - s
    ratio = np.divide(m, s, out=np.full_like(m, np.nan), where=s != 0.0)
    finite_ratio = ratio[np.isfinite(ratio)]
    corr = np.corrcoef(m, s)[0, 1] if m.size > 1 and np.std(m) > 0 and np.std(s) > 0 else None
    return {
        "n_valid": int(m.size),
        "model_min": float(np.min(m)),
        "model_max": float(np.max(m)),
        "model_mean": float(np.mean(m)),
        "model_std": float(np.std(m)),
        "satellite_min": float(np.min(s)),
        "satellite_max": float(np.max(s)),
        "satellite_mean": float(np.mean(s)),
        "satellite_std": float(np.std(s)),
        "bias_model_minus_satellite": float(np.mean(diff)),
        "mae": float(np.mean(np.abs(diff))),
        "rmse": float(np.sqrt(np.mean(diff * diff))),
        "correlation": float(corr) if corr is not None and np.isfinite(corr) else None,
        "ratio_mean": float(np.mean(finite_ratio)) if finite_ratio.size else None,
        "ratio_median": float(np.median(finite_ratio)) if finite_ratio.size else None,
    }


def _write_tif(path: Path, profile: dict, arr: np.ndarray, description: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out_profile = profile.copy()
    out_profile.update(driver="GTiff", count=1, dtype="float32", nodata=np.nan, compress="deflate")
    with rasterio.open(path, "w", **out_profile) as dst:
        dst.write(arr.astype(np.float32), 1)
        dst.set_band_description(1, description)


def _write_csv(path: Path, stats: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for key, value in stats.items():
            if isinstance(value, (str, int, float)) or value is None:
                writer.writerow([key, value])


def _out_path(prefix: Path, suffix: str) -> Path:
    return Path(str(prefix) + suffix)


def run_compare_calpuff(args: argparse.Namespace) -> None:
    configure_cli_logging()

    grid = GeoDATReader(args.geo, None, require_projection=True).read()
    records = read_calpuff_grid_records(args.calpuff, grid.nx, grid.ny, array_origin=args.array_origin)
    if args.list_records:
        logger.info(json.dumps(summarize_records(records), indent=2))
        return
    if args.satellite is None:
        raise ValueError("--satellite is required unless --list-records is used")
    if args.out_prefix is None:
        raise ValueError("--out-prefix is required unless --list-records is used")

    cal_start = parse_datetime(args.time_start)
    cal_end = parse_datetime(args.time_end)
    validate_window(cal_start, cal_end, "CALPUFF comparison time")

    selected = _filter_records(records, args.species, args.group, args.level)
    max_closest_delta = None if args.max_closest_time_delta_minutes < 0 else args.max_closest_time_delta_minutes * 60.0
    selected_for_time, time_weights, calpuff_time_selection = select_records_for_window(selected, cal_start, cal_end, args.time_selection, max_closest_delta)
    raw_calpuff = aggregate_selected_records(selected_for_time, time_weights, args.time_agg)
    calpuff_target = apply_linear_conversion(raw_calpuff, args.calpuff_scale, args.calpuff_offset)
    model_native = (calpuff_target + np.float32(args.background)).astype(np.float32)

    resampling = {"nearest": Resampling.nearest, "bilinear": Resampling.bilinear, "average": Resampling.average}[args.resampling]
    with rasterio.open(args.satellite) as src:
        sat_raw = src.read(args.satellite_band).astype(np.float32)
        sat_mask = src.read_masks(args.satellite_band) == 0
        if src.nodata is not None:
            sat_mask |= sat_raw == src.nodata
        sat_raw = np.where(sat_mask, np.nan, sat_raw)
        sat_start = parse_datetime(args.satellite_time_start)
        sat_end = parse_datetime(args.satellite_time_end)
        sat_source = "cli" if sat_start is not None or sat_end is not None else "missing"
        if sat_start is None and sat_end is None:
            sat_start, sat_end, sat_source = discover_time_from_tags((src.tags(), src.tags(args.satellite_band)), args.satellite_instant_duration_minutes)
        else:
            validate_window(sat_start, sat_end, "satellite time", allow_instant=True)
            sat_start, sat_end = expand_instant(sat_start, sat_end, args.satellite_instant_duration_minutes)
        report_time = time_check_report(
            cal_start,
            cal_end,
            sat_start,
            sat_end,
            sat_source,
            policy=args.time_overlap_policy,
            min_fraction=args.min_time_overlap_fraction,
            allow_untimed_satellite=args.allow_untimed_satellite,
        )
        sat_target = apply_linear_conversion(sat_raw, args.satellite_scale, args.satellite_offset)
        target_profile = src.profile.copy()
        target_crs = src.crs
        target_transform = src.transform
        target_shape = sat_target.shape

    model_aligned = np.full(target_shape, np.nan, dtype=np.float32)
    reproject(
        source=model_native,
        destination=model_aligned,
        src_transform=grid.transform,
        src_crs=grid.crs,
        src_nodata=np.nan,
        dst_transform=target_transform,
        dst_crs=target_crs,
        dst_nodata=np.nan,
        resampling=resampling,
    )
    model_aligned = np.where(np.isfinite(sat_target), model_aligned, np.nan).astype(np.float32)
    sat_target = sat_target.astype(np.float32)
    difference = (model_aligned - sat_target).astype(np.float32)
    ratio = np.divide(model_aligned, sat_target, out=np.full_like(model_aligned, np.nan), where=np.isfinite(sat_target) & (sat_target != 0.0)).astype(np.float32)
    stats = _stats(model_aligned, sat_target)

    prefix = Path(args.out_prefix)
    _write_tif(_out_path(prefix, ".model.tif"), target_profile, model_aligned, "CALPUFF converted plus background aligned to reference")
    _write_tif(_out_path(prefix, ".satellite.tif"), target_profile, sat_target, "Converted satellite/reference raster")
    _write_tif(_out_path(prefix, ".difference.tif"), target_profile, difference, "Model minus satellite/reference")
    _write_tif(_out_path(prefix, ".ratio.tif"), target_profile, ratio, "Model divided by satellite/reference")

    target_unit = args.target_unit or args.satellite_unit
    report = {
        "calpuff": {"path": str(args.calpuff), "species": args.species, "group": args.group, "level": args.level, "time_aggregation": args.time_agg},
        "calpuff_time_selection": calpuff_time_selection,
        "geo": grid.as_dict(),
        "satellite": {"path": str(args.satellite), "band": args.satellite_band},
        "time_check": report_time,
        "unit_conversion": unit_report(
            raw_calpuff,
            calpuff_target,
            model_native,
            sat_raw,
            sat_target,
            calpuff_unit=args.calpuff_unit,
            satellite_unit=args.satellite_unit,
            target_unit=target_unit,
            calpuff_scale=args.calpuff_scale,
            calpuff_offset=args.calpuff_offset,
            satellite_scale=args.satellite_scale,
            satellite_offset=args.satellite_offset,
            background=args.background,
        ),
        "statistics": stats,
        "notes": SCIENTIFIC_CAVEATS,
    }
    json_path = _out_path(prefix, ".stats.json")
    csv_path = _out_path(prefix, ".stats.csv")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_csv(csv_path, stats)
    logger.info(json.dumps({"outputs": [str(Path(str(prefix) + suffix)) for suffix in (".model.tif", ".satellite.tif", ".difference.tif", ".ratio.tif", ".stats.json", ".stats.csv")], "statistics": stats}, indent=2))
