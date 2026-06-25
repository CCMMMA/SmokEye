# SmokEye Pollutant Downscaler

SmokEye provides one command with three comparable workflows for downscaling a gridded pollutant raster to the grid defined by a CALMET `GEO.DAT` file:

- `python downscale_pollutant.py --method deterministic`: deterministic dynamic downscaling with conservative allocation.
- `python downscale_pollutant.py --method ai`: AI-based dynamic downscaling with the same input interface and the same output products.
- `python downscale_pollutant.py --method diffusion`: conservation-guided residual diffusion downscaling with hard coarse-to-fine normalization.

All methods read the same pollutant raster, CALMET/CMET meteorology, `GEO.DAT` target grid, and optional station CSV. They write a single-band GeoTIFF aligned to the `GEO.DAT` grid, plus optional diagnostic rasters and JSON reports. This makes the methods suitable for direct side-by-side comparison.

The top-level script is a thin compatibility entry point. Shared implementation lives in the `smokeye` package so deterministic and AI workflows do not duplicate parsing, I/O, conservative allocation, station correction, validation, or raster writing code.

## What The Workflow Does

The command does not simply resample the source raster. It treats each source pixel value as a coarse observational constraint and distributes it over the finer CALMET grid using a weight field. The allocation is conservative before optional seamless/deblocking regularization:

```text
fine_i = source_P * w_i * sum(A_iP) / sum(w_i * A_iP)
```

where `w_i` is the fine-grid weight and `A_iP` is the overlap area between fine cell `i` and source pixel `P`.

The deterministic method builds `w_i` from explicit terrain, land-use, and meteorological rules. The AI method builds `w_i` using a deterministic machine-learning model while preserving the same downstream allocation, station-correction, reporting, and validation behavior. The diffusion method starts from the deterministic conservative field, generates positive residual fine-grid structure from an explicit checkpoint, and then hard-normalizes the result so each source pollutant pixel footprint aggregates back to the original coarse value.

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
python downscale_pollutant.py --inspect-geodat data/geo.dat
```

Run deterministic downscaling:

```bash
python downscale_pollutant.py \
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
python downscale_pollutant.py --method ai \
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

Run diffusion downscaling with an explicit checkpoint:

```bash
python downscale_pollutant.py --method diffusion \
  data/S5P_NO2_000_20240628T111519UTC_orbit-unknown.tif \
  data/cmet.dat \
  data/geo.dat \
  output/diffusion_no2.tif \
  --pollutant NO2 \
  --input-band 1 \
  --diffusion-checkpoint runs/diffusion_hybrid/best.pt \
  --diffusion-samples 8 \
  --diffusion-seed 42 \
  --write-uncertainty \
  --validate
```

Diffusion inference fails with a clear error if `--diffusion-checkpoint` is omitted. This prevents deterministic output from being mislabeled as diffusion-assisted output.

## Documentation

- [Workflow overview](docs/workflow.md)
- [Getting started](docs/getting_started.md)
- [Input data requirements](docs/input-data.md)
- [Deterministic method](docs/deterministic-method.md)
- [AI method](docs/ai-method.md)
- [Diffusion method](docs/diffusion-method.md)
- [Step-by-step comparison guide](docs/comparison-guide.md)
- [Outputs, reports, and validation](docs/outputs-and-validation.md)

## Repository Layout

```text
SmokEye/
├── downscale_pollutant.py
├── smokeye/
│   ├── __init__.py
│   ├── cli.py
│   ├── ai_downscaler.py
│   ├── diffusion_downscaler.py
│   ├── downscaler.py
│   └── ...
├── requirements.txt
├── README.md
├── AGENTS.md
├── docs/
│   ├── workflow.md
│   ├── getting_started.md
│   ├── input-data.md
│   ├── deterministic-method.md
│   ├── ai-method.md
│   ├── diffusion-method.md
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

## Development Notes

- Keep `downscale_pollutant.py` as a thin command-line wrapper.
- Put shared behavior in `smokeye/downscaler.py`.
- Put unified CLI dispatch in `smokeye/cli.py`.
- Put AI-specific weight-model behavior in `smokeye/ai_downscaler.py`.
- Do not duplicate source code between deterministic and AI workflows; add strategy hooks to the shared workflow when methods need to differ.

## Scientific Caveats

- A 200 m output grid does not mean the satellite observed the pollutant at 200 m resolution.
- The output is a model-assisted allocation product.
- Optional seamless/deblocking regularization improves visual continuity but relaxes strict per-source-pixel conservation.
- The diffusion method reapplies hard coarse-to-fine normalization after residual generation, so the written diffusion raster is the conservation-enforced product.
- Station measurements are near-surface values, while some satellite products are column quantities. Station correction should be interpreted carefully.
- For production use, review the weight logic for the target pollutant, emissions regime, meteorology, and local land-use classes.

## References

SmokEye's conservative allocation, ancillary-data weighting, and diffusion-assisted workflow are informed by the following peer-reviewed journal articles and conference proceedings:

- Tobler, W. R. (1979). Smooth pycnophylactic interpolation for geographical regions. *Journal of the American Statistical Association*, 74(367), 519-530. https://doi.org/10.1080/01621459.1979.10481647
- Eicher, C. L., & Brewer, C. A. (2001). Dasymetric mapping and areal interpolation: Implementation and evaluation. *Cartography and Geographic Information Science*, 28(2), 125-138. https://doi.org/10.1559/152304001782173727
- Mennis, J. (2003). Generating surface models of population using dasymetric mapping. *The Professional Geographer*, 55(1), 31-42. https://doi.org/10.1111/0033-0124.10042
- Song, Y., & Ermon, S. (2019). Generative modeling by estimating gradients of the data distribution. *Advances in Neural Information Processing Systems*, 32.
- Ho, J., Jain, A., & Abbeel, P. (2020). Denoising diffusion probabilistic models. *Advances in Neural Information Processing Systems*, 33, 6840-6851.
- Rombach, R., Blattmann, A., Lorenz, D., Esser, P., & Ommer, B. (2022). High-resolution image synthesis with latent diffusion models. *Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition*, 10684-10695. https://doi.org/10.1109/CVPR52688.2022.01042

## License

This project is released under the MIT License. See `LICENSE`.
