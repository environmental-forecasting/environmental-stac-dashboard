import logging
from datetime import datetime as dt
from typing import Iterable

from dateutil import parser
from pystac import Collection, Item, MediaType
from pystac_client import Client, ItemSearch
from pystac_client.stac_api_io import StacApiIO
from urllib3 import Retry

logger = logging.getLogger(__name__)


class STAC:
    def __init__(self, STAC_FASTAPI_URL: str) -> None:
        # Refer to pystac-client docs:
        # https://pystac-client.readthedocs.io/en/stable/usage.html

        retry = Retry(
            total=5, backoff_factor=1, status_forcelist=[502, 503, 504], allowed_methods=None
        )
        stac_api_io = StacApiIO(max_retries=retry)
        self._url = STAC_FASTAPI_URL
        self._catalog = Client.open(STAC_FASTAPI_URL, stac_io=stac_api_io)

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

    def _search_item_by_reference_time(self, collection_id: str, forecast_reference_time: str, max_items: int | None = 1) -> ItemSearch:
        """
        Search for an item by the 'forecast:reference_time' STAC property.
        """
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
        print(collection)
        temporal_extent = collection.extent.temporal.intervals[0]
        spatial_extent = collection.extent.spatial.bboxes[0]
        return temporal_extent, spatial_extent

    def get_collection_forecast_init_dates(self, collection_id) -> list[dt]:
        items = self.get_collection_items(collection_id)
        datetimes = sorted(
            {item.datetime for item in items if item.datetime is not None}
        )
        return datetimes

    def get_item(self, collection_id: str, forecast_reference_time: str) -> Item:
        search = self._search_item_by_reference_time(collection_id, forecast_reference_time)
        items = list(search.items())

        if len(items) == 0:
            raise ValueError(f"No item found with forecast:reference_time = {forecast_reference_time} in collection {collection_id}.")
        elif len(items) > 1:
            raise ValueError(f"Multiple items found with forecast:reference_time = {forecast_reference_time} in collection {collection_id}.")

        return items[0]

    def get_item_properties(self, collection_id: str, forecast_reference_time: str):
        item = self.get_item(collection_id, forecast_reference_time)
        return item.properties

    def get_item_leadtime(self, collection_id: str, forecast_reference_time: str) -> str:
        properties = self.get_item_properties(collection_id, forecast_reference_time)
        return properties["forecast:leadtime_length"]

    def get_item_extents(self, collection_id: str, forecast_reference_time: str):
        item = self.get_item(collection_id, forecast_reference_time)
        item_props = item.properties
        temporal_extent = (
            item_props["forecast:reference_time"],
            item_props["forecast:end_time"],
        )
        temporal_extent = [
            parser.isoparse(iso_string) for iso_string in temporal_extent
        ]
        # Convert to match datetime like `get_collection_extents`.
        spatial_extent = item.bbox
        return temporal_extent, spatial_extent

    def get_item_cogs(self, collection_id: str, forecast_reference_time: str):
        item = self.get_item(collection_id, forecast_reference_time)
        assets = item.get_assets(media_type=MediaType.COG, role="data")
        return assets

    def get_asset_band_props(self, collection_id: str, forecast_reference_time: str, asset_id):
        item = self.get_item(collection_id, forecast_reference_time)
        asset = item.assets.get(asset_id)

        # Get band information
        key = "forecast:bands"
        if key in asset.extra_fields:
            return asset.extra_fields[key]

        return None

    def get_asset_bands(self, collection_id: str, forecast_reference_time: str, asset_id) -> dict[str, int]:
        asset_band_props = self.get_asset_band_props(collection_id, forecast_reference_time, asset_id)
        bands = {band["name"]: band["index"] for band in asset_band_props}
        return bands
