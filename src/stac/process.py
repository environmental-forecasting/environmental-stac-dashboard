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
        self._url = STAC_FASTAPI_URL
        self._catalog = Client.open(STAC_FASTAPI_URL)

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

    def get_item(self, collection_id, item_id) -> Item:
        # Using db likely to be faster than using get_collection_items, then filtering here in Python.
        search = self._search_item(collection_id, item_id)
        item = tuple(search.items())
        if len(item) > 1:
            raise ValueError(
                f"Multiple items with id {item_id} found within {collection_id} collection."
            )
        else:
            item = item[0]
        return item

    def get_item_properties(self, collection_id, item_id):
        item = self.get_item(collection_id, item_id)
        return item.properties

    def get_item_leadtime(self, collection_id, item_id) -> str:
        properties = self.get_item_properties(collection_id, item_id)
        return properties["forecast:leadtime_length"]

    def get_item_extents(self, collection_id, item_id):
        item = self.get_item(collection_id, item_id)
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

    def get_item_cogs(self, collection_id, item_id):
        item = self.get_item(collection_id, item_id)
        assets = item.get_assets(media_type=MediaType.COG, role="data")
        return assets

    def get_asset_band_props(self, collection_id, item_id, asset_id):
        item = self.get_item(collection_id, item_id)
        asset = item.assets.get(asset_id)

        # Get band information
        key = "forecast:bands"
        if key in asset.extra_fields:
            return asset.extra_fields[key]

        return None

    def get_asset_band_names(self, collection_id, item_id, asset_id):
        asset_band_props = self.get_asset_band_props(collection_id, item_id, asset_id)
        band_names = [band["name"] for band in asset_band_props]
        return band_names
















import datetime as dt
import logging

import numpy as np
from pystac import Catalog


def get_catalog(catalog_path: str) -> Catalog:
    """
    Retrieve STAC catalog.

    Args:
        catalog_path: Path to the STAC catalog JSON file.

    Returns:
        The STAC catalog object.
    """
    # Load the STAC catalog
    try:
        catalog = Catalog.from_file(catalog_path)
        return catalog
    except FileNotFoundError:
        logging.error("STAC catalog file not found.")
        return set()
    except:
        logging.error("Error loading STAC catalog")
        return set()


def get_collections(catalog_path: str) -> list[str]:
    """
    Retrieve all collections within the STAC catalog.

    Args:
        catalog_path: Path to the STAC catalog JSON file.

    Returns:
        A list of collection id's in the catalog.
    """
    catalog = get_catalog(catalog_path)

    return [collection.id for collection in catalog.get_children()]


def get_all_forecast_start_dates(catalog_path: str, collection_id: str) -> set[str]:
    """
    Retrieve all available forecast_start_date values for a given collection.

    Args:
        catalog_path: Path to the STAC catalog JSON file.
        collection: Collection ID (e.g., "north" or "south").

    Returns:
        A set of unique forecast_start_date values in "YYYY-MM-DD" format.
    """
    catalog = get_catalog(catalog_path)

    # Find the hemisphere collection
    collection = next(
        (coll for coll in catalog.get_children() if coll.id == collection_id), None
    )
    if not collection:
        raise ValueError(f"collection '{collection_id}' not found in catalog.")

    # Extract all forecast_start_date values from the items in the forecast collections
    forecast_start_dates = set()
    for forecast_collection in collection.get_children():
        for item in forecast_collection.get_items():
            forecast_start_date = item.properties.get("forecast_start_date")
            forecast_start_date = dt.datetime.strptime(forecast_start_date, "%Y-%m-%d")
            if forecast_start_date:
                forecast_start_dates.add(forecast_start_date)

    return forecast_start_dates


def get_all_forecast_dates(catalog_path: str, collection_id: str) -> set[str]:
    """
    Retrieve all available `forecast_start_date` and `forecast_end_date` values
    for a given collection.

    Args:
        catalog_path: Path to the STAC catalog JSON file.
        collection: Collection ID (e.g., "north" or "south").

    Returns:
        A set of unique forecast_start_date values in "YYYY-MM-DD" format.
    """
    catalog = get_catalog(catalog_path)

    # Find the hemisphere collection
    collection = next(
        (coll for coll in catalog.get_children() if coll.id == collection_id), None
    )
    if not collection:
        raise ValueError(f"collection '{collection_id}' not found in catalog.")

    # Extract all forecast_start_date values from the items in the forecast collections
    forecast_dates = {}
    for forecast_collection in collection.get_children():
        temporal_interval = forecast_collection.extent.temporal.intervals

        forecast_start_date, forecast_end_date = temporal_interval[0]

        if forecast_start_date and forecast_end_date:
            forecast_dates[forecast_start_date.strftime("%Y-%m-%d")] = forecast_end_date.strftime("%Y-%m-%d")

    return forecast_dates


def get_leadtimes(
    catalog_path: str, collection_id: str, forecast_start_date: str
) -> list[int]:
    """
    Retrieve all leadtime items for a given hemisphere collection and forecast_start_time.

    Args:
        catalog_path: Path to the STAC catalog JSON file.
        collection_id: Collection ID (e.g., "north" or "south").
        forecast_start_date: Forecast start time in "YYYY-MM-DD" format.

    Returns:
        List of leadtimes for the specified collection and forecast start time.
    """
    catalog = get_catalog(catalog_path)

    # Find the hemisphere collection
    collection = next(
        (coll for coll in catalog.get_children() if coll.id == collection_id), None
    )
    if not collection:
        raise ValueError(f"Collection '{collection_id}' not found in catalog.")
    # print(list(hemisphere_collection.get_children()))

    # Find the forecast collection for the given forecast_start_date
    for forecast_collection in collection.get_children():
        forecast_time_interval = np.concatenate(
            forecast_collection.extent.temporal.intervals
        )
        forecast_start, forecast_end = [
            time.strftime("%Y-%m-%d") for time in forecast_time_interval
        ]
        if forecast_start == forecast_start_date:
            return forecast_collection.get_items()

    # # Extract leadtimes from the items in the forecast collection
    # leadtimes = []
    # for item in forecast_collection.get_items():
    #     leadtime = item.properties.get("leadtime")
    #     if leadtime is not None:
    #         leadtimes.append(leadtime)

    # return leadtimes

    # return forecast_collection.get_items()


def get_leadtime(
    catalog_path: str, collection_id: str, forecast_start_date: str, leadtime: int
):
    """
    Retrieve COG path of specified leadtime for a given hemisphere collection and forecast_start_time.

    Args:
        catalog_path: Path to the STAC catalog JSON file.
        collection_id: Collection ID (e.g., "north" or "south").
        forecast_start_date: Forecast start time in "YYYY-MM-DD" format.
        leadtime: Forecast lead time.
    """
    forecast_collection = get_leadtimes(
        catalog_path, collection_id, forecast_start_date
    )
    if forecast_collection:
        for forecast in forecast_collection:
            if forecast.properties["leadtime"] == leadtime:
                return forecast  # .get_assets()#["geotiff"].href


def get_cog_path(
    catalog_path: str, collection_id: str, forecast_start_date: str, leadtime: int
):
    """
    Retrieve COG path of specified leadtime for a given collection and forecast_start_time.

    Args:
        catalog_path: Path to the STAC catalog JSON file.
        collection_id: Collection ID (e.g., "north" or "south").
        forecast_start_date: Forecast start time in "YYYY-MM-DD" format.
        leadtime: Forecast lead time.
    """
    forecast_leadtime_collection = get_leadtimes(
        catalog_path, collection_id, forecast_start_date
    )
    if forecast_leadtime_collection:
        for forecast in forecast_leadtime_collection:
            if forecast.properties["leadtime"] == leadtime:
                return forecast.get_assets()["geotiff"].href
