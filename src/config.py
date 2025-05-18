import os

# Get config from environmental variables
TITILER_URL = os.getenv("TITILER_URL", "http://localhost:8000")
DATA_URL = os.getenv("DATA_URL", "http://localhost:8002")
CATALOG_PATH = os.getenv("CATALOG_PATH", f"{DATA_URL}/data/stac/catalog.json")

print("TITILER URL:", TITILER_URL)
print("DATA URL:", DATA_URL)
print("CATALOG_PATH:", CATALOG_PATH)
