#!/usr/bin/env python3
"""
AI-based variant of downscale_pollutant_geodat_calmet.py.

This script intentionally keeps the same command-line interface and output
contract as the deterministic downscaler. It reuses the same GEO.DAT, CALMET,
ground-truth, conservative allocation, validation, and raster-writing code, but
replaces the handcrafted dynamic-weight builder with a compact deterministic
machine-learning model.

The model is an Extreme Learning Machine-style regressor: a fixed random hidden
feature layer is fitted by ridge regression to a physically informed teacher
field. When station data is supplied, the existing station-correction workflow is
still applied after the AI weight field, so reports and comparison products stay
directly comparable with the original method.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
from scipy.ndimage import gaussian_filter

import downscale_pollutant_geodat_calmet as baseline

_ORIGINAL_BUILD_WEIGHTS = baseline.build_weights
_ORIGINAL_WRITE_POLLUTANT_RASTER = baseline.write_pollutant_raster
_ORIGINAL_WRITE_WEIGHT_RASTER = baseline.write_weight_raster


def _finite_fill(arr: np.ndarray, fallback: float = 0.0) -> np.ndarray:
    a = np.asarray(arr, dtype=float)
    if np.isfinite(a).any():
        fill = float(np.nanmedian(a[np.isfinite(a)]))
    else:
        fill = float(fallback)
    return np.where(np.isfinite(a), a, fill)


def _standardize_feature(arr: np.ndarray) -> np.ndarray:
    scaled = baseline.robust01(_finite_fill(arr))
    return (scaled - 0.5) * 2.0


def _feature_stack(grid: baseline.GeoGrid, met: Dict[str, np.ndarray]) -> Tuple[np.ndarray, List[str]]:
    rows = np.linspace(-1.0, 1.0, grid.ny, dtype=float)[:, None]
    cols = np.linspace(-1.0, 1.0, grid.nx, dtype=float)[None, :]
    yy = np.repeat(rows, grid.nx, axis=1)
    xx = np.repeat(cols, grid.ny, axis=0)

    features: List[np.ndarray] = [
        xx,
        yy,
        xx * yy,
        xx * xx,
        yy * yy,
    ]
    names = ["x", "y", "xy", "x2", "y2"]

    elev = grid.elevation if grid.elevation is not None else met.get("elevation_calmet")
    if elev is not None:
        features.append(_standardize_feature(elev))
        names.append("elevation")

    if grid.landuse is not None:
        lu = _finite_fill(grid.landuse)
        features.append(_standardize_feature(lu))
        names.append("landuse_code")
        for cls in sorted(int(v) for v in np.unique(lu[np.isfinite(lu)]))[:24]:
            features.append((lu == cls).astype(float))
            names.append(f"landuse_{cls}")

    for key in sorted(met):
        if key == "elevation_calmet" and elev is not None:
            continue
        arr = met[key]
        if arr.shape == (grid.ny, grid.nx):
            features.append(_standardize_feature(arr))
            names.append(key)

    cube = np.stack(features, axis=-1)
    return cube.reshape((-1, cube.shape[-1])), names


def _ridge_fit(hidden: np.ndarray, target: np.ndarray, alpha: float) -> np.ndarray:
    lhs = hidden.T @ hidden
    lhs.flat[:: lhs.shape[0] + 1] += alpha
    rhs = hidden.T @ target
    return np.linalg.solve(lhs, rhs)


def build_ai_weights(grid: baseline.GeoGrid, met: Dict[str, np.ndarray], min_weight: float = 0.05) -> np.ndarray:
    """
    Build a positive fine-grid weight field with a small deterministic ML model.

    The original dynamic model is used only to generate a physically meaningful
    training signal from the same inputs. The fitted nonlinear model then
    generalizes that signal through terrain, land-use, meteorology, and grid
    position features, producing an alternate AI-derived allocation surface.
    """
    x, feature_names = _feature_stack(grid, met)
    teacher = _ORIGINAL_BUILD_WEIGHTS(grid, met, min_weight=min_weight).reshape(-1)
    valid = np.isfinite(teacher) & (teacher > 0) & np.all(np.isfinite(x), axis=1)
    if valid.sum() < max(10, x.shape[1] + 2):
        return np.maximum(np.ones((grid.ny, grid.nx), dtype=float), min_weight)

    rng = np.random.default_rng(42)
    hidden_width = min(96, max(24, x.shape[1] * 4))
    w_in = rng.normal(0.0, 0.85, size=(x.shape[1], hidden_width))
    b_in = rng.normal(0.0, 0.35, size=(hidden_width,))
    hidden = np.tanh(x @ w_in + b_in)
    hidden = np.concatenate([np.ones((hidden.shape[0], 1)), x, hidden], axis=1)

    y = np.log(np.clip(teacher, min_weight, None))
    coef = _ridge_fit(hidden[valid], y[valid], alpha=1.0e-2)
    pred = np.exp(hidden @ coef).reshape((grid.ny, grid.nx))

    # Keep the learned field smooth enough for allocation while preserving local
    # structure expressed by the learned nonlinear features.
    sigma_cells = max(0.5, min(3.0, 600.0 / float(max(grid.dx, grid.dy))))
    smooth = gaussian_filter(pred, sigma=sigma_cells, mode="nearest")
    learned = 0.75 * pred + 0.25 * smooth
    learned = np.where(np.isfinite(learned), learned, np.nanmedian(teacher))
    learned = np.maximum(learned, min_weight)

    median = float(np.nanmedian(learned))
    if np.isfinite(median) and median > 0:
        learned = learned / median
    learned = np.clip(learned, min_weight, 20.0)

    # Expose a tiny breadcrumb in stdout without changing the CLI or outputs.
    print(
        "AI weight model:",
        f"features={len(feature_names)}",
        f"hidden={hidden_width}",
        f"training_cells={int(valid.sum())}",
    )
    return learned


def write_ai_pollutant_raster(*args, **kwargs) -> None:
    tags = dict(kwargs.pop("tags", None) or {})
    tags.update(
        {
            "method": "ai_conservative_dynamic_downscaling",
            "ai_model": "deterministic_extreme_learning_machine_ridge",
        }
    )
    kwargs["tags"] = tags
    _ORIGINAL_WRITE_POLLUTANT_RASTER(*args, **kwargs)


def write_ai_weight_raster(path, grid, weights) -> None:
    _ORIGINAL_WRITE_WEIGHT_RASTER(path, grid, weights)


def main() -> None:
    baseline.build_weights = build_ai_weights
    baseline.write_pollutant_raster = write_ai_pollutant_raster
    baseline.write_weight_raster = write_ai_weight_raster
    baseline.main()


if __name__ == "__main__":
    main()
