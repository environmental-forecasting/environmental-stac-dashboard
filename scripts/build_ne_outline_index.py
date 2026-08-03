"""Build the shipped Natural Earth marine and ice outline index.

Downloads Natural Earth 10m GeoJSON from the natural-earth-vector mirror and
writes ``src/map/data/ne_outline_index.json``, which maps place names to the
polygons used to enrich search hits.

Usage (from environmental-stac-dashboard/):

    python scripts/build_ne_outline_index.py
"""

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "src" / "map" / "data" / "ne_outline_index.json"

_SOURCES = (
    (
        "marine",
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_geography_marine_polys.geojson",
        "ne_10m_geography_marine_polys",
    ),
    (
        "ice_shelf",
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_antarctic_ice_shelves_polys.geojson",
        "ne_10m_antarctic_ice_shelves_polys",
    ),
)


def _round_coords(obj, nd: int = 4):
    """Round every coordinate in a nested list to ``nd`` decimal places."""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(x), nd) for x in obj]
        return [_round_coords(x, nd) for x in obj]
    return obj


def _bbox_of(geom: dict) -> list[float] | None:
    """Return ``[west, south, east, north]`` for a geometry, or None."""
    coords: list[list[float]] = []

    def walk(node):
        if isinstance(node, list):
            if node and isinstance(node[0], (int, float)):
                coords.append(node)
            else:
                for child in node:
                    walk(child)

    walk(geom.get("coordinates"))
    if not coords:
        return None
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def _fetch(url: str) -> dict:
    """Download and parse a GeoJSON document."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "environmental-stac-dashboard/1.0 (build ne index)"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    """Fetch every source layer and write the combined outline index."""
    entries: list[dict] = []
    layers: list[str] = []
    for kind, url, layer_name in _SOURCES:
        layers.append(layer_name)
        collection = _fetch(url)
        for feature in collection.get("features") or []:
            props = feature.get("properties") or {}
            names = set()
            for key in ("name", "name_en", "label", "namealt"):
                value = (props.get(key) or "").strip()
                if value:
                    names.add(value)
            if not names:
                continue
            geometry = feature.get("geometry")
            if not geometry or geometry.get("type") in (None, "Point", "MultiPoint"):
                continue
            geometry = {
                "type": geometry["type"],
                "coordinates": _round_coords(geometry["coordinates"]),
            }
            bbox = _bbox_of(geometry)
            entries.append(
                {
                    "names": sorted(names),
                    "kind": kind,
                    "bbox": [round(x, 4) for x in bbox] if bbox else None,
                    "geometry": geometry,
                }
            )

    payload = {
        "source": "Natural Earth 10m",
        "layers": layers,
        "attribution": "Natural Earth",
        "features": entries,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes, {len(entries)} features)")


if __name__ == "__main__":
    main()
