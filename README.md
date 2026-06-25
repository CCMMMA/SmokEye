# SmokEye Pollutant Downscaler

SmokEye provides two comparable workflows for downscaling a gridded pollutant raster to the grid defined by a CALMET `GEO.DAT` file:

- `downscale_pollutant_geodat_calmet.py`: deterministic dynamic downscaling with conservative allocation.
- `downscale_pollutant_geodat_calmet_ai.py`: AI-based dynamic downscaling with the same input interface and the same output products.

Both scripts read the same pollutant raster, CALMET/CMET meteorology, `GEO.DAT` target grid, and optional station CSV. Both write a single-band GeoTIFF aligned to the `GEO.DAT` grid, plus optional diagnostic rasters and JSON reports. This makes the two methods suitable for direct side-by-side comparison.

## What The Workflow Does

The scripts do not simply resample the source raster. They treat each source pixel value as a coarse observational constraint and distribute it over the finer CALMET grid using a weight field. The allocation is conservative before optional seamless/deblocking regularization:

```text
fine_i = source_P * w_i * sum(A_iP) / sum(w_i * A_iP)
```

where `w_i` is the fine-grid weight and `A_iP` is the overlap area between fine cell `i` and source pixel `P`.

The deterministic script builds `w_i` from explicit terrain, land-use, and meteorological rules. The AI script builds `w_i` using a deterministic machine-learning model while preserving the same downstream allocation, station-correction, reporting, and validation behavior.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On systems where `rasterio` needs GDAL-compatible wheels, a conda environment is often easier:

```bash
conda create -n smokeye -c conda-forge python=3.11 numpy rasterio shapely pyproj scipy
conda activate smokeye
```

## Quick Start

Inspect the target grid:

```bash
python downscale_pollutant_geodat_calmet.py --inspect-geodat data/geo.dat
```

Run deterministic downscaling:

```bash
python downscale_pollutant_geodat_calmet.py \
  data/S5P_NO2_000_20240628T111519UTC_orbit-unknown.tif \
  data/cmet.dat \
  data/geo.dat \
  output/deterministic_no2.tif \
  --pollutant NO2 \
  --input-band 1 \
  --groundtruth-csv data/groundtruth.csv \
  --groundtruth-value-column NO2 \
  --validate \
  --station-report output/deterministic_station_report.json \
  --write-weight output/deterministic_weight.tif \
  --write-correction output/deterministic_correction.tif
```

Run AI downscaling with the same interface:

```bash
python downscale_pollutant_geodat_calmet_ai.py \
  data/S5P_NO2_000_20240628T111519UTC_orbit-unknown.tif \
  data/cmet.dat \
  data/geo.dat \
  output/ai_no2.tif \
  --pollutant NO2 \
  --input-band 1 \
  --groundtruth-csv data/groundtruth.csv \
  --groundtruth-value-column NO2 \
  --validate \
  --station-report output/ai_station_report.json \
  --write-weight output/ai_weight.tif \
  --write-correction output/ai_correction.tif
```

## Documentation

- [Workflow overview](docs/workflow.md)
- [Input data requirements](docs/input-data.md)
- [Deterministic method](docs/deterministic-method.md)
- [AI method](docs/ai-method.md)
- [Step-by-step comparison guide](docs/comparison-guide.md)
- [Outputs, reports, and validation](docs/outputs-and-validation.md)

## Repository Layout

```text
SmokEye/
├── downscale_pollutant_geodat_calmet.py
├── downscale_pollutant_geodat_calmet_ai.py
├── requirements.txt
├── README.md
├── docs/
│   ├── workflow.md
│   ├── input-data.md
│   ├── deterministic-method.md
│   ├── ai-method.md
│   ├── comparison-guide.md
│   └── outputs-and-validation.md
├── examples/
│   └── groundtruth_example.csv
└── data/
    ├── S5P_NO2_000_20240628T111519UTC_orbit-unknown.tif
    ├── cmet.dat
    ├── geo.dat
    └── groundtruth.csv
```

## Scientific Caveats

- A 200 m output grid does not mean the satellite observed the pollutant at 200 m resolution.
- The output is a model-assisted allocation product.
- Optional seamless/deblocking regularization improves visual continuity but relaxes strict per-source-pixel conservation.
- Station measurements are near-surface values, while some satellite products are column quantities. Station correction should be interpreted carefully.
- For production use, review the weight logic for the target pollutant, emissions regime, meteorology, and local land-use classes.

## License

This project is released under the MIT License. See `LICENSE`.
