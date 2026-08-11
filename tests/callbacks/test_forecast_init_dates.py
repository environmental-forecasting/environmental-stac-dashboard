"""Tests for the forecast start date picker allow-list."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from components.controls import forecast_init_disabled_dates  # noqa: E402


def test_picker_sends_available_days_not_gaps():
    spec = forecast_init_disabled_dates(["2020-01-01", "2026-01-01"])
    assert spec["function"] == "disableUnlessForecastInit"
    assert spec["options"]["allowed"] == {
        "2020-01-01": True,
        "2026-01-01": True,
    }


def test_picker_reuses_the_init_day_store():
    store = {"2020-01-01": "2020-01-04", "2026-01-01": "2026-01-04"}
    spec = forecast_init_disabled_dates(store)
    assert spec["options"]["allowed"] is store


def test_picker_allow_list_is_empty_when_there_are_no_inits():
    spec = forecast_init_disabled_dates(())
    assert spec["options"]["allowed"] == {}
