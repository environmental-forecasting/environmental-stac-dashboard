---
icon: lucide/code
---

# Local development

You can run the app alone for development/testing; full forecast visualisation needs the orchestrator services (STAC API, tiler, file server).

## Clone and install

```bash
git clone https://github.com/environmental-forecasting/environmental-stac-dashboard.git
cd environmental-stac-dashboard
pip install -r requirements.txt
```

## Run

```bash
make run
```

Open [http://localhost:8005](http://localhost:8005).

For the full stack, use [environmental-stac-orchestrator](https://github.com/environmental-forecasting/environmental-stac-orchestrator) (`make dev`).
