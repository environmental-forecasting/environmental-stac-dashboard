"""Tests for listing forecast variables without a full Item download."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from stac.process import STAC  # noqa: E402


def _data_cog_asset(*, bands: list[dict], with_href: bool = True) -> dict:
    asset = {
        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "roles": ["data"],
        "forecast:bands": bands,
    }
    if with_href:
        asset["href"] = "https://example.invalid/forecast.tif"
    return asset


def test_bands_from_asset_dicts_reads_forecast_bands():
    assets = {
        "forecast": _data_cog_asset(
            bands=[
                {"name": "t2m", "index": 1},
                {"name": "msl", "index": 2},
            ],
            with_href=False,
        )
    }
    assert STAC._bands_from_asset_dicts(assets) == {"t2m": 1, "msl": 2}


def test_bands_from_asset_dicts_skips_non_data_assets():
    assets = {
        "thumbnail": {
            "type": "image/png",
            "roles": ["thumbnail"],
            "forecast:bands": [{"name": "ignored", "index": 1}],
        },
        "forecast": _data_cog_asset(
            bands=[{"name": "t2m", "index": 1}],
            with_href=False,
        ),
    }
    assert STAC._bands_from_asset_dicts(assets) == {"t2m": 1}


def test_list_forecast_bands_uses_slim_search_then_cache():
    stac = object.__new__(STAC)
    stac._item_cache = {}
    stac._bands_cache = {}
    stac._catalog = MagicMock()
    search = MagicMock()
    search.items_as_dicts.return_value = [
        {
            "id": "item-1",
            "assets": {
                "forecast": _data_cog_asset(
                    bands=[{"name": "t2m", "index": 1}],
                    with_href=False,
                )
            },
        }
    ]
    stac._catalog.search.return_value = search

    first = stac.list_forecast_bands("col", "2024-01-01T00:00:00Z")
    second = stac.list_forecast_bands("col", "2024-01-01T00:00:00Z")

    assert first == {"t2m": 1}
    assert second == first
    stac._catalog.search.assert_called_once()
    call_kwargs = stac._catalog.search.call_args.kwargs
    assert "assets.*.href" in call_kwargs["fields"]["exclude"]


def test_list_forecast_bands_prefers_item_cache():
    stac = object.__new__(STAC)
    stac._bands_cache = {}
    stac._catalog = MagicMock()

    asset = MagicMock()
    asset.extra_fields = {
        "forecast:bands": [{"name": "msl", "index": 3}],
    }
    item = MagicMock()
    item.get_assets.return_value = {"forecast": asset}
    stac._item_cache = {("col", "2024-01-01T00:00:00Z"): item}

    bands = stac.list_forecast_bands("col", "2024-01-01T00:00:00Z")

    assert bands == {"msl": 3}
    stac._catalog.search.assert_not_called()
