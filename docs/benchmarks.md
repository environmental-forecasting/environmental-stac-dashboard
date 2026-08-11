---
icon: lucide/gauge
---

# Leadtime scrub benchmark

With the full orchestrator stack running, measure leadtime scrub latency (Playwright + Chromium on the host):

```bash
pip install -r scripts/requirements-bench.txt
python3 scripts/bench_leadtime.py --label baseline
python3 scripts/bench_leadtime.py --label after-change --compare baseline
```

Results land in `bench/results/` (gitignored). Optional env: `BENCH_URL`, `BENCH_CHROMIUM`.

## Example summary line

```text
median_t_slider_to_ready_ms= 393 median_t_first_cog_tile_ms= 426 burst= 0/11
```

| Metric | Meaning |
| ------ | ------- |
| `median_t_slider_to_ready_ms` | Median time from setting the leadtime slider until `ForecastMap.isTilesReady()` is true. End-to-end scrub delay (Dash callbacks, new tile URLs, OpenLayers fetch/decode, ready flag). |
| `median_t_first_cog_tile_ms` | Median time until the first successful titiler-pgstac Item tile response after that slider change (network/tiler path only; not "map fully painted"). |
| `burst= hits/total` | Separate stress pass: jump through leads 0 to `max-lead` with only 250 ms between each; counts how many leads got at least one successful COG tile in that window. Low values (e.g. `0/11`) mean rapid scrub paints almost nothing before the next jump. |

Defaults: collection `icenet_0.2_north`, init date `2026-06-19`, leads 0 to 10, 3 repeats. Compare runs with `--compare baseline` after changes.
