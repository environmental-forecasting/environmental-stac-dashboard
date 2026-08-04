"""Tests for map-request build helpers."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.request import (  # noqa: E402
    DEFAULT_COLORMAP,
    build_map_request,
    collections_list,
    recipe_complete,
    resolve_live_colormap,
)


def test_collections_list_normalises_inputs():
    assert collections_list(None) == []
    assert collections_list("") == []
    assert collections_list("a") == ["a"]
    assert collections_list(["a", "", "b"]) == ["a", "b"]


def test_recipe_complete_requires_all_fields():
    assert not recipe_complete(
        collection=None, forecast_start="2024-01-01", variable=0
    )
    assert not recipe_complete(
        collection=["a"], forecast_start=None, variable=0
    )
    assert not recipe_complete(
        collection=["a"], forecast_start="2024-01-01", variable=None
    )
    assert recipe_complete(
        collection=["a"], forecast_start="2024-01-01", variable=0
    )


def test_build_map_request_returns_none_when_incomplete():
    assert (
        build_map_request(
            None,
            collection=None,
            forecast_start="2024-01-01",
            variable=0,
        )
        is None
    )


def test_build_map_request_bumps_revision_and_defaults():
    first = build_map_request(
        None,
        collection="ocean",
        forecast_start="2024-01-01",
        variable="2",
    )
    assert first == {
        "collection": ["ocean"],
        "forecast_start": "2024-01-01",
        "variable": 2,
        "colormap": "blues_r",
        "view_mode": "global_3857",
        "lead": 0,
        "force_stats": False,
        "clear_lock": False,
        "leadtime_only": False,
        "tms_only": False,
        "colormap_only": False,
        "revision": 1,
    }
    second = build_map_request(
        first,
        collection=["ocean"],
        forecast_start="2024-01-01",
        variable=2,
        colormap="viridis",
        view_mode="EPSG6931",
        lead=3,
        force_stats=True,
        clear_lock=True,
        leadtime_only=True,
        tms_only=True,
        colormap_only=True,
    )
    assert second["revision"] == 2
    assert second["colormap"] == "viridis"
    assert second["view_mode"] == "EPSG6931"
    assert second["lead"] == 3
    assert second["force_stats"] is True
    assert second["clear_lock"] is True
    assert second["leadtime_only"] is True
    assert second["tms_only"] is True
    assert second["colormap_only"] is True


def test_resolve_live_colormap_prefers_first_nonempty():
    assert resolve_live_colormap("viridis", "blues_r") == "viridis"
    assert resolve_live_colormap(None, "", "plasma") == "plasma"
    # Pause/confirm: live dropdown wins over a stale map-request blues_r.
    assert (
        resolve_live_colormap("turbo", "turbo", "blues_r") == "turbo"
    )
    assert resolve_live_colormap(None, None, None) == DEFAULT_COLORMAP
