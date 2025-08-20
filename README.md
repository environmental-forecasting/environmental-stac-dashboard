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

