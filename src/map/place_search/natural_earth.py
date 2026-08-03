"""Natural Earth marine and ice-shelf outlines used to enrich search hits.

This is not a search engine: it only attaches an outline to a hit that came
back from a gazetteer without one.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

from .hits import hit_has_area, normalise_place_name, title_from_label

logger = logging.getLogger(__name__)

ATTRIBUTION = "Natural Earth"
_INDEX_PATH = Path(__file__).resolve().parents[1] / "data" / "ne_outline_index.json"


@lru_cache(maxsize=1)
def _load_index() -> dict[str, dict]:
    """
    Load the shipped outline index, keyed by normalised place name.

    When several features share a name, the one with the largest bounding
    box wins.

    Returns:
        Mapping of lookup key to ``{bbox, geometry, kind, area}``. Empty when
        the index file is missing or unreadable.
    """
    try:
        payload = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load Natural Earth outline index: %s", exc)
        return {}

    by_name: dict[str, dict] = {}
    for feature in payload.get("features") or []:
        names = feature.get("names") or []
        bbox = feature.get("bbox")
        geometry = feature.get("geometry")
        if not names or not isinstance(geometry, dict):
            continue
        area = 0.0
        if isinstance(bbox, list) and len(bbox) >= 4:
            try:
                area = (float(bbox[2]) - float(bbox[0])) * (
                    float(bbox[3]) - float(bbox[1])
                )
            except (TypeError, ValueError):
                area = 0.0
        entry = {
            "bbox": bbox,
            "geometry": geometry,
            "kind": feature.get("kind"),
            "area": area,
        }
        for name in names:
            key = normalise_place_name(name)
            if not key:
                continue
            existing = by_name.get(key)
            if existing is None or area > existing.get("area", 0.0):
                by_name[key] = entry
    return by_name


def lookup_outline(name: str) -> dict | None:
    """
    Look up a Natural Earth outline by place name.

    Args:
        name: Place name such as ``Hudson Bay``.

    Returns:
        ``{bbox, geometry, kind}`` for the place, or None when it is not in
        the index.
    """
    key = normalise_place_name(name)
    if not key:
        return None
    entry = _load_index().get(key)
    if entry is None:
        return None
    return {
        "bbox": entry.get("bbox"),
        "geometry": entry.get("geometry"),
        "kind": entry.get("kind"),
    }


def _name_candidates(hit: dict) -> list[str]:
    """
    Derive name lookup keys from a search hit label.

    Args:
        hit: Search hit dict.

    Returns:
        Candidate names in the order they should be tried.
    """
    label = (hit.get("label") or "").strip()
    if not label:
        return []
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = (value or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(text)

    add(title_from_label(label))
    add(label)
    # Nominatim often embeds the English name between dashes or parentheses.
    head = title_from_label(label)
    for chunk in head.replace("(", ",").replace(")", ",").split(","):
        for piece in chunk.split(" - "):
            add(piece)
    return candidates


def enrich_hit(hit: dict) -> dict:
    """
    Attach a Natural Earth outline when a hit has no usable area geometry.

    Args:
        hit: Search hit dict, which is mutated in place.

    Returns:
        The same hit. ``outline_source`` is set when an outline was added.
    """
    if hit_has_area(hit):
        return hit

    outline = None
    for candidate in _name_candidates(hit):
        outline = lookup_outline(candidate)
        if outline is not None:
            break
    if outline is None:
        # Last resort: any indexed name contained in the label, which covers
        # the long multilingual display names Nominatim returns.
        label_key = normalise_place_name(hit.get("label") or "")
        if label_key:
            best = None
            best_len = 0
            for name, entry in _load_index().items():
                if len(name) < 4:
                    continue
                if name in label_key and len(name) > best_len:
                    best = entry
                    best_len = len(name)
            if best is not None:
                outline = {
                    "bbox": best.get("bbox"),
                    "geometry": best.get("geometry"),
                    "kind": best.get("kind"),
                }
    if outline is None:
        return hit

    geometry = outline.get("geometry")
    bbox = outline.get("bbox")
    if isinstance(geometry, dict) and geometry.get("type"):
        hit["geojson"] = geometry
    if isinstance(bbox, list) and len(bbox) >= 4:
        hit["bbox"] = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
    hit["outline_source"] = "natural_earth"
    kind = outline.get("kind")
    if kind in {"marine", "ice_shelf"} and int(hit.get("zoom") or 14) > 5:
        hit["zoom"] = 5
    return hit
