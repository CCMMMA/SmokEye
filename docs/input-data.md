# Input Data Requirements

Both downscaling methods use the same input files and command-line interface.

## Positional Inputs

```text
input_tif calmet_dat geodat output_tif
```

### `input_tif`

Input pollutant GeoTIFF. The command reads one 1-based band selected with `--input-band`.

Requirements:

- The raster must have a valid CRS.
- Pixel values must be numeric pollutant values.
- Nodata values are skipped when present.

Example:

```bash
--input-band 1
```

### `calmet_dat`

CALMET/CMET meteorology file, or an `.npz` file if `--met-npz` is not supplied.

The binary reader looks for common Fortran-unformatted records:

```text
ZI, TEMPK, USTAR, Z0, U-LEV 1, V-LEV 1, ELEV, ILANDU
```

If the local CALMET layout differs, export meteorological fields to `.npz` and pass:

```bash
--met-npz path/to/met_fields.npz
```

Supported `.npz` field names include:

```text
pblh, ws10, u10, v10, ustar, tempk, z0, elevation_calmet, landuse_calmet
```

Each array must have shape `(ny, nx)` on the `GEO.DAT` grid. If `u10` and `v10` are present, `ws10` is derived automatically.

#### Time Selection

CALMET/CMET files may contain multiple gridded records for the same variable at different model timestamps. SmokEye reads supported records and selects one array per meteorological field.

The default is:

```bash
--calmet-selector last
```

Available selector modes are:

```bash
--calmet-selector first
--calmet-selector last
--calmet-selector mean
```

Use `first` or `last` when the CALMET file has already been trimmed to a short period or when the desired record order is known. Use `mean` when the pollutant raster represents a time average and the meteorological influence should also be averaged over the available records.

If the CALMET integer timestamp for the desired analysis time is known, select the nearest record with:

```bash
--calmet-stamp 2024062811
```

The integer is interpreted only as a CALMET record stamp. SmokEye does not parse it as a calendar date, does not infer time zones, and does not compare it with dates embedded in filenames.

For `.npz` meteorology, there is no internal time selection. The arrays are assumed to have already been selected or averaged for the intended pollutant analysis time.

### `geodat`

CALMET `GEO.DAT` file used to infer the target grid.

The reader attempts to infer:

- CRS, currently with UTM/WGS-84 support.
- `nx`, `ny`.
- `x0`, `y0`.
- `dx`, `dy`.
- origin.
- optional terrain.
- optional land-use.

If a local `GEO.DAT` variant cannot be inferred automatically, create a JSON sidecar:

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

Then pass:

```bash
--geodat-sidecar geodat_grid.json
```

### `output_tif`

Output single-band GeoTIFF. Parent directories are created automatically by the writer.

## Optional Station CSV

Station correction uses:

```bash
--groundtruth-csv path/to/groundtruth.csv
```

The CSV must contain station ID and coordinates:

```csv
ID,LAT,LON,NO2
AQSTN_A1,40.814289,14.267230,9.9736753e-05
AQSTN_B2,40.845249,14.321457,0.00015246817
```

Column matching is case-insensitive. For pollutants other than `NO2`, either name the value column after `--pollutant` or specify it explicitly:

```bash
--groundtruth-value-column PM25
```

`PM25` also accepts `PM2.5` when present.

Station CSV files do not carry a time axis in the SmokEye workflow. If source station data are hourly or sub-hourly, prepare the CSV before running SmokEye so each station row contains the measurement or average corresponding to the pollutant raster and selected CALMET period.

## Inspection Commands

Inspect the target grid:

```bash
python downscale_pollutant.py --inspect-geodat data/geo.dat
```

Inspect CALMET records:

```bash
python downscale_pollutant.py --inspect-calmet data/cmet.dat
```

Inspect station CSV and estimate background:

```bash
python downscale_pollutant.py \
  --pollutant NO2 \
  --inspect-groundtruth examples/groundtruth_example.csv
```

The AI method supports the same inspection commands by adding `--method ai`.
