from datetime import datetime

import numpy as np

from smokeye.temporal import overlap_seconds, parse_datetime, time_check_report
from smokeye.unit_conversion import apply_linear_conversion


def test_timezone_datetime_is_normalized_to_utc_naive():
    assert parse_datetime("2025-02-25T08:00:00+01:00") == datetime(2025, 2, 25, 7, 0, 0)


def test_overlap_seconds():
    a0 = datetime(2025, 2, 25, 7)
    a1 = datetime(2025, 2, 25, 8)
    b0 = datetime(2025, 2, 25, 7, 30)
    b1 = datetime(2025, 2, 25, 8, 30)
    assert overlap_seconds(a0, a1, b0, b1) == 1800.0


def test_strict_time_report_ok():
    report = time_check_report(
        datetime(2025, 2, 25, 7),
        datetime(2025, 2, 25, 8),
        datetime(2025, 2, 25, 7),
        datetime(2025, 2, 25, 8),
        "cli",
    )
    assert report["time_consistency"] == "ok"
    assert report["time_overlap_fraction_of_satellite"] == 1.0


def test_unit_conversion_order_is_explicit():
    raw = np.array([0.0, 1000.0], dtype=np.float32)
    converted = apply_linear_conversion(raw, 0.001, 0.0)
    model = converted + 2.0
    assert np.allclose(model, [2.0, 3.0])
