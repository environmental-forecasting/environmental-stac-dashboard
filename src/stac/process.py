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

def get_leadtimes(catalog_path: str, collection_id: str, forecast_start_date: str) -> list[int]:
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
        # print(dir(forecast_collection.extent.temporal))
        # print(forecast_collection.extent.temporal.intervals)
        # forecast_start, forecast_end = forecast_collection.extent.temporal.intervals[0]
        forecast_time_interval = np.concatenate(forecast_collection.extent.temporal.intervals)
        forecast_start, forecast_end = [time.strftime('%Y-%m-%d') for time in forecast_time_interval]
        if forecast_start == forecast_start_date:
            # print("forecast_collection", forecast_collection.get_items())
            return forecast_collection.get_items()


    # # Extract leadtimes from the items in the forecast collection
    # leadtimes = []
    # for item in forecast_collection.get_items():
    #     leadtime = item.properties.get("leadtime")
    #     if leadtime is not None:
    #         leadtimes.append(leadtime)

    # return leadtimes

    # return forecast_collection.get_items()


def get_leadtime(catalog_path: str, collection_id: str, forecast_start_date: str, leadtime: int):
    """
    Retrieve COG path of specified leadtime for a given hemisphere collection and forecast_start_time.

    Args:
        catalog_path: Path to the STAC catalog JSON file.
        collection_id: Collection ID (e.g., "north" or "south").
        forecast_start_date: Forecast start time in "YYYY-MM-DD" format.
        leadtime: Forecast lead time.
    """
    forecast_collection = get_leadtimes(catalog_path, collection_id, forecast_start_date)
    if forecast_collection:
        for forecast in forecast_collection:
            if forecast.properties["leadtime"] == leadtime:
                return forecast#.get_assets()#["geotiff"].href


def get_cog_path(catalog_path: str, collection_id: str, forecast_start_date: str, leadtime: int):
    """
    Retrieve COG path of specified leadtime for a given collection and forecast_start_time.

    Args:
        catalog_path: Path to the STAC catalog JSON file.
        collection_id: Collection ID (e.g., "north" or "south").
        forecast_start_date: Forecast start time in "YYYY-MM-DD" format.
        leadtime: Forecast lead time.
    """
    forecast_leadtime_collection = get_leadtimes(catalog_path, collection_id, forecast_start_date)
    if forecast_leadtime_collection:
        for forecast in forecast_leadtime_collection:
            if forecast.properties["leadtime"] == leadtime:
                return forecast.get_assets()["geotiff"].href
