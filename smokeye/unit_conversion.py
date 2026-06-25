"""Unit conversion helpers for CALPUFF/reference raster comparison."""

from __future__ import annotations

from typing import Optional

import numpy as np


def finite_stats(values: np.ndarray) -> dict:
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
    }


def apply_linear_conversion(values: np.ndarray, scale: float = 1.0, offset: float = 0.0) -> np.ndarray:
    return np.asarray(values, dtype=np.float32) * np.float32(scale) + np.float32(offset)


def unit_report(
    raw_calpuff: np.ndarray,
    converted_calpuff: np.ndarray,
    model: np.ndarray,
    raw_satellite: Optional[np.ndarray],
    converted_satellite: Optional[np.ndarray],
    *,
    calpuff_unit: str,
    satellite_unit: str,
    target_unit: str,
    calpuff_scale: float,
    calpuff_offset: float,
    satellite_scale: float,
    satellite_offset: float,
    background: float,
) -> dict:
    return {
        "calpuff_unit": calpuff_unit,
        "satellite_unit": satellite_unit,
        "target_unit": target_unit,
        "calpuff_scale": calpuff_scale,
        "calpuff_offset": calpuff_offset,
        "satellite_scale": satellite_scale,
        "satellite_offset": satellite_offset,
        "background": background,
        "formula": "model = raw_CALPUFF * calpuff_scale + calpuff_offset + background; satellite = raw_satellite * satellite_scale + satellite_offset",
        "raw_calpuff_stats": finite_stats(raw_calpuff),
        "converted_calpuff_before_background_stats": finite_stats(converted_calpuff),
        "model_after_background_stats": finite_stats(model),
        "raw_satellite_stats": finite_stats(raw_satellite) if raw_satellite is not None else None,
        "converted_satellite_stats": finite_stats(converted_satellite) if converted_satellite is not None else None,
    }
