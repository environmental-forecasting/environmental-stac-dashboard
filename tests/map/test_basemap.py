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
    CARTO_API_KEY_ENV,
    DEFAULT_BASEMAP_ID,
    basemap_descriptor,
    get_carto_api_key,
    list_basemap_options,
    normalise_basemap_id,
)


def test_basemap_catalogue_and_default(monkeypatch):
    monkeypatch.delenv(CARTO_API_KEY_ENV, raising=False)
    ids = {opt["value"] for opt in list_basemap_options()}
    assert ids == {BASEMAP_VOYAGER, BASEMAP_POSITRON, BASEMAP_DARK_MATTER, BASEMAP_OSM}
    assert DEFAULT_BASEMAP_ID == BASEMAP_OSM

    default_desc = basemap_descriptor()
    assert default_desc["id"] == BASEMAP_OSM
    assert "tile.openstreetmap.org" in default_desc["url"]
    assert "CARTO" not in default_desc["attribution"]

    voyager_desc = basemap_descriptor(BASEMAP_VOYAGER)
    assert "voyager" in voyager_desc["url"]
    assert "https://carto.com/attributions" in voyager_desc["attribution"]

    assert normalise_basemap_id("nope") == DEFAULT_BASEMAP_ID


def test_basemap_descriptor_carto_api_key(monkeypatch):
    monkeypatch.delenv(CARTO_API_KEY_ENV, raising=False)
    assert basemap_descriptor(BASEMAP_VOYAGER, api_key="secret-key")["url"].endswith("?key=secret-key")
    assert "?key=" not in basemap_descriptor(BASEMAP_OSM, api_key="secret-key")["url"]

    monkeypatch.setenv(CARTO_API_KEY_ENV, "env-key")
    assert get_carto_api_key() == "env-key"
    assert basemap_descriptor(BASEMAP_VOYAGER)["url"].endswith("?key=env-key")

    monkeypatch.setenv(CARTO_API_KEY_ENV, "   ")
    assert get_carto_api_key() is None
