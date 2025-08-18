# environmental-stac-dashboard

This repository contains a dashboard for visualising earth system forecast predictions. It is built on top of [Plotly Dash](https://dash.plotly.com/) to serve Cloud Optimized GeoTIFF (COG) files from [environmental-stac-generator](https://github.com/environmental-forecasting/environmental-stac-generator) using [icenet-tiler-api](https://github.com/icenet-ai/icenet-tiler-api).

Depends on `icenet-tiler-api` and `environmental-stac-generator`.

## Usage

This application is designed to be used in conjunction with [icenet-tiler-api](https://github.com/icenet-ai/icenet-tiler-api).

## Installation and Setup

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
