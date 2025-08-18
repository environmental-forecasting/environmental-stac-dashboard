import os
import logging

# Get config from environmental variables
STAC_FASTAPI_URL = os.getenv("STAC_FASTAPI_URL", "http://localhost:8000")
DATA_URL = os.getenv("DATA_URL", "http://localhost:8001")
TITILER_URL = os.getenv("TITILER_URL", "http://localhost:8002")
CATALOG_PATH = os.getenv("CATALOG_PATH", f"{DATA_URL}/data/stac/catalog.json")

logging.info("TITILER URL:", TITILER_URL)
logging.info("DATA URL:", DATA_URL)
logging.info("STAC_FASTAPI_URL:", STAC_FASTAPI_URL)
