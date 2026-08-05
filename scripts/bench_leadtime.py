#!/usr/bin/env python3
"""Benchmark leadtime scrub latency against a running dashboard.

Measures time from setting the leadtime slider until ForecastMap reports tiles
ready, plus first /cog/tiles/ response timing. Writes median JSON under
bench/results/{label}.json for before/after commit comparisons.

Setup (host, not the dashboard image)::

    pip install playwright
    playwright install chromium   # or set BENCH_CHROMIUM=/path/to/chromium

Usage::

    python scripts/bench_leadtime.py --label baseline
    python scripts/bench_leadtime.py --label after-playback --compare baseline
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.stderr.write(
        "Install Playwright on the host: pip install playwright "
        "&& playwright install chromium\n"
    )
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "bench" / "results"

DEFAULT_URL = "http://127.0.0.1/"
DEFAULT_COLLECTION = "icenet_0.2_north"
DEFAULT_DATE = "2026-06-19"
READY_TIMEOUT_MS = 15000


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _chromium_path() -> str | None:
    for key in ("BENCH_CHROMIUM", "CHROMIUM_PATH"):
        path = os.environ.get(key)
        if path and Path(path).exists():
            return path
    for candidate in (
        "/snap/bin/chromium",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def _wait_tiles_ready(page, timeout_ms: int = READY_TIMEOUT_MS) -> float:
    """Return ms until ForecastMap.isTilesReady(), or timeout_ms if never ready."""
    start = time.perf_counter()
    deadline = start + timeout_ms / 1000.0
    while time.perf_counter() < deadline:
        ready = page.evaluate(
            """() => !!(window.ForecastMap && window.ForecastMap.isTilesReady
                && window.ForecastMap.isTilesReady())"""
        )
        if ready:
            return (time.perf_counter() - start) * 1000.0
        page.wait_for_timeout(50)
    return float(timeout_ms)


def _set_leadtime(page, lead: int) -> None:
    page.evaluate(
        """(lead) => {
            window.dash_clientside.set_props("leadtime-slider", {value: lead});
        }""",
        lead,
    )


def _run_once(
    page,
    *,
    base_url: str,
    collection: str,
    init_date: str,
    max_lead: int,
    repeats: int,
) -> dict:
    cog_meta: list[dict] = []

    def on_response(response) -> None:
        url = response.url
        if "/cog/tiles/" not in url:
            return
        cog_meta.append(
            {
                "t": time.perf_counter(),
                "status": response.status,
                "url": url,
            }
        )

    page.on("response", on_response)
    page.goto(base_url, wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(1500)
    page.evaluate(
        """(collection) => {
            window.dash_clientside.set_props("collections-dropdown", {
                value: [collection],
            });
        }""",
        collection,
    )
    page.wait_for_timeout(2500)
    page.evaluate(
        """(date) => {
            window.dash_clientside.set_props("forecast-init-date-picker", {
                value: date,
            });
        }""",
        init_date,
    )
    page.wait_for_timeout(4000)
    _wait_tiles_ready(page)
    page.wait_for_timeout(500)

    step_runs: dict[int, list[dict]] = {lead: [] for lead in range(max_lead + 1)}

    for _ in range(repeats):
        for lead in range(max_lead + 1):
            before_n = len(cog_meta)
            t0 = time.perf_counter()
            page.evaluate(
                """() => {
                    if (window.ForecastMap && window.ForecastMap.setTilesReady) {
                        window.ForecastMap.setTilesReady(false);
                    }
                }"""
            )
            _set_leadtime(page, lead)
            t_ready = _wait_tiles_ready(page)
            t_first = None
            fails = 0
            count = 0
            for item in cog_meta[before_n:]:
                count += 1
                if item["status"] >= 400:
                    fails += 1
                if t_first is None and item["status"] < 400:
                    t_first = (item["t"] - t0) * 1000.0
            step_runs[lead].append(
                {
                    "t_slider_to_ready_ms": t_ready,
                    "t_first_cog_tile_ms": t_first,
                    "cog_tile_count": count,
                    "cog_tile_fails": fails,
                }
            )
            page.wait_for_timeout(200)

    burst_hits = 0
    burst_leads = list(range(max_lead + 1))
    for lead in burst_leads:
        before_n = len(cog_meta)
        _set_leadtime(page, lead)
        # Short window: counts frames that get at least one tile before the next tick.
        page.wait_for_timeout(250)
        if any(item["status"] < 400 for item in cog_meta[before_n:]):
            burst_hits += 1

    page.remove_listener("response", on_response)

    steps = []
    for lead in range(max_lead + 1):
        runs = step_runs[lead]
        steps.append(
            {
                "lead": lead,
                "t_slider_to_ready_ms": _median(
                    [r["t_slider_to_ready_ms"] for r in runs]
                ),
                "t_first_cog_tile_ms": _median(
                    [
                        r["t_first_cog_tile_ms"]
                        for r in runs
                        if r["t_first_cog_tile_ms"] is not None
                    ]
                ),
                "cog_tile_count": _median(
                    [float(r["cog_tile_count"]) for r in runs]
                ),
                "cog_tile_fails": _median(
                    [float(r["cog_tile_fails"]) for r in runs]
                ),
                "runs": runs,
            }
        )

    ready_vals = [
        s["t_slider_to_ready_ms"]
        for s in steps
        if s["t_slider_to_ready_ms"] is not None
    ]
    first_vals = [
        s["t_first_cog_tile_ms"]
        for s in steps
        if s["t_first_cog_tile_ms"] is not None
    ]
    return {
        "steps": steps,
        "summary": {
            "median_t_slider_to_ready_ms": _median(ready_vals),
            "median_t_first_cog_tile_ms": _median(first_vals),
            "burst_frames_with_tile": burst_hits,
            "burst_frames_total": len(burst_leads),
        },
    }


def _compare(current: dict, baseline_path: Path) -> None:
    baseline = json.loads(baseline_path.read_text())
    cur = current["summary"]
    base = baseline.get("summary", {})
    print("\nCompare to", baseline_path.name)
    for key in (
        "median_t_slider_to_ready_ms",
        "median_t_first_cog_tile_ms",
    ):
        a, b = cur.get(key), base.get(key)
        if a is None or b is None:
            print(f"  {key}: n/a")
            continue
        delta = a - b
        pct = (delta / b * 100.0) if b else 0.0
        print(f"  {key}: {b:.0f} to {a:.0f} ms ({delta:+.0f}, {pct:+.0f}%)")
    print(
        "  burst_frames_with_tile:",
        f"{base.get('burst_frames_with_tile')} to {cur.get('burst_frames_with_tile')}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--label", required=True, help="Result file stem")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--date", default=DEFAULT_DATE)
    parser.add_argument("--max-lead", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--compare",
        metavar="LABEL",
        help="Print deltas against bench/results/LABEL.json",
    )
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{args.label}.json"

    launch_kwargs: dict = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }
    chrome = _chromium_path()
    if chrome:
        launch_kwargs["executable_path"] = chrome

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        try:
            payload = _run_once(
                page,
                base_url=args.url,
                collection=args.collection,
                init_date=args.date,
                max_lead=args.max_lead,
                repeats=args.repeats,
            )
        finally:
            browser.close()

    result = {
        "label": args.label,
        "url": args.url,
        "collection": args.collection,
        "date": args.date,
        "max_lead": args.max_lead,
        "repeats": args.repeats,
        **payload,
    }
    out_path.write_text(json.dumps(result, indent=2) + "\n")
    summary = result["summary"]
    print(f"Wrote {out_path}")
    print(
        "median_t_slider_to_ready_ms=",
        summary.get("median_t_slider_to_ready_ms"),
        "median_t_first_cog_tile_ms=",
        summary.get("median_t_first_cog_tile_ms"),
        "burst=",
        f"{summary.get('burst_frames_with_tile')}/{summary.get('burst_frames_total')}",
    )
    if args.compare:
        base_path = RESULTS_DIR / f"{args.compare}.json"
        if not base_path.exists():
            print(f"Missing baseline {base_path}", file=sys.stderr)
            return 1
        _compare(result, base_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
