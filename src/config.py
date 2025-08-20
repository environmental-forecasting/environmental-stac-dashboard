import os
import logging

# Get config from environmental variables
STAC_FASTAPI_URL = os.getenv("STAC_FASTAPI_URL", "http://localhost:8000")
TILER_URL = os.getenv("TILER_URL", "http://localhost:8002")

logging.info("TILER URL:", TILER_URL)
logging.info("STAC_FASTAPI_URL:", STAC_FASTAPI_URL)
