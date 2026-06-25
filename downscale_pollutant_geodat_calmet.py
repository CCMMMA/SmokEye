#!/usr/bin/env python3
"""Compatibility entry point for the deterministic SmokEye downscaler."""

from smokeye.downscaler import *  # noqa: F403
from smokeye.downscaler import main


if __name__ == "__main__":
    main()
