# CALPUFF-To-Satellite Comparison

Use `prepare_calpuff.py` and `compare_calpuff_satellite.py` to compare CALPUFF gridded outputs with a satellite or SmokEye-downscaled pollutant GeoTIFF on a common raster grid.

This is a comparison workflow, not a downscaling method. It is intended for cases where CALPUFF `.con`, `.dry`, or `.wet` style outputs must be spatially aligned, temporally matched, converted into the same pollutant unit, and compared pixel by pixel against a reference GeoTIFF.

## Commands

```bash
python prepare_calpuff.py \
  --calpuff calpuff.con \
  --geo GEO.DAT \
  --satellite final_weight_gt_deblocked.tif \
  --species NO2 \
  --group TOTAL \
  --time-start 2025-02-25T07:00:00 \
  --time-end 2025-02-25T08:00:00 \
  --satellite-time-start 2025-02-25T07:00:00 \
  --satellite-time-end 2025-02-25T08:00:00 \
  --time-agg mean \
  --time-selection closest \
  --calpuff-unit arbitrary \
  --satellite-unit ug_m3 \
  --target-unit ug_m3 \
  --calpuff-scale 0.001 \
  --background 2.0 \
  --out-prefix outputs/no2_total_vs_satellite

python compare_calpuff_satellite.py \
  --model outputs/no2_total_vs_satellite.model.tif \
  --satellite outputs/no2_total_vs_satellite.satellite.tif \
  --preparation-report outputs/no2_total_vs_satellite.prepare.json \
  --out-prefix outputs/no2_total_vs_satellite
```

## Inspecting CALPUFF records

```bash
python prepare_calpuff.py \
  --calpuff calpuff.con \
  --geo GEO.DAT \
  --list-records
```

The listing reports record index, species, level, source group, start/end time, and basic statistics. Use this before deciding `--species`, `--group`, `--level`, and the comparison time window.

## Time consistency

The reference time window must represent the validity period of the satellite or downscaled GeoTIFF. Supply it explicitly with:

```text
--satellite-time-start
--satellite-time-end
```

or store common time tags in the GeoTIFF. The command accepts naive ISO datetimes and timezone-aware values such as `2025-02-25T07:00:00Z` or `2025-02-25T08:00:00+01:00`; timezone-aware inputs are normalized to UTC internally.

Default behavior is strict:

```text
--time-overlap-policy strict
--min-time-overlap-fraction 0.95
```

This prevents accidental comparison of a CALPUFF time window against an unrelated satellite pass or downscaled product. Use `warn` only for diagnostics and `ignore` only when time matching is intentionally bypassed.

CALPUFF temporal aggregation uses the overlap with `--time-start/--time-end`:

```text
mean  -> weighted by overlap seconds
sum   -> prorated by overlap fraction
first -> first overlapping record
last  -> last overlapping record
max   -> maximum over overlapping records
```

`--time-selection closest` is useful when CALPUFF records are timestamped as interval endpoints or nearest-hour snapshots. It first prefers overlapping records, then selects the nearest record midpoint if no overlap exists. The closest-time decision is written to JSON diagnostics.

## Units and background

All comparison values must be in the same target unit. The conversion order is fixed:

```text
calpuff_target = raw_CALPUFF * calpuff_scale + calpuff_offset
model_for_comparison = calpuff_target + background
satellite_target = raw_satellite * satellite_scale + satellite_offset
```

The background value is in `--target-unit` and is added after CALPUFF conversion. This makes it possible to use CALPUFF arbitrary/model units while comparing against a satellite/downscaled GeoTIFF in a physical unit.

SmokEye intentionally does not infer physical conversions between near-surface concentrations, deposition fluxes, mixing ratios, and satellite column amounts. Use explicit scale/offset values and record the scientific basis externally or in the run metadata.

## Outputs

For `--out-prefix outputs/no2_total_vs_satellite`, `prepare_calpuff.py` writes:

```text
outputs/no2_total_vs_satellite.model.tif
outputs/no2_total_vs_satellite.satellite.tif
outputs/no2_total_vs_satellite.prepare.json
```

Then `compare_calpuff_satellite.py` writes:

```text
outputs/no2_total_vs_satellite.difference.tif
outputs/no2_total_vs_satellite.ratio.tif
outputs/no2_total_vs_satellite.stats.json
outputs/no2_total_vs_satellite.stats.csv
```

The preparation JSON includes the CALPUFF record selection, GEO.DAT grid metadata, reference raster metadata, time-overlap report, unit-conversion report, and scientific caveats. The comparison JSON includes the prepared raster paths, optional embedded preparation report, statistics, and scientific caveats.

## Interpretation caveats

Spatial alignment does not make CALPUFF and satellite products physically equivalent. Temporal mismatch, vertical representativeness, chemistry, deposition/concentration differences, and user-provided background levels can dominate the comparison. Treat the outputs as diagnostic products and keep unit/time assumptions visible in the JSON report.
