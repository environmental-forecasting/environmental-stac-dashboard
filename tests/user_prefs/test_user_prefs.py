"""Tests for browser-persisted user map defaults."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from user_prefs import (  # noqa: E402
    DEFAULT_VIEW_MODE,
    display_style_seed_from_prefs,
    merge_user_prefs,
    normalise_user_prefs,
    preferred_collections,
    preferred_in,
)


def test_normalise_and_preferred():
    prefs = normalise_user_prefs(
        {
            "collection": "only-one",
            "forecast_start": "2024-06-01",
            "variable": "2",
            "colormap": "viridis",
            "view_mode": "epsg3031",
            "colorbar": {"vmin": "0.5", "vmax": "1.5", "locked": True},
            "noise": True,
        }
    )
    assert prefs["collection"] == ["only-one"]
    assert prefs["variable"] == 2
    assert prefs["colorbar"]["locked"] is True
    assert "noise" not in prefs
    assert preferred_collections(prefs, {"only-one", "x"}) == ["only-one"]
    assert preferred_collections(prefs, {"x"}) is None
    assert preferred_in(prefs, "forecast_start", {"2024-06-01"}) == "2024-06-01"
    assert preferred_in(prefs, "variable", {1, 2}) == 2
    assert preferred_in(prefs, "colormap", ["viridis"]) == "viridis"
    assert preferred_in(prefs, "view_mode", ["global_3857"]) is None


def test_merge_user_prefs():
    assert merge_user_prefs(colormap="blues_r", view_mode=DEFAULT_VIEW_MODE) is None
    assert merge_user_prefs(collection=None, colormap=None) is None

    cleared = merge_user_prefs(
        collection=None,
        forecast_start="2024-01-01",
        variable=1,
        colormap="viridis",
        view_mode=DEFAULT_VIEW_MODE,
        display_style={"locked": False},
    )
    assert cleared == {"colormap": "viridis"}

    locked = merge_user_prefs(
        collection=["a"],
        forecast_start="2024-01-01",
        variable=1,
        colormap="viridis",
        view_mode="globe_cesium",
        display_style={"vmin": 0.2, "vmax": 0.8, "locked": True},
    )
    assert locked["view_mode"] == "globe_cesium"
    assert locked["colorbar"] == {"vmin": 0.2, "vmax": 0.8, "locked": True}
    assert "colorbar" not in merge_user_prefs(
        collection=["a"],
        colormap="viridis",
        display_style={"vmin": 0, "vmax": 1, "locked": False},
    )


def test_display_style_seed_from_prefs():
    assert display_style_seed_from_prefs({}) is None
    seed = display_style_seed_from_prefs(
        {
            "colormap": "viridis",
            "colorbar": {"vmin": 1, "vmax": 2, "locked": True},
        }
    )
    assert seed["colormap"] == "viridis"
    assert seed["vmin"] == 1.0
    assert seed["locked"] is True
    assert display_style_seed_from_prefs({"colormap": "plasma"})["locked"] is False
