"""Tests for place search and Natural Earth enrichment."""

import sys
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.geocode import parse_lon_lat  # noqa: E402
from map.place_search import PlaceSearch, hit_has_area  # noqa: E402
from map.place_search.natural_earth import enrich_hit, lookup_outline  # noqa: E402


def test_parse_lon_lat_accepts_hemisphere_suffixes():
    assert parse_lon_lat("60.0 N, 86.0 W") == (-86.0, 60.0)


def test_parse_lon_lat_rejects_plain_text():
    assert parse_lon_lat("Hudson Bay") is None


def test_natural_earth_lookup_hudson_bay():
    outline = lookup_outline("Hudson Bay")
    assert outline is not None
    assert outline["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert outline["bbox"] is not None
    west, south, east, north = outline["bbox"]
    assert east - west > 5
    assert north - south > 5


def test_enrich_hit_attaches_ne_outline_for_point_only_bay():
    hit = {
        "label": "Hudson Bay, Canada",
        "lon": -86.0,
        "lat": 60.0,
        "zoom": 5,
        "source": "nominatim",
        "geojson": {"type": "Point", "coordinates": [-86.0, 60.0]},
    }
    assert not hit_has_area(hit)
    enriched = enrich_hit(hit)
    assert enriched.get("outline_source") == "natural_earth"
    assert hit_has_area(enriched)
    assert enriched["geojson"]["type"] in {"Polygon", "MultiPolygon"}


def test_enrich_hit_finds_english_name_inside_multilingual_label():
    # Leading escapes stand in for the Inuktitut name Nominatim returns first.
    hit = {
        "label": "\u1472\u14c7\u1585\u14f1\u14a1 - Hudson Bay - Baie d'Hudson, Canada",
        "lon": -86.0,
        "lat": 60.0,
        "zoom": 5,
        "source": "nominatim",
        "geojson": {"type": "Point", "coordinates": [-86.0, 60.0]},
    }
    enriched = enrich_hit(hit)
    assert enriched.get("outline_source") == "natural_earth"
    assert enriched["geojson"]["type"] in {"Polygon", "MultiPolygon"}


def test_enrich_hit_skips_when_area_already_present():
    hit = {
        "label": "Lake Superior",
        "lon": -88.0,
        "lat": 48.0,
        "zoom": 7,
        "source": "nominatim",
        "bbox": [-92.0, 46.0, -84.0, 49.0],
        "geojson": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-92.0, 46.0],
                    [-84.0, 46.0],
                    [-84.0, 49.0],
                    [-92.0, 49.0],
                    [-92.0, 46.0],
                ]
            ],
        },
    }
    enriched = enrich_hit(dict(hit))
    assert "outline_source" not in enriched
    assert enriched["geojson"] == hit["geojson"]


def test_place_search_uses_nominatim_for_all_modes():
    finder = PlaceSearch()
    fake = [
        {
            "label": "Demo",
            "lon": 1.0,
            "lat": 2.0,
            "zoom": 10,
            "source": "nominatim",
        }
    ]
    modes = ("global_3857", "global_leaflet", "globe_cesium", "EPSG6931", "EPSG6932")
    for mode in modes:
        with (
            patch("map.place_search.facade.nominatim.search", return_value=fake) as nom,
            patch("map.place_search.facade.enrich_hit", side_effect=lambda h: h),
        ):
            hits = finder.search("Demo", mode=mode, enrich=False)
        assert hits == fake
        nom.assert_called_once()


def test_attribution_mentions_natural_earth_when_enriched():
    finder = PlaceSearch()
    text = finder.attribution_for_hits(
        [
            {
                "source": "nominatim",
                "outline_source": "natural_earth",
            }
        ]
    )
    assert "Nominatim" in text
    assert "Natural Earth" in text
