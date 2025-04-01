import datetime as dt
import logging
import numpy as np

from pystac import Catalog

def get_all_forecast_start_dates(catalog_path: str, hemisphere: str) -> set[str]:
    """
    Retrieve all available forecast_start_date values for a given hemisphere collection.

    Args:
        catalog_path: Path to the STAC catalog JSON file.
        hemisphere: Hemisphere collection ID (e.g., "north" or "south").

    Returns:
        A set of unique forecast_start_date values in "YYYY-MM-DD" format.
    """
    # Load the STAC catalog
    try:
        catalog = Catalog.from_file(catalog_path)
    except FileNotFoundError:
        logging.error("STAC catalog file not found.")
        return set()
    except:
        logging.error("Error loading STAC catalog")
        return set()

    # Find the hemisphere collection
    hemisphere_collection = next(
        (coll for coll in catalog.get_children() if coll.id == hemisphere), None
    )
    if not hemisphere_collection:
        raise ValueError(f"Hemisphere collection '{hemisphere}' not found in catalog.")

    # Extract all forecast_start_date values from the items in the forecast collections
    forecast_start_dates = set()
    for forecast_collection in hemisphere_collection.get_children():
        for item in forecast_collection.get_items():
            forecast_start_date = item.properties.get("forecast_start_date")
            forecast_start_date = dt.datetime.strptime(forecast_start_date, "%Y-%m-%d")
            if forecast_start_date:
                forecast_start_dates.add(forecast_start_date)

    return forecast_start_dates

def get_leadtimes(catalog_path, hemisphere, forecast_start_date):
    """
    Retrieve all leadtime items for a given hemisphere collection and forecast_start_time.

    Args:
        catalog_path (str): Path to the STAC catalog JSON file.
        hemisphere (str): Hemisphere collection ID (e.g., "north" or "south").
        forecast_start_date (str): Forecast start time in "YYYY-MM-DD" format.

    Returns:
        list[int]: List of leadtimes for the specified collection and forecast start time.
    """
    # Load the STAC catalog
    catalog = Catalog.from_file(catalog_path)

    # Find the hemisphere collection
    hemisphere_collection = next(
        (coll for coll in catalog.get_children() if coll.id == hemisphere), None
    )
    if not hemisphere_collection:
        raise ValueError(f"Hemisphere collection '{hemisphere}' not found in catalog.")
    # print(list(hemisphere_collection.get_children()))

    # Find the forecast collection for the given forecast_start_date
    for forecast_collection in hemisphere_collection.get_children():
        # print(dir(forecast_collection.extent.temporal))
        # print(forecast_collection.extent.temporal.intervals)
        # forecast_start, forecast_end = forecast_collection.extent.temporal.intervals[0]
        forecast_time_interval = np.concatenate(forecast_collection.extent.temporal.intervals)
        forecast_start, forecast_end = [time.strftime('%Y-%m-%d') for time in forecast_time_interval]
        # print(forecast_start, forecast_start_date)
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

    return forecast_collection.get_items()


def get_leadtime(catalog_path: str, hemisphere: str, forecast_start_date: str, leadtime: int):
    """
    Retrieve COG path of specified leadtime for a given hemisphere collection and forecast_start_time.

    Args:
        catalog_path: Path to the STAC catalog JSON file.
        hemisphere: Hemisphere collection ID (e.g., "north" or "south").
        forecast_start_date: Forecast start time in "YYYY-MM-DD" format.
        leadtime: Forecast lead time.
    """
    forecast_collection = get_leadtimes(catalog_path, hemisphere, forecast_start_date)
    for forecast in forecast_collection:
        if forecast.properties["leadtime"] == leadtime:
            return forecast#.get_assets()#["geotiff"].href


def get_cog_path(catalog_path: str, hemisphere: str, forecast_start_date: str, leadtime: int):
    """
    Retrieve COG path of specified leadtime for a given hemisphere collection and forecast_start_time.

    Args:
        catalog_path: Path to the STAC catalog JSON file.
        hemisphere: Hemisphere collection ID (e.g., "north" or "south").
        forecast_start_date: Forecast start time in "YYYY-MM-DD" format.
        leadtime: Forecast lead time.
    """
    forecast_collection = get_leadtimes(catalog_path, hemisphere, forecast_start_date)
    for forecast in forecast_collection:
        if forecast.properties["leadtime"] == leadtime:
            return forecast.get_assets()["geotiff"].href
