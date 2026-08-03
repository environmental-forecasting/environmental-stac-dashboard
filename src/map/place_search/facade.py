"""Place-search facade: Nominatim lookup plus Natural Earth outlines."""

from . import nominatim
from .natural_earth import enrich_hit

_ATTRIBUTION = {
    "nominatim": nominatim.ATTRIBUTION,
    "coords": "",
}


class PlaceSearch:
    """Global Nominatim place search with optional Natural Earth outlines."""

    def search(
        self,
        query: str,
        *,
        mode: str | None = None,
        limit: int = 5,
        enrich: bool = True,
    ) -> list[dict]:
        """
        Search for a place by name.

        Every view mode shares one gazetteer by design, so the polar tile
        matrix views search the same global index as the Web Mercator views.

        Args:
            query: Free-text place name.
            mode: Current view mode. Accepted so call sites can pass it, but
                it does not change which provider is used.
            limit: Maximum number of hits to return.
            enrich: Whether to attach Natural Earth outlines to hits that
                come back as a bare point.

        Returns:
            Hits shaped as ``{label, lon, lat, zoom, source, bbox?, geojson?,
            outline_source?}``.
        """
        del mode
        hits = nominatim.search(query, limit=limit)

        if enrich:
            hits = [enrich_hit(dict(hit)) for hit in hits]
        return hits

    def attribution_for_hits(self, hits: list[dict]) -> str:
        """
        Build a short status-line credit for a result set.

        Args:
            hits: Hits currently shown in the suggestion list.

        Returns:
            Credit text, or an empty string when there is nothing to credit.
        """
        if not hits:
            return ""
        sources = {hit.get("source") for hit in hits if hit.get("source")}
        parts = [
            _ATTRIBUTION[src]
            for src in sources
            if src in _ATTRIBUTION and _ATTRIBUTION[src]
        ]
        if any(hit.get("outline_source") == "natural_earth" for hit in hits):
            parts.append("Natural Earth outline")
        seen: set[str] = set()
        ordered: list[str] = []
        for part in parts:
            if part and part not in seen:
                seen.add(part)
                ordered.append(part)
        return " | ".join(ordered)


_DEFAULT = PlaceSearch()


def place_search() -> PlaceSearch:
    """Return the shared PlaceSearch facade."""
    return _DEFAULT


def search(
    query: str,
    *,
    mode: str | None = None,
    limit: int = 5,
    enrich: bool = True,
) -> list[dict]:
    """
    Search for a place using the shared facade.

    Args:
        query: Free-text place name.
        mode: Current view mode, accepted for call-site convenience.
        limit: Maximum number of hits to return.
        enrich: Whether to attach Natural Earth outlines.

    Returns:
        List of search hits.
    """
    return _DEFAULT.search(query, mode=mode, limit=limit, enrich=enrich)
