import logging
import os
from datetime import datetime as dt
from typing import Any, Iterable

import diskcache
from pystac import Asset, Collection, Item, MediaType
from pystac_client import Client, ItemSearch
from pystac_client.stac_api_io import StacApiIO
from urllib3 import Retry

from .leadtime_axis import leadtime_axis_payload, ordered_cog_assets
from .timefmt import parse_stac_datetime, to_stac_datetime

logger = logging.getLogger(__name__)

# Cross-process shared cache for STAC Items, bands, inits, and Collections.
# Lives on /tmp (tmpfs in Docker) so it is fast and ephemeral across restarts.
# All gunicorn workers share this store via diskcache's file-locking protocol,
# so each STAC API round-trip happens at most once across the process group.
_CACHE_DIR = os.environ.get("STAC_DISK_CACHE_DIR", "/tmp/stac-dashboard-cache")
_shared_cache: diskcache.Cache | None = None


def _get_shared_cache() -> diskcache.Cache:
    """Return the process-wide shared diskcache instance, creating it once."""
    global _shared_cache
    if _shared_cache is None:
        _shared_cache = diskcache.Cache(
            _CACHE_DIR,
            # Use pickle so pystac Item/Collection objects serialise correctly.
            disk=diskcache.Disk,
            size_limit=256 * 1024 * 1024,  # 256 MiB cap
        )
        logger.info("Shared STAC disk cache opened at %s", _CACHE_DIR)
    return _shared_cache


class _InternalStacApiIO(StacApiIO):
    """Rewrite public ``/api`` hrefs to the in-network STAC root.

    Staging/prod/dev advertise ``.../api/...`` in STAC links (for Traefik), while
    uvicorn still serves routes at ``/``. Strip the prefix for container-to-
    container calls from the dashboard. Pagination ``next`` links can also
    advertise ``.../api/api/...`` when ``ROOT_PATH=/api`` is set; strip every
    leading ``/api`` segment after the in-network base.
    """

    def __init__(self, base_url: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._base = base_url.rstrip("/")

    def _to_internal(self, href: str) -> str:
        # ROOT_PATH=/api makes some pagination links advertise ``/api/api/...``.
        # Strip every leading ``/api`` segment after the in-network base.
        marker = f"{self._base}/api"
        while href == marker or href == f"{marker}/" or href.startswith(marker + "/"):
            href = (
                f"{self._base}/"
                if href.rstrip("/") == marker
                else f"{self._base}/{href[len(marker) + 1 :]}"
            )
        return href

    def request(
        self,
        href: str,
        method: str | None = None,
        headers: dict[str, str] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        # Item Search passes a Link into read_text, which then calls request()
        # with the advertised ``/api/search`` href. Rewrite here so Link-driven
        # and string calls both hit uvicorn paths without the Traefik prefix.
        return super().request(
            self._to_internal(href),
            method=method,
            headers=headers,
            parameters=parameters,
        )

# Page size for listing inits when Collection summaries cannot be used.
# Matches pgSTAC's usual max so a mixed-leadtime fallback needs less
# HTTP round trips than the API default of 10.
_FORECAST_INIT_SEARCH_LIMIT = 10000

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

# Variable names sit on each forecast COG as ``forecast:bands``. Ask the
# API for assets only (no geometry, links, or file URLs) so filling the
# variables dropdown stays fast.
_FORECAST_BANDS_FIELDS = {
    "include": ["id", "assets"],
    "exclude": [
        "geometry",
        "bbox",
        "links",
        "assets.*.href",
        "assets.*.alternate",
    ],
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


def _datetime_equals_filter(forecast_reference_time: str) -> dict[str, Any]:
    """CQL2 filter: Item datetime is exactly this forecast start."""
    return {
        "op": "=",
        "args": [
            {"property": "datetime"},
            {"timestamp": forecast_reference_time},
        ],
    }


class STAC:
    # Namespace prefixes keep the four logical caches collision-free inside the
    # single shared diskcache store.
    _NS_ITEM = "item"
    _NS_BANDS = "bands"
    _NS_INITS = "inits"
    _NS_COLL = "coll"

    def __init__(self, STAC_FASTAPI_URL: str) -> None:
        # Refer to pystac-client docs:
        # https://pystac-client.readthedocs.io/en/stable/usage.html

        retry = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[502, 503, 504],
            allowed_methods=None,
        )
        stac_api_io = _InternalStacApiIO(STAC_FASTAPI_URL, max_retries=retry)
        self._url = STAC_FASTAPI_URL
        self._catalog = Client.open(STAC_FASTAPI_URL, stac_io=stac_api_io)
        # Shared cross-process cache (all gunicorn workers read/write the same
        # store). Replaces the four per-worker in-memory dicts so a cold STAC
        # API fetch only happens once regardless of which worker handles the
        # first request for a given key.
        self._cache = _get_shared_cache()

    # Internal cache helpers

    def _ckey(self, ns: str, *parts: str) -> str:
        """Build a namespaced cache key from namespace + key parts."""
        return "|".join([ns, *parts])

    def _active_cache(self) -> diskcache.Cache | dict:
        """
        Return the STAC cache store.

        Production always uses the shared ``diskcache.Cache``. Unit tests that
        build ``STAC`` via ``object.__new__`` may assign ``self._cache = {}``
        so they never touch ``/tmp``.
        """
        cache = getattr(self, "_cache", None)
        if cache is None:
            cache = _get_shared_cache()
            self._cache = cache
        return cache

    def _cache_get(self, ns: str, *parts: str) -> Any:
        """Read a namespaced value from the active cache store."""
        store = self._active_cache()
        key = self._ckey(ns, *parts)
        # dict: in-memory test double; otherwise diskcache.Cache.
        if isinstance(store, dict):
            return store.get(key)
        return store.get(key)

    def _cache_set(self, ns: str, value: Any, *parts: str) -> None:
        """Write a namespaced value to the active cache store."""
        store = self._active_cache()
        key = self._ckey(ns, *parts)
        if isinstance(store, dict):
            store[key] = value
        else:
            store.set(key, value)

    def _search_collection(self, collection_id) -> ItemSearch:
        search = self._catalog.search(collections=[collection_id], max_items=None)
        return search

    def _search_item_at(
        self,
        collection_id: str,
        forecast_reference_time: str,
        *,
        fields: dict[str, list[str]] | None = None,
    ) -> ItemSearch:
        """Find the one Item that started at this forecast time."""
        kwargs: dict[str, Any] = {
            "collections": [collection_id],
            "filter": _datetime_equals_filter(forecast_reference_time),
            "filter_lang": "cql2-json",
            "max_items": 1,
        }
        if fields is not None:
            kwargs["fields"] = fields
        return self._catalog.search(**kwargs)

    def get_catalog_collection_ids(self) -> list[str]:
        """
        Collection ids for the dropdown.

        Asks for ``id`` only so first load does not download every init
        summary. The selected Collection is loaded when the date picker
        needs it.
        """
        search = self._catalog.collection_search(fields=["id"])
        return [col["id"] for col in search.collections_as_dicts() if col.get("id")]

    def cache_collections(self, collections: Iterable[Collection]) -> None:
        """
        Keep Collection objects already in hand and prime forecast-init rows.

        Call this after listing collections for the dropdown so
        ``list_forecast_inits`` can use summaries without a second
        ``GET /collections/{id}``.
        """
        for collection in collections:
            self._cache_set(self._NS_COLL, collection, collection.id)
            if self._cache_get(self._NS_INITS, collection.id) is not None:
                continue
            inits = self._list_forecast_inits_from_summaries(collection)
            if inits is not None:
                self._cache_set(self._NS_INITS, inits, collection.id)

    def _get_collection(self, collection_id: str) -> Collection:
        """Return a Collection, reusing one already cached when present."""
        cached = self._cache_get(self._NS_COLL, collection_id)
        if cached is not None:
            return cached
        collection = self._catalog.get_collection(collection_id)
        self._cache_set(self._NS_COLL, collection, collection_id)
        return collection

    def get_collection_extents(self, collection_id):
        collection = self._get_collection(collection_id)
        logger.debug(f"Collection: {collection}")
        temporal_extent = collection.extent.temporal.intervals[0]
        spatial_extent = collection.extent.spatial.bboxes[0]
        return temporal_extent, spatial_extent

    def list_forecast_inits(self, collection_id: str) -> list[dict[str, Any]]:
        """
        List forecast initialisation times for a collection.

        Prefers Collection summaries (``forecast:reference_time`` plus a single
        shared ``forecast:leadtime_length``) so the date picker can avoid an
        Item Search. Falls back to a slim Item Search when summaries are
        missing or leadtime lengths are not uniform.

        Fetches the Collection when it is first selected so summaries can
        fill the date picker. Later calls reuse the cached object.

        Results are cached per collection on this client so switching
        selection back and forth does not repeat the API call.

        Returns:
            Sorted list of dicts with keys:
            ``datetime``, ``reference_time``, ``end_time``, ``leadtime_length``.
        """
        cached = self._cache_get(self._NS_INITS, collection_id)
        if cached is not None:
            return cached

        try:
            collection = self._get_collection(collection_id)
        except Exception as e:
            logger.warning(
                "Could not load collection %s for summaries: %s", collection_id, e
            )
            collection = None

        from_summaries = (
            self._list_forecast_inits_from_summaries(collection)
            if collection is not None
            else None
        )
        inits = (
            from_summaries
            if from_summaries is not None
            else self._list_forecast_inits_from_search(collection_id)
        )
        self._cache_set(self._NS_INITS, inits, collection_id)
        return inits

    def _list_forecast_inits_from_summaries(
        self, collection: Collection
    ) -> list[dict[str, Any]] | None:
        """
        Build init rows from a Collection's summaries, or None to fall back.

        Requires ``forecast:reference_time`` and exactly one
        ``forecast:leadtime_length`` value so each init can get an end date
        without listing Items. Does not fetch the Collection from the API.

        Read the init list in full. Converting summaries to a dict first
        drops any list of 25 or more dates, which would make the dashboard
        walk every Item instead.
        """
        summaries = collection.summaries
        if summaries is None or summaries.is_empty():
            return None

        reference_times = summaries.get_list("forecast:reference_time") or []
        if not isinstance(reference_times, list) or not reference_times:
            return None

        leadtime_values = summaries.get_list("forecast:leadtime_length") or []
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
                collection.id,
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
            collection.id,
        )
        return inits

    def _list_forecast_inits_from_search(
        self, collection_id: str
    ) -> list[dict[str, Any]]:
        """List forecast inits via a slim Item Search (Fields extension)."""
        search = self._catalog.search(
            collections=[collection_id],
            fields=_FORECAST_INIT_FIELDS,
            limit=_FORECAST_INIT_SEARCH_LIMIT,
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

    def get_forecast_item(
        self, collection_id: str, forecast_reference_time: str
    ) -> Item:
        """
        Return the STAC Item for one forecast run.

        Asks the API for the Item whose start time is exactly this forecast
        start. The result is cached so opening the same day again does not
        hit the API.
        """
        cached = self._cache_get(self._NS_ITEM, collection_id, forecast_reference_time)
        if cached is not None:
            return cached

        items = list(
            self._search_item_at(collection_id, forecast_reference_time).items()
        )
        if not items:
            raise ValueError(
                f"No item found with datetime {forecast_reference_time} "
                f"in collection {collection_id}."
            )

        item = items[0]
        self._cache_set(self._NS_ITEM, item, collection_id, forecast_reference_time)
        # Filling the variables dropdown can reuse this Item's band list.
        if self._cache_get(self._NS_BANDS, collection_id, forecast_reference_time) is None:
            bands = self._bands_from_item(item)
            if bands:
                self._cache_set(self._NS_BANDS, bands, collection_id, forecast_reference_time)
        return item

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
        # Ascending valid time so lead index matches the scrubber axis.
        return {
            key: asset
            for _valid, key, asset in ordered_cog_assets(assets)
        }

    def get_leadtime_axis(
        self, collection_id: str, forecast_reference_time: str
    ) -> dict:
        """Ordered valid times and inferred step unit for the lead scrubber."""
        cogs = self.get_item_cogs(collection_id, forecast_reference_time)
        return leadtime_axis_payload(cogs)

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

    @staticmethod
    def _bands_from_item(item: Item) -> dict[str, int]:
        """Read variable names and band numbers from a loaded forecast Item."""
        cogs = item.get_assets(media_type=MediaType.COG, role="data")
        if not cogs:
            return {}
        asset = next(iter(cogs.values()))
        band_props = asset.extra_fields.get("forecast:bands") or []
        return {
            str(band["name"]): int(band["index"])
            for band in band_props
            if band.get("name") is not None and band.get("index") is not None
        }

    @staticmethod
    def _bands_from_asset_dicts(assets: dict[str, Any]) -> dict[str, int]:
        """Read variable names and band numbers from a slim search response."""
        for asset in assets.values():
            if not isinstance(asset, dict):
                continue
            roles = asset.get("roles") or []
            media = asset.get("type") or asset.get("media_type") or ""
            is_data = "data" in roles
            is_cog = "cog" in media.lower() or media == str(MediaType.COG)
            if not (is_data or is_cog):
                continue
            band_props = asset.get("forecast:bands")
            if not band_props:
                continue
            bands: dict[str, int] = {}
            for band in band_props:
                name = band.get("name")
                index = band.get("index")
                if name is None or index is None:
                    continue
                bands[str(name)] = int(index)
            if bands:
                return bands
        return {}

    def list_forecast_bands(
        self, collection_id: str, forecast_reference_time: str
    ) -> dict[str, int]:
        """
        List the variables available for one forecast run.

        Returns a dict of variable name to band number. Prefers a light
        catalogue search that skips file URLs and geometry, so the variables
        dropdown can fill without waiting on a full Item download. Reuses a
        full Item already held in memory when present.
        """
        cached = self._cache_get(self._NS_BANDS, collection_id, forecast_reference_time)
        if cached is not None:
            return cached

        item = self._cache_get(self._NS_ITEM, collection_id, forecast_reference_time)
        if item is not None:
            bands = self._bands_from_item(item)
            self._cache_set(self._NS_BANDS, bands, collection_id, forecast_reference_time)
            return bands

        search = self._search_item_at(
            collection_id,
            forecast_reference_time,
            fields=_FORECAST_BANDS_FIELDS,
        )
        for raw in search.items_as_dicts():
            bands = self._bands_from_asset_dicts(raw.get("assets") or {})
            if bands:
                self._cache_set(self._NS_BANDS, bands, collection_id, forecast_reference_time)
                logger.debug(
                    "Loaded %s bands for %s @ %s via slim Item Search",
                    len(bands),
                    collection_id,
                    forecast_reference_time,
                )
                return bands

        # Search returned nothing useful: load the full Item instead.
        try:
            cogs = self.get_item_cogs(collection_id, forecast_reference_time)
        except ValueError:
            self._cache_set(self._NS_BANDS, {}, collection_id, forecast_reference_time)
            return {}
        if not cogs:
            self._cache_set(self._NS_BANDS, {}, collection_id, forecast_reference_time)
            return {}
        first_id = next(iter(cogs))
        bands = self.get_asset_bands(
            collection_id, forecast_reference_time, first_id
        )
        self._cache_set(self._NS_BANDS, bands, collection_id, forecast_reference_time)
        return bands

    def get_band_rescale(
        self, asset: Asset, band_index: int
    ) -> tuple[float, float] | None:
        """
        Return (min, max) for a COG band from asset metadata, or None.

        When None, callers should fall back to TiTiler ``/cog/statistics``.
        """
        return band_rescale_from_asset(asset, band_index)
