# Agent Guidance

## High-Quality Software Engineering

- Preserve the public command-line behavior of `downscale_pollutant_geodat_calmet.py` and `downscale_pollutant_geodat_calmet_ai.py` unless a change is explicitly requested.
- Keep the top-level scripts as thin compatibility entry points. Put reusable implementation in the `smokeye` package.
- Do not duplicate source code between deterministic and AI workflows. Prefer shared functions, strategy parameters, and small method-specific modules.
- Keep changes cohesive, readable, and scoped to the requested behavior.
- Favor explicit data flow over monkey-patching or hidden global mutation.
- Validate scientific workflow changes with syntax checks and, when data is available, comparable deterministic and AI command runs.
- Update README and relevant files under `docs/` whenever behavior, layout, command options, outputs, or development workflow changes.
- Preserve reproducibility for model-assisted paths; any stochastic component must use a deliberate fixed seed or expose a documented configuration.
- Treat geospatial metadata, CRS handling, raster transforms, nodata values, and conservation validation as correctness-critical.
