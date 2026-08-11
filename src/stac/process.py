import logging
import os
from datetime import datetime as dt
from typing import Any

import diskcache
from pystac import Collection
from pystac_client import Client
from pystac_client.stac_api_io import StacApiIO
from urllib3 import Retry

from .timefmt import parse_stac_datetime, to_stac_datetime

logger = logging.getLogger(__name__)

# Cross-process shared cache for STAC Collections and forecast-init lists.
# Lives on /tmp (tmpfs in Docker) so it is fast and ephemeral across restarts.
# All gunicorn workers share this store via diskcache's file-locking protocol,
# so each STAC API round-trip happens at most once across the process group.
_CACHE_DIR = os.environ.get("STAC_DISK_CACHE_DIR", "/tmp/stac-dashboard-cache")
# How long a cached row stays valid. After this the next read asks the
# API again, so a re-ingest shows up without restarting the dashboard.
# A day matches a daily production ingest; shorten locally if you are
# ingesting often. Set STAC_DISK_CACHE_TTL=0 to keep rows until the
# store evicts them.
_CACHE_TTL_SECONDS = int(os.environ.get("STAC_DISK_CACHE_TTL", "86400"))
_shared_cache: diskcache.Cache | None = None


def _get_shared_cache() -> diskcache.Cache:
    """Return the process-wide shared diskcache instance, creating it once."""
    global _shared_cache
    if _shared_cache is None:
        _shared_cache = diskcache.Cache(
            _CACHE_DIR,
            # Use pickle so pystac Item/Collection objects serialise correctly.
            disk=diskcache.Disk,
            size_limit=1024 * 1024 * 1024,  # 1024 MiB cap
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

class STAC:
    # Namespace prefixes keep the logical caches collision-free inside the
    # single shared diskcache store.
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
        # store). Replaces per-worker in-memory dicts so a cold STAC
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
            return
        # 0 means no expiry (tests and local debugging).
        expire = _CACHE_TTL_SECONDS or None
        store.set(key, value, expire=expire)

    def get_catalog_collection_ids(self) -> list[str]:
        """
        Collection ids for the dropdown.

        Asks for ``id`` only so first load does not download every init
        summary. The selected Collection is loaded when the date picker
        needs it.
        """
        search = self._catalog.collection_search(fields=["id"])
        return [col["id"] for col in search.collections_as_dicts() if col.get("id")]

    def _get_collection(self, collection_id: str) -> Collection:
        """Return a Collection, reusing one already cached when present."""
        cached = self._cache_get(self._NS_COLL, collection_id)
        if cached is not None:
            return cached
        collection = self._catalog.get_collection(collection_id)
        self._cache_set(self._NS_COLL, collection, collection_id)
        return collection

    def list_forecast_inits(self, collection_id: str) -> list[dict[str, Any]]:
        """
        List forecast initialisation times for a collection.

        Prefers Collection summaries (``forecast:reference_time`` plus a single
        shared ``forecast:leadtime_length``) so the date picker can avoid an
        Item Search. Falls back to a slim Item Search when summaries are
        missing or leadtime lengths are not uniform.

        Fetches the Collection when it is first selected so summaries can
        fill the date picker. Later calls reuse the cached object until
        it expires.

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

