# icenet-dashboard

This repository contains a dashboard for visualising IceNet forecasts. It is built on top of [Plotly Dash](https://dash.plotly.com/) to serve Cloud Optimized GeoTIFF (COG) files from [icenet-dashboard-preprocessor](https://github.com/icenet-ai/icenet-dashboard-preprocessor) using [icenet-tiler-api](https://github.com/icenet-ai/icenet-tiler-api).

Depends on `icenet-tiler-api` and `icenet-dashboard-preprocessor`.

## Usage

This application is designed to be used in conjunction with [icenet-tiler-api](https://github.com/icenet-ai/icenet-tiler-api).

## Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/icenet-ai/icenet-dashboard.git
cd icenet-dashboard
```

### 2. Install requirements

```bash
pip install -r requirements.txt
```

### 3. Run the applications

```bash
make run
```
Open a browser and navigate to [http://localhost:8001](http://localhost:8001).
