"""Tests for free XYZ basemap catalogue helpers."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.basemap import (  # noqa: E402
    BASEMAP_DARK_MATTER,
    BASEMAP_OSM,
    BASEMAP_POSITRON,
    BASEMAP_VOYAGER,
    DEFAULT_BASEMAP_ID,
    basemap_descriptor,
    list_basemap_options,
    normalise_basemap_id,
)


def test_basemap_catalogue_and_default():
    ids = {opt["value"] for opt in list_basemap_options()}
    assert ids == {
        BASEMAP_VOYAGER,
        BASEMAP_POSITRON,
        BASEMAP_DARK_MATTER,
        BASEMAP_OSM,
    }
    assert DEFAULT_BASEMAP_ID == BASEMAP_VOYAGER
    assert "voyager" in basemap_descriptor()["url"]
    assert "light_all" in basemap_descriptor(BASEMAP_POSITRON)["url"]
    assert "dark_all" in basemap_descriptor(BASEMAP_DARK_MATTER)["url"]
    assert "tile.openstreetmap.org" in basemap_descriptor(BASEMAP_OSM)["url"]
    assert "CARTO" not in basemap_descriptor(BASEMAP_OSM)["attribution"]
    assert normalise_basemap_id("nope") == DEFAULT_BASEMAP_ID
