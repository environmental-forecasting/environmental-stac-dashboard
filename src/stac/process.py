import logging
from datetime import datetime as dt
from typing import Any, Iterable

from pystac import Asset, Collection, Item, MediaType
from pystac_client import Client, ItemSearch
from pystac_client.stac_api_io import StacApiIO
from urllib3 import Retry

from .timefmt import parse_stac_datetime, to_stac_datetime

logger = logging.getLogger(__name__)

# Slim Item Search field set for building the forecast date picker.
# Drop geometry and assets so listing many inits stays cheap.
_FORECAST_INIT_FIELDS = {
    "include": [
        "id",
        "datetime",
        "properties.datetime",
        "properties.forecast:reference_time",
        "properties.forecast:end_time",
        "properties.forecast:leadtime_length",
    ],
    "exclude": ["geometry", "bbox", "assets", "links"],
}


def band_rescale_from_asset(
    asset: Asset, band_index: int
) -> tuple[float, float] | None:
    """
    Read colour-scale min/max for a band from Item asset metadata.

    Expects ``forecast:bands`` entries with ``STATISTICS_MINIMUM`` and
    ``STATISTICS_MAXIMUM`` (written at preprocess time). Returns None if
    those tags are missing so the caller can fall back to TiTiler statistics.
    """
    bands = asset.extra_fields.get("forecast:bands") or []
    for band in bands:
        if band.get("index") != band_index:
            continue
        minimum = band.get("STATISTICS_MINIMUM")
        maximum = band.get("STATISTICS_MAXIMUM")
        if minimum is None or maximum is None:
            return None
        return float(minimum), float(maximum)
    return None


class STAC:
    def __init__(self, STAC_FASTAPI_URL: str) -> None:
        # Refer to pystac-client docs:
        # https://pystac-client.readthedocs.io/en/stable/usage.html

        retry = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[502, 503, 504],
            allowed_methods=None,
        )
        stac_api_io = StacApiIO(max_retries=retry)
        self._url = STAC_FASTAPI_URL
        self._catalog = Client.open(STAC_FASTAPI_URL, stac_io=stac_api_io)
        # Cache full Items by (collection_id, forecast:reference_time).
        self._item_cache: dict[tuple[str, str], Item] = {}

    def _search_collection(self, collection_id) -> ItemSearch:
        search = self._catalog.search(collections=[collection_id], max_items=None)
        return search

    def _search_item(
        self, collection_id, item_id, max_items: int | None = None
    ) -> ItemSearch:
        search = self._catalog.search(
            collections=[collection_id], ids=item_id, max_items=max_items
        )
        return search

    def _search_item_by_reference_time(
        self,
        collection_id: str,
        forecast_reference_time: str,
        max_items: int | None = 1,
    ) -> ItemSearch:
        """Search for an item by the ``forecast:reference_time`` STAC property."""
        search = self._catalog.search(
            collections=[collection_id],
            query={"forecast:reference_time": {"eq": forecast_reference_time}},
            max_items=max_items,
        )
        return search

    def get_catalog_collection_ids(
        self, resolve: bool = False
    ) -> Iterable[Collection] | tuple[Collection]:
        # Get all available collections in STAC API
        collections = self._catalog.get_all_collections()
        return tuple(collections) if resolve else collections

    def get_collection_items(self, collection_id, resolve: bool = False):
        collection = self._catalog.get_collection(collection_id)
        items = collection.get_items()
        return tuple(items) if resolve else items

    def get_collection_extents(self, collection_id):
        collection = self._catalog.get_collection(collection_id)
        logger.debug(f"Collection: {collection}")
        temporal_extent = collection.extent.temporal.intervals[0]
        spatial_extent = collection.extent.spatial.bboxes[0]
        return temporal_extent, spatial_extent

    def list_forecast_inits(self, collection_id: str) -> list[dict[str, Any]]:
        """
        List forecast initialisation times for a collection in one slim search.

        Uses the Item Search Fields extension to omit geometry and assets.
        Each entry includes init datetime plus leadtime metadata when present,
        so callers need not fetch each Item again for the date picker.

        Returns:
            Sorted list of dicts with keys:
            ``datetime``, ``reference_time``, ``end_time``, ``leadtime_length``.
        """
        search = self._catalog.search(
            collections=[collection_id],
            fields=_FORECAST_INIT_FIELDS,
            max_items=None,
        )

        inits: list[dict[str, Any]] = []
        for raw in search.items_as_dicts():
            props = raw.get("properties") or {}
            item_dt = self._parse_item_datetime(raw, props)
            if item_dt is None:
                continue

            reference_time = props.get("forecast:reference_time")
            if not reference_time and item_dt is not None:
                reference_time = to_stac_datetime(item_dt)

            leadtime_length = props.get("forecast:leadtime_length")
            if leadtime_length is not None:
                try:
                    leadtime_length = int(leadtime_length)
                except (TypeError, ValueError):
                    leadtime_length = None

            inits.append(
                {
                    "datetime": item_dt,
                    "reference_time": reference_time,
                    "end_time": props.get("forecast:end_time"),
                    "leadtime_length": leadtime_length,
                }
            )

        inits.sort(key=lambda row: row["datetime"])
        return inits

    @staticmethod
    def _parse_item_datetime(raw: dict[str, Any], props: dict[str, Any]) -> dt | None:
        """Best-effort datetime from a slim Item dict."""
        for value in (
            raw.get("datetime"),
            props.get("datetime"),
            props.get("forecast:reference_time"),
        ):
            if not value:
                continue
            try:
                return parse_stac_datetime(value)
            except (TypeError, ValueError):
                continue
        return None

    def get_collection_forecast_init_dates(self, collection_id) -> list[dt]:
        """Return sorted forecast init datetimes (slim Item Search under the hood)."""
        return [row["datetime"] for row in self.list_forecast_inits(collection_id)]

    def get_forecast_item(
        self, collection_id: str, forecast_reference_time: str
    ) -> Item:
        """
        Return the full STAC Item for a forecast init, with per-client caching.

        Repeated calls with the same collection and reference time reuse the
        cached Item (COGs, bands, leadtime) without another HTTP search.
        """
        cache_key = (collection_id, forecast_reference_time)
        cached = self._item_cache.get(cache_key)
        if cached is not None:
            return cached

        search = self._search_item_by_reference_time(
            collection_id, forecast_reference_time
        )
        items = list(search.items())

        if len(items) == 0:
            raise ValueError(
                f"No item found with forecast:reference_time = "
                f"{forecast_reference_time} in collection {collection_id}."
            )
        if len(items) > 1:
            raise ValueError(
                f"Multiple items found with forecast:reference_time = "
                f"{forecast_reference_time} in collection {collection_id}."
            )

        item = items[0]
        self._item_cache[cache_key] = item
        return item

    def get_item(self, collection_id: str, forecast_reference_time: str) -> Item:
        """Load a forecast Item (cached). Prefer ``get_forecast_item`` in new code."""
        return self.get_forecast_item(collection_id, forecast_reference_time)

    def clear_item_cache(self) -> None:
        """Drop cached forecast Items (e.g. after a catalog refresh)."""
        self._item_cache.clear()

    def get_item_properties(self, collection_id: str, forecast_reference_time: str):
        item = self.get_forecast_item(collection_id, forecast_reference_time)
        return item.properties

    def get_item_leadtime(self, collection_id: str, forecast_reference_time: str) -> str:
        properties = self.get_item_properties(collection_id, forecast_reference_time)
        return properties["forecast:leadtime_length"]

    def get_item_extents(self, collection_id: str, forecast_reference_time: str):
        item = self.get_forecast_item(collection_id, forecast_reference_time)
        item_props = item.properties
        temporal_extent = (
            item_props["forecast:reference_time"],
            item_props["forecast:end_time"],
        )
        temporal_extent = [
            parse_stac_datetime(iso_string) for iso_string in temporal_extent
        ]
        # Convert to match datetime like `get_collection_extents`.
        spatial_extent = item.bbox
        return temporal_extent, spatial_extent

    def get_item_cogs(self, collection_id: str, forecast_reference_time: str):
        item = self.get_forecast_item(collection_id, forecast_reference_time)
        assets = item.get_assets(media_type=MediaType.COG, role="data")
        return assets

    def get_asset_band_props(
        self, collection_id: str, forecast_reference_time: str, asset_id
    ):
        item = self.get_forecast_item(collection_id, forecast_reference_time)
        asset = item.assets.get(asset_id)

        key = "forecast:bands"
        if asset is not None and key in asset.extra_fields:
            return asset.extra_fields[key]

        return None

    def get_asset_bands(
        self, collection_id: str, forecast_reference_time: str, asset_id
    ) -> dict[str, int]:
        asset_band_props = self.get_asset_band_props(
            collection_id, forecast_reference_time, asset_id
        )
        bands = {band["name"]: band["index"] for band in asset_band_props}
        return bands

    def get_band_rescale(
        self, asset: Asset, band_index: int
    ) -> tuple[float, float] | None:
        """
        Return (min, max) for a COG band from asset metadata, or None.

        When None, callers should fall back to TiTiler ``/cog/statistics``.
        """
        return band_rescale_from_asset(asset, band_index)
