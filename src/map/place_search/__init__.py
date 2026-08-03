"""Place search with Natural Earth outline enrichment."""

from .facade import PlaceSearch, place_search, search
from .hits import hit_has_area

__all__ = [
    "PlaceSearch",
    "hit_has_area",
    "place_search",
    "search",
]
