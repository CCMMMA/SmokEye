"""Logging helpers for command-line entry points."""

from __future__ import annotations

import logging
import sys


def configure_cli_logging(level: int = logging.INFO) -> None:
    """Configure plain CLI logging unless the host application already did."""
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)
