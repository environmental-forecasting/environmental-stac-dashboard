import os
import logging

# Get config from environmental variables
TITILER_URL = os.getenv("TITILER_URL", "http://localhost:8000")
DATA_URL = os.getenv("DATA_URL", "http://localhost:8002")
CATALOG_PATH = os.getenv("CATALOG_PATH", f"{DATA_URL}/data/stac/catalog.json")

logging.info("TITILER URL:", TITILER_URL)
logging.info("DATA URL:", DATA_URL)
logging.info("CATALOG_PATH:", CATALOG_PATH)
