from __future__ import annotations

import unittest
import argparse
from datetime import datetime

import numpy as np

from smokeye.calpuff_reader import CalpuffGridRecord
from smokeye.comparison import _stats, add_compare_calpuff_arguments, aggregate_records, select_records_for_window
from smokeye.downscaler import GeoDATReader, calmet_stamp_from_window, enforce_met_time_consistency, orient_grid_array
from smokeye.temporal import time_check_report
from smokeye.unit_conversion import apply_linear_conversion, unit_report


class ComparisonTests(unittest.TestCase):
    def test_grid_array_orientation_lower_flips_to_raster_order(self):
        raw = np.array([1, 2, 3, 4])
        lower = orient_grid_array(raw, nx=2, ny=2, array_origin="lower")
        upper = orient_grid_array(raw, nx=2, ny=2, array_origin="upper")
        self.assertTrue(np.array_equal(lower, np.array([[3, 4], [1, 2]])))
        self.assertTrue(np.array_equal(upper, np.array([[1, 2], [3, 4]])))

    def test_geodat_reader_array_origin_controls_embedded_arrays(self):
        lines = [
            "LAND USE DATA",
            "NLU",
            "CATEGORIES",
            "1 2 3 4",
            "TERRAIN HEIGHT 1.0",
            "10 20 30 40",
        ]
        lu_lower = GeoDATReader._read_landuse(lines, nx=2, ny=2, array_origin="lower")
        lu_upper = GeoDATReader._read_landuse(lines, nx=2, ny=2, array_origin="upper")
        elev_lower = GeoDATReader._read_elevation(lines, nx=2, ny=2, array_origin="lower")
        elev_upper = GeoDATReader._read_elevation(lines, nx=2, ny=2, array_origin="upper")
        self.assertTrue(np.array_equal(lu_lower, np.array([[3, 4], [1, 2]], dtype=np.int16)))
        self.assertTrue(np.array_equal(lu_upper, np.array([[1, 2], [3, 4]], dtype=np.int16)))
        self.assertTrue(np.array_equal(elev_lower, np.array([[30, 40], [10, 20]], dtype=np.float32)))
        self.assertTrue(np.array_equal(elev_upper, np.array([[10, 20], [30, 40]], dtype=np.float32)))

    def test_unit_conversion_and_background_report(self):
        raw_calpuff = np.full((2, 2), 1000.0, dtype=np.float32)
        converted = apply_linear_conversion(raw_calpuff, 0.001, 0.0)
        model = converted + 2.0
        raw_satellite = np.full((2, 2), 10.0, dtype=np.float32)
        satellite = apply_linear_conversion(raw_satellite, 0.5, 1.0)
        report = unit_report(
            raw_calpuff,
            converted,
            model,
            raw_satellite,
            satellite,
            calpuff_unit="arbitrary",
            satellite_unit="ug_m3",
            target_unit="ug_m3",
            calpuff_scale=0.001,
            calpuff_offset=0.0,
            satellite_scale=0.5,
            satellite_offset=1.0,
            background=2.0,
        )
        self.assertTrue(np.allclose(model, 3.0))
        self.assertTrue(np.allclose(satellite, 6.0))
        self.assertEqual(report["background"], 2.0)
        self.assertEqual(report["calpuff_scale"], 0.001)

    def test_unit_report_defaults_to_micrograms_per_cubic_meter(self):
        raw = np.ones((1, 1), dtype=np.float32)
        report = unit_report(
            raw,
            raw,
            raw,
            raw,
            raw,
            calpuff_unit="ug_m3",
            satellite_unit="ug_m3",
            target_unit="ug_m3",
            calpuff_scale=1.0,
            calpuff_offset=0.0,
            satellite_scale=1.0,
            satellite_offset=0.0,
            background=0.0,
        )
        self.assertEqual(report["target_unit"], "ug_m3")
        self.assertEqual(report["calpuff_unit"], "ug_m3")
        self.assertEqual(report["satellite_unit"], "ug_m3")

    def test_compare_cli_defaults_to_micrograms_per_cubic_meter(self):
        parser = argparse.ArgumentParser()
        add_compare_calpuff_arguments(parser)
        args = parser.parse_args(["--calpuff", "calpuff.con", "--geo", "GEO.DAT"])
        self.assertEqual(args.calpuff_unit, "ug_m3")
        self.assertEqual(args.satellite_unit, "ug_m3")
        self.assertEqual(args.target_unit, "ug_m3")


    def test_time_consistency_strict_and_warn(self):
        start = datetime(2025, 2, 25, 7)
        end = datetime(2025, 2, 25, 8)
        ok = time_check_report(start, end, start, end, "cli", policy="strict", min_fraction=0.95, allow_untimed_satellite=False)
        self.assertEqual(ok["time_consistency"], "ok")
        with self.assertRaises(ValueError):
            time_check_report(start, end, datetime(2025, 2, 25, 9), datetime(2025, 2, 25, 10), "cli", policy="strict", min_fraction=0.95, allow_untimed_satellite=False)
        warn = time_check_report(start, end, datetime(2025, 2, 25, 9), datetime(2025, 2, 25, 10), "cli", policy="warn", min_fraction=0.95, allow_untimed_satellite=False)
        self.assertEqual(warn["time_consistency"], "warning")


    def test_aggregation_mean_weights_and_sum_prorates(self):
        records = [
            CalpuffGridRecord("NO2", None, "TOTAL", datetime(2025, 2, 25, 7), datetime(2025, 2, 25, 8), np.full((1, 1), 2.0, dtype=np.float32)),
            CalpuffGridRecord("NO2", None, "TOTAL", datetime(2025, 2, 25, 8), datetime(2025, 2, 25, 9), np.full((1, 1), 6.0, dtype=np.float32)),
        ]
        start = datetime(2025, 2, 25, 7, 30)
        end = datetime(2025, 2, 25, 8, 30)
        self.assertTrue(np.allclose(aggregate_records(records, start, end, "mean"), [[4.0]]))
        self.assertTrue(np.allclose(aggregate_records(records, start, end, "sum"), [[4.0]]))

    def test_closest_time_selection_is_deterministic_and_reported(self):
        records = [
            CalpuffGridRecord("NO2", None, "TOTAL", datetime(2025, 2, 25, 5), datetime(2025, 2, 25, 6), np.full((1, 1), 2.0, dtype=np.float32)),
            CalpuffGridRecord("NO2", None, "TOTAL", datetime(2025, 2, 25, 9), datetime(2025, 2, 25, 10), np.full((1, 1), 6.0, dtype=np.float32)),
        ]
        chosen, weights, report = select_records_for_window(records, datetime(2025, 2, 25, 7), datetime(2025, 2, 25, 8), "closest", 7200.0)
        self.assertEqual(chosen[0].start, datetime(2025, 2, 25, 5))
        self.assertTrue(np.allclose(weights, [1.0]))
        self.assertEqual(report["time_selection"], "closest")
        self.assertEqual(report["closest_time_delta_seconds"], 7200.0)
        with self.assertRaises(ValueError):
            select_records_for_window(records, datetime(2025, 2, 25, 7), datetime(2025, 2, 25, 8), "overlap")
        with self.assertRaises(ValueError):
            select_records_for_window(records, datetime(2025, 2, 25, 7), datetime(2025, 2, 25, 8), "closest", 3600.0)

    def test_downscaling_calmet_timestamp_policy_helpers(self):
        self.assertEqual(
            calmet_stamp_from_window(datetime(2025, 2, 25, 7), datetime(2025, 2, 25, 8)),
            2025022507,
        )
        report = {
            "fields": {
                "ws10": {"selected_stamp": 2025022508, "requested_stamp": 2025022507, "stamp_delta": 1},
            }
        }
        enforce_met_time_consistency(report, 1)
        with self.assertRaises(ValueError):
            enforce_met_time_consistency(report, 0)

    def test_stats_ignore_nan_and_mask_zero_ratio(self):
        model = np.array([[2.0, 4.0], [np.nan, 8.0]], dtype=np.float32)
        satellite = np.array([[1.0, 0.0], [5.0, np.nan]], dtype=np.float32)
        stats = _stats(model, satellite)
        self.assertEqual(stats["n_valid"], 2)
        self.assertEqual(stats["bias_model_minus_satellite"], 2.5)
        self.assertEqual(stats["ratio_mean"], 2.0)


if __name__ == "__main__":
    unittest.main()
