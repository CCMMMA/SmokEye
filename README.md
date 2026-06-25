# Pollutant Downscaler GEO.DAT/CALMET

`pollutant-downscaler` is a standalone Python workflow for dynamically downscaling a gridded pollutant raster to the grid defined by a CALMET `GEO.DAT` file. It was developed for Sentinel-5P/TROPOMI NO2 experiments, but the current script is pollutant-agnostic and can be used with NO2, O3, PM10, PM2.5/PM25, SO2, CO, or any scalar pollutant field stored as a raster band.

The output is a single-band GeoTIFF aligned to the `GEO.DAT` reference grid, typically 200 m, and optionally corrected using air-quality station measurements.

## Scientific idea

The script does **not** simply resample the coarse raster. It treats the input raster value as a coarse observational constraint and distributes it over the finer `GEO.DAT` grid using a dynamic weight field built from:

- CALMET/CALWRF-style meteorology, when available;
- terrain and land-use read from `GEO.DAT`;
- optional station ground truth supplied as CSV;
- optional seamless/deblocking regularization to reduce visible coarse-pixel seams.

For each coarse source pixel `P` and fine cell `i`, the conservative allocation is:

```text
fine_i = source_P * w_i * sum(A_iP) / sum(w_i * A_iP)
```

where `w_i` is the dynamic fine-grid weight and `A_iP` is the area of intersection between fine cell `i` and coarse pixel `P`.

This preserves the coarse field when exact conservative mode is used. Seamless/deblocking regularization can make maps visually smoother, but it relaxes strict per-source-pixel conservation; the domain mean is preserved by default.

## Main features

- Reads any selected band from an input pollutant GeoTIFF.
- Infers grid geometry, CRS, terrain, and land-use from CALMET `GEO.DAT`.
- Supports optional `--geodat-sidecar` JSON if a local `GEO.DAT` variant cannot be inferred automatically.
- Reads common Fortran-unformatted CALMET/CMET.DAT records, including `ZI`, `TEMPK`, `USTAR`, `Z0`, `U-LEV 1`, `V-LEV 1`, `ELEV`, and `ILANDU` when present.
- Supports meteorological fields from `.npz` files on the `GEO.DAT` grid.
- Uses station ground-truth CSV files with configurable pollutant/value column.
- Estimates the average background pollutant value from stations.
- Reports station before/after metrics and coarse-scale validation statistics.
- Writes optional diagnostic rasters: dynamic weights and station correction field.
- MIT licensed.

## Installation

Create a virtual environment and install the requirements:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On some systems `rasterio` may require GDAL-compatible wheels or a conda environment. A conda alternative is:

```bash
conda create -n pollutant-downscaler -c conda-forge python=3.11 numpy rasterio shapely pyproj scipy
conda activate pollutant-downscaler
```

## Input files

### 1. Input pollutant raster

A GeoTIFF containing the pollutant field. The script reads one 1-based band selected with `--input-band`.

Example pollutants:

- Sentinel-5P/TROPOMI tropospheric NO2 column;
- satellite/model O3 field;
- PM10 or PM2.5 raster field;
- SO2 or CO raster field;
- any scalar environmental variable where dynamic fine-grid allocation is meaningful.

### 2. CALMET `GEO.DAT`

The target grid is inferred from `GEO.DAT`. For the test dataset used during development the inferred grid was:

```text
CRS: EPSG:32633
Grid: 100 x 100
Resolution: 200 m x 200 m
Origin: lower-left
```

If your `GEO.DAT` variant cannot be inferred automatically, provide a JSON sidecar:

```json
{
  "crs": "EPSG:32633",
  "nx": 100,
  "ny": 100,
  "x0": 434304.0,
  "y0": 4515091.0,
  "dx": 200.0,
  "dy": 200.0,
  "origin": "lower-left"
}
```

Then pass it with `--geodat-sidecar geodat_grid.json`.

### 3. CALMET/CMET meteorology or NPZ meteorology

The positional `calmet_dat` argument can point to a CALMET/CMET.DAT binary file. The script attempts to read useful meteorological fields directly. If your CALMET binary layout differs, export fields to `.npz` and pass `--met-npz`.

Expected NPZ arrays must have shape `(ny, nx)` on the `GEO.DAT` grid. Supported field names include:

```text
pblh, ws10, u10, v10, ustar, tempk, z0, elevation_calmet, landuse_calmet
```

If both `u10` and `v10` are present, `ws10` is derived automatically.

### 4. Optional station ground truth CSV

The CSV must contain station ID and coordinates:

```csv
ID,LAT,LON,NO2
AQSTN_A1,40.814289,14.267230,9.9736753e-05
AQSTN_B2,40.845249,14.321457,0.00015246817
```

For other pollutants, either name the value column after `--pollutant`, for example `O3` or `PM10`, or specify it explicitly:

```bash
--groundtruth-value-column PM25
```

Column matching is case-insensitive. `PM25` also accepts `PM2.5` when present.

## Usage

### Inspect the target grid

```bash
python downscale_pollutant_geodat_calmet.py --inspect-geodat data/geo.dat
```

### Inspect CALMET records

```bash
python downscale_pollutant_geodat_calmet.py --inspect-calmet data/cmet.dat
```

### Inspect station CSV and estimate background

```bash
python downscale_pollutant_geodat_calmet.py \
  --pollutant NO2 \
  --inspect-groundtruth examples/groundtruth_example.csv
```

### Basic dynamic downscaling

```bash
python downscale_pollutant_geodat_calmet.py \
  data/input_pollutant.tif \
  data/cmet.dat \
  data/geo.dat \
  output/downscaled_pollutant.tif \
  --pollutant NO2 \
  --input-band 1 \
  --validate
```

### Downscaling with station correction

```bash
python downscale_pollutant_geodat_calmet.py \
  data/input_pollutant.tif \
  data/cmet.dat \
  data/geo.dat \
  output/downscaled_no2_station_corrected.tif \
  --pollutant NO2 \
  --input-band 1 \
  --groundtruth-csv data/groundtruth.csv \
  --groundtruth-value-column NO2 \
  --validate \
  --station-report output/station_report.json \
  --write-weight output/final_weight.tif \
  --write-correction output/station_correction.tif
```

### PM10 example

```bash
python downscale_pollutant_geodat_calmet.py \
  data/pm10_coarse.tif \
  data/cmet.dat \
  data/geo.dat \
  output/pm10_200m.tif \
  --pollutant PM10 \
  --input-band 1 \
  --groundtruth-csv data/pm10_stations.csv \
  --groundtruth-value-column PM10 \
  --validate
```

### O3 example

Ozone may have different source/dispersion behavior than NO2. The current dynamic weights are generic and should be reviewed for ozone-specific chemistry and regional transport.

```bash
python downscale_pollutant_geodat_calmet.py \
  data/o3_coarse.tif \
  data/cmet.dat \
  data/geo.dat \
  output/o3_200m.tif \
  --pollutant O3 \
  --groundtruth-csv data/o3_stations.csv \
  --groundtruth-value-column O3
```

## Background estimation

When `--groundtruth-csv` is provided, the script estimates a background value from station measurements. Modes:

```text
--background-mode low-percentile  # default
--background-mode mean
--background-mode median
--background-mode min
--background-mode none
```

For `low-percentile`, the default threshold is the 40th percentile:

```bash
--background-percentile 40
```

The background is used in the station correction ratio by default through background-excess correction:

```text
ratio = max(obs - background, eps) / max(pred - background, eps)
```

Use direct observed/predicted ratios instead with:

```bash
--station-direct-ratio
```

## Seamless/deblocking options

Strict conservation per source pixel can reveal coarse-pixel boundaries. The script includes two regularization stages:

```bash
--seamless / --no-seamless
--seamless-baseline-sigma-m 1400
--seamless-anomaly-sigma-m 1000
--seamless-strength 0.95
--deblock-sigma-m 400
--deblock-strength 0.75
--deblock-iterations 1
```

More aggressive seam removal:

```bash
--seamless-baseline-sigma-m 2200 \
--seamless-anomaly-sigma-m 900 \
--seamless-strength 1.0 \
--deblock-sigma-m 700 \
--deblock-strength 0.85
```

Caution: stronger deblocking improves visual continuity but relaxes exact per-pixel conservation. Use `--validate` to quantify the impact.

## Outputs

Main output:

- single-band GeoTIFF aligned to the `GEO.DAT` grid.

Optional outputs:

- `--write-weight`: final dynamic weight raster;
- `--write-correction`: station multiplicative correction raster;
- `--station-report`: JSON report with station metrics, background estimate, correction details, and conservation validation.

## Limitations and scientific caveats

- A 200 m output does not mean the satellite or source raster observed the pollutant at 200 m resolution.
- The output is a model-assisted downscaling/allocation product.
- For reactive pollutants such as NO2 and O3, chemistry, vertical sensitivity, emissions, and transport matter. If available, use a chemistry-transport model or pollutant-specific weights.
- Station measurements are near-surface values, while many satellite products are column quantities. Bias correction using stations should be interpreted carefully.
- The built-in weight model is intentionally conservative and generic. For production use, adapt `build_weights()` to the target pollutant, emissions inventory, land-use categories, and meteorological regime.

## Repository layout

```text
pollutant-downscaler/
├── downscale_pollutant_geodat_calmet.py
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
└── examples/
    └── groundtruth_example.csv
```

## License

This project is released under the MIT License. See `LICENSE`.
