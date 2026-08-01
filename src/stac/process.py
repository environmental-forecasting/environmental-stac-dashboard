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
        # Cache forecast init rows by collection_id (summaries or slim search).
        self._forecast_inits_cache: dict[str, list[dict[str, Any]]] = {}

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
        List forecast initialisation times for a collection.

        Prefers Collection summaries (``forecast:reference_time`` plus a single
        shared ``forecast:leadtime_length``) so the date picker needs only
        ``GET /collections/{id}``. Falls back to a slim Item Search when
        summaries are missing or leadtime lengths are not uniform.

        Results are cached per collection on this client so switching
        selection back and forth does not repeat the API call.

        Returns:
            Sorted list of dicts with keys:
            ``datetime``, ``reference_time``, ``end_time``, ``leadtime_length``.
        """
        cached = self._forecast_inits_cache.get(collection_id)
        if cached is not None:
            return cached

        from_summaries = self._list_forecast_inits_from_summaries(collection_id)
        inits = (
            from_summaries
            if from_summaries is not None
            else self._list_forecast_inits_from_search(collection_id)
        )
        self._forecast_inits_cache[collection_id] = inits
        return inits

    def _list_forecast_inits_from_summaries(
        self, collection_id: str
    ) -> list[dict[str, Any]] | None:
        """
        Build init rows from Collection summaries, or None to fall back.

        Requires ``forecast:reference_time`` and exactly one
        ``forecast:leadtime_length`` value so each init can get an end date
        without listing Items.
        """
        try:
            collection = self._catalog.get_collection(collection_id)
        except Exception as e:
            logger.warning(
                "Could not load collection %s for summaries: %s", collection_id, e
            )
            return None

        summaries = collection.summaries
        if summaries is None or summaries.is_empty():
            return None

        summary_dict = summaries.to_dict()
        reference_times = summary_dict.get("forecast:reference_time") or []
        if not isinstance(reference_times, list) or not reference_times:
            return None

        leadtime_values = summary_dict.get("forecast:leadtime_length") or []
        if not isinstance(leadtime_values, list):
            leadtime_values = [leadtime_values]

        leadtime_lengths: list[int] = []
        for value in leadtime_values:
            try:
                leadtime_lengths.append(int(value))
            except (TypeError, ValueError):
                continue

        # Multiple different leadtime lengths cannot be mapped per init from
        # summaries alone; fall back to Item Search.
        if len(set(leadtime_lengths)) != 1:
            logger.debug(
                "Collection %s summaries lack a single leadtime length; "
                "falling back to Item Search",
                collection_id,
            )
            return None

        leadtime_length = leadtime_lengths[0]
        inits: list[dict[str, Any]] = []
        for reference_time in reference_times:
            try:
                item_dt = parse_stac_datetime(reference_time)
            except (TypeError, ValueError):
                logger.warning(
                    "Skipping invalid forecast:reference_time in summaries: %s",
                    reference_time,
                )
                continue
            inits.append(
                {
                    "datetime": item_dt,
                    "reference_time": reference_time,
                    "end_time": None,
                    "leadtime_length": leadtime_length,
                }
            )

        if not inits:
            return None

        inits.sort(key=lambda row: row["datetime"])
        logger.debug(
            "Loaded %s forecast inits for %s from Collection summaries",
            len(inits),
            collection_id,
        )
        return inits

    def _list_forecast_inits_from_search(
        self, collection_id: str
    ) -> list[dict[str, Any]]:
        """List forecast inits via a slim Item Search (Fields extension)."""
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
        """Drop cached Items and forecast inits (e.g. after a catalog refresh)."""
        self._item_cache.clear()
        self._forecast_inits_cache.clear()

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
