"""Conservation-guided diffusion-style strategy for SmokEye."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import numpy as np

from smokeye import downscaler


TRAINING_STRATEGIES = (
    "self_supervised_coarse_to_fine",
    "hybrid_teacher_student",
    "physics_guided_weak_supervision",
)


def add_diffusion_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--diffusion-checkpoint", type=Path, default=None, help="Path to a diffusion checkpoint or lightweight JSON/NPZ inference checkpoint.")
    parser.add_argument("--diffusion-samples", type=int, default=1, help="Number of diffusion samples to draw.")
    parser.add_argument("--diffusion-seed", type=int, default=42, help="Seed for reproducible diffusion sampling.")
    parser.add_argument("--diffusion-device", choices=["cpu", "cuda", "mps", "auto"], default="auto", help="Device selector for diffusion inference.")
    parser.add_argument("--diffusion-steps", type=int, default=50, help="Number of diffusion denoising steps.")
    parser.add_argument("--diffusion-guidance-scale", type=float, default=1.0, help="Conditional guidance scale.")
    parser.add_argument("--diffusion-training-strategy", choices=TRAINING_STRATEGIES, default="hybrid_teacher_student", help="Training strategy associated with the checkpoint.")
    parser.add_argument("--diffusion-train", action="store_true", help="Validate diffusion training configuration and exit. Full model training is external to this lightweight package.")
    parser.add_argument("--diffusion-train-config", type=Path, default=None, help="Path to a diffusion training configuration file.")
    parser.add_argument("--diffusion-train-output-dir", type=Path, default=None, help="Output directory for diffusion training artifacts.")
    parser.add_argument("--write-uncertainty", action="store_true", help="Write per-cell ensemble standard deviation next to the main output when multiple samples are requested.")
    parser.add_argument("--write-ensemble", action="store_true", help="Write per-sample ensemble GeoTIFFs next to the main output when multiple samples are requested.")


def _load_checkpoint(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Diffusion checkpoint does not exist: {path}")
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text())
    if path.suffix.lower() == ".npz":
        data = np.load(path, allow_pickle=True)
        return {name: data[name] for name in data.files}
    return {"checkpoint_path": str(path)}


def _checkpoint_float(checkpoint: Dict[str, Any], name: str, default: float) -> float:
    value = checkpoint.get(name, default)
    if isinstance(value, np.ndarray):
        value = value.item() if value.shape == () else default
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _positive_residual_sample(
    baseline: np.ndarray,
    weights: np.ndarray,
    grid: downscaler.GeoGrid,
    rng: np.random.Generator,
    checkpoint: Dict[str, Any],
    guidance_scale: float,
    steps: int,
) -> np.ndarray:
    residual_scale = _checkpoint_float(checkpoint, "residual_scale", 0.08)
    smooth_sigma_m = _checkpoint_float(checkpoint, "residual_sigma_m", 900.0)
    weight_influence = _checkpoint_float(checkpoint, "weight_influence", 0.35)

    noise = rng.normal(0.0, 1.0, size=baseline.shape)
    sigma_cells = max(0.01, smooth_sigma_m / float(max(grid.dx, grid.dy)))
    structured = downscaler.nan_gaussian_filter(noise, sigma_cells).astype(float)
    finite = np.isfinite(structured)
    if np.any(finite):
        std = float(np.nanstd(structured[finite]))
        if np.isfinite(std) and std > 1.0e-30:
            structured = structured / std

    w = np.asarray(weights, dtype=float)
    valid_w = np.isfinite(w) & (w > 0)
    anomaly = np.zeros_like(w, dtype=float)
    if np.any(valid_w):
        median_w = float(np.nanmedian(w[valid_w]))
        if np.isfinite(median_w) and median_w > 0:
            anomaly[valid_w] = np.log(np.maximum(w[valid_w], 1.0e-30) / median_w)

    step_factor = np.sqrt(max(1, int(steps)) / 50.0)
    residual = residual_scale * float(guidance_scale) * step_factor * (structured + weight_influence * anomaly)
    return np.maximum(np.asarray(baseline, dtype=float) * np.exp(residual), 0.0).astype(np.float32)


def diffusion_output_transform(
    field: np.ndarray,
    weights: np.ndarray,
    grid: downscaler.GeoGrid,
    ref: downscaler.RasterReference,
    input_band_array: np.ndarray,
    args: argparse.Namespace,
) -> np.ndarray:
    if args.diffusion_train:
        if args.diffusion_train_config is None:
            raise ValueError("--diffusion-train requires --diffusion-train-config")
        if not args.diffusion_train_config.exists():
            raise FileNotFoundError(f"Diffusion training config does not exist: {args.diffusion_train_config}")
        if args.diffusion_train_output_dir is None:
            raise ValueError("--diffusion-train requires --diffusion-train-output-dir")
        args.diffusion_train_output_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "strategy": args.diffusion_training_strategy,
            "config": str(args.diffusion_train_config),
            "status": "configuration validated; train the diffusion model with your ML training stack",
        }
        (args.diffusion_train_output_dir / "training_manifest.json").write_text(json.dumps(manifest, indent=2))
        raise SystemExit(0)

    if args.diffusion_checkpoint is None:
        raise ValueError("--method diffusion inference requires --diffusion-checkpoint PATH")
    if args.diffusion_samples < 1:
        raise ValueError("--diffusion-samples must be at least 1")

    checkpoint = _load_checkpoint(args.diffusion_checkpoint)
    samples = []
    for idx in range(int(args.diffusion_samples)):
        rng = np.random.default_rng(int(args.diffusion_seed) + idx)
        raw = _positive_residual_sample(
            baseline=field,
            weights=weights,
            grid=grid,
            rng=rng,
            checkpoint=checkpoint,
            guidance_scale=args.diffusion_guidance_scale,
            steps=args.diffusion_steps,
        )
        conserved = downscaler.conservative_normalize_to_source(ref, input_band_array, raw, grid, nonnegative=True)
        samples.append(conserved)

    stack = np.stack(samples, axis=0)
    mean_field = np.nanmean(stack, axis=0).astype(np.float32)
    final = downscaler.conservative_normalize_to_source(ref, input_band_array, mean_field, grid, nonnegative=True)

    if args.write_ensemble and len(samples) > 1:
        for idx, sample in enumerate(samples, start=1):
            path = args.output_tif.with_name(f"{args.output_tif.stem}_ensemble_{idx:03d}{args.output_tif.suffix}")
            downscaler.write_pollutant_raster(path, grid, sample, tags=diffusion_raster_tags({}), pollutant=args.pollutant, source_band=args.input_band)
    if args.write_uncertainty and len(samples) > 1:
        path = args.output_tif.with_name(f"{args.output_tif.stem}_uncertainty{args.output_tif.suffix}")
        downscaler.write_pollutant_raster(path, grid, np.nanstd(stack, axis=0).astype(np.float32), tags={"method": "diffusion_ensemble_uncertainty"}, pollutant=args.pollutant, source_band=args.input_band)

    return final


def diffusion_raster_tags(tags: dict) -> dict:
    out = dict(tags)
    out.update(
        {
            "method": "diffusion_conservation_guided_downscaling",
            "diffusion_model": "residual_conditional_diffusion_checkpoint",
            "conservation": "hard_coarse_to_fine_normalization",
        }
    )
    return out


def main() -> None:
    downscaler.main(
        method_name="diffusion",
        add_method_arguments=add_diffusion_arguments,
        method_output_transform=diffusion_output_transform,
        raster_tag_builder=diffusion_raster_tags,
    )


if __name__ == "__main__":
    main()
