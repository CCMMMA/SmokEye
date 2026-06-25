"""Unified command-line entry point for SmokEye pollutant downscaling."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from smokeye import ai_downscaler, comparison, diffusion_downscaler, downscaler


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] == "compare-calpuff":
        parser = argparse.ArgumentParser(
            prog="downscale_pollutant.py compare-calpuff",
            description="Compare CALPUFF gridded output with a satellite/downscaled pollutant GeoTIFF.",
        )
        comparison.add_compare_calpuff_arguments(parser)
        args = parser.parse_args(argv[1:])
        comparison.run_compare_calpuff(args)
        return

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--method",
        choices=["deterministic", "ai", "diffusion"],
        default="deterministic",
        help="Downscaling weight strategy to use. Defaults to deterministic.",
    )
    args, remaining = parser.parse_known_args(argv)
    if "-h" in argv or "--help" in argv:
        if args.method == "diffusion":
            downscaler.main(
                raster_tag_builder=diffusion_downscaler.diffusion_raster_tags,
                add_method_arguments=diffusion_downscaler.add_diffusion_arguments,
                method_output_transform=diffusion_downscaler.diffusion_output_transform,
                method_name="diffusion",
                argv=remaining,
                include_method_help=True,
            )
        else:
            downscaler.main(method_name=args.method, argv=remaining, include_method_help=True)
        return

    if args.method == "ai":
        downscaler.main(
            weight_builder=ai_downscaler.build_ai_weights,
            raster_tag_builder=ai_downscaler.ai_raster_tags,
            method_name="ai",
            argv=remaining,
        )
    elif args.method == "diffusion":
        downscaler.main(
            raster_tag_builder=diffusion_downscaler.diffusion_raster_tags,
            add_method_arguments=diffusion_downscaler.add_diffusion_arguments,
            method_output_transform=diffusion_downscaler.diffusion_output_transform,
            method_name="diffusion",
            argv=remaining,
        )
    else:
        downscaler.main(method_name="deterministic", argv=remaining)
