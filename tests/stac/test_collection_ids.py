"""Tests for listing collection ids without full Collection bodies."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from stac.process import STAC  # noqa: E402


def test_collection_ids_request_id_field_only():
    stac = object.__new__(STAC)
    stac._catalog = MagicMock()
    search = MagicMock()
    search.collections_as_dicts.return_value = [{"id": "alpha"}, {"id": "beta"}]
    stac._catalog.collection_search.return_value = search

    assert stac.get_catalog_collection_ids() == ["alpha", "beta"]
    stac._catalog.collection_search.assert_called_once_with(fields=["id"])
