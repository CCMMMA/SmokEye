"""Unit-conversion helpers for SmokEye comparison workflows."""

from __future__ import annotations

import numpy as np


def apply_linear_conversion(values: np.ndarray, scale: float = 1.0, offset: float = 0.0) -> np.ndarray:
    """Apply an explicit linear conversion without guessing physical units."""
    return (values.astype(np.float32) * np.float32(scale) + np.float32(offset)).astype(np.float32)


def array_stats(values: np.ndarray) -> dict:
    valid = np.isfinite(values)
    if not valid.any():
        return {"min": None, "max": None, "mean": None, "std": None}
    data = values[valid].astype(float)
    return {
        "min": float(np.min(data)),
        "max": float(np.max(data)),
        "mean": float(np.mean(data)),
        "std": float(np.std(data)),
    }


def unit_report(
    raw_calpuff: np.ndarray,
    converted_calpuff: np.ndarray,
    model_after_background: np.ndarray,
    raw_satellite: np.ndarray,
    converted_satellite: np.ndarray,
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
        "formula": (
            "model = raw_CALPUFF * calpuff_scale + calpuff_offset + background; "
            "satellite = raw_satellite * satellite_scale + satellite_offset"
        ),
        "raw_calpuff_stats": array_stats(raw_calpuff),
        "converted_calpuff_before_background_stats": array_stats(converted_calpuff),
        "model_after_background_stats": array_stats(model_after_background),
        "raw_satellite_stats": array_stats(raw_satellite),
        "converted_satellite_stats": array_stats(converted_satellite),
        "note": (
            "SmokEye does not infer physical conversions between concentration, deposition, "
            "mixing-ratio, and column products. Scale/offset values must be provided by the user."
        ),
    }
