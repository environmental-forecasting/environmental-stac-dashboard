# environmental-stac-dashboard

This repository contains a dashboard for visualising earth system forecast predictions. It is built on top of [Plotly Dash](https://dash.plotly.com/) to serve Cloud Optimized GeoTIFF (COG) files from [environmental-stac-generator](https://github.com/environmental-forecasting/environmental-stac-generator) using services deployed by the main orchestrator repo [environmental-stac-orchestrator](https://github.com/environmental-forecasting/environmental-stac-orchestrator).

## Usage

> [!WARNING]
> This application is not designed to be run independently, it should be deployed in conjunction with [environmental-stac-orchestrator](https://github.com/environmental-forecasting/environmental-stac-orchestrator).

## Installation and Setup

As warned, this is not meant to be run independently, but you can for development/testing by following these steps.

### 1. Clone the repository

```bash
git clone https://github.com/environmental-forecasting/environmental-stac-dashboard.git
cd environmental-stac-dashboard
```

### 2. Install requirements

```bash
pip install -r requirements.txt
```

### 3. Run the applications

```bash
make run
```
Open a browser and navigate to [http://localhost:8005](http://localhost:8005).

### Leadtime scrub benchmark

With the full orchestrator stack running, measure leadtime scrub latency (Playwright + Chromium on the host):

```bash
pip install -r scripts/requirements-bench.txt
python3 scripts/bench_leadtime.py --label baseline
python3 scripts/bench_leadtime.py --label after-change --compare baseline
```

Results land in `bench/results/` (gitignored). Optional env: `BENCH_URL`, `BENCH_CHROMIUM`.

Example summary line:

```text
median_t_slider_to_ready_ms= 393 median_t_first_cog_tile_ms= 426 burst= 0/11
```

- **`median_t_slider_to_ready_ms`** - Median time from setting the leadtime slider until `ForecastMap.isTilesReady()` is true. End-to-end scrub delay (Dash callbacks, new tile URLs, OpenLayers fetch/decode, ready flag).
- **`median_t_first_cog_tile_ms`** - Median time until the first successful TiTiler `/cog/tiles/` response after that slider change (network/tiler path only; not "map fully painted").
- **`burst= hits/total`** - Separate stress pass: jump through leads 0-`max-lead` with only 250 ms between each; counts how many leads got at least one successful COG tile in that window. Low values (e.g. `0/11`) mean rapid scrub paints almost nothing before the next jump.

Defaults: collection `icenet_0.2_north`, init date `2026-06-19`, leads 0-10, 3 repeats. Compare runs with `--compare baseline` after changes.

## Documentation

Docs can be built with:

```bash
make docs-install
make docs
```

Related: [environmental-stac-orchestrator](https://github.com/environmental-forecasting/environmental-stac-orchestrator), [environmental-stac-generator](https://github.com/environmental-forecasting/environmental-stac-generator).

