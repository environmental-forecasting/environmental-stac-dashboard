from datetime import datetime, timezone
import sys
from pathlib import Path

from pystac import Asset

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from stac.leadtime_axis import (  # noqa: E402
    cog_asset_valid_time,
    infer_step_unit,
    leadtime_axis_payload,
    ordered_cog_assets,
)


def _asset(valid: str, lead: int) -> Asset:
    return Asset(
        href=f"https://example.com/{lead}.tif",
        media_type="image/tiff; application=geotiff; profile=cloud-optimized",
        roles=["data"],
        extra_fields={
            "custom:valid_time": valid,
            "custom:leadtime": lead,
        },
    )


def test_ordered_cog_assets_sorts_by_valid_time():
    cogs = {
        "later": _asset("2026-07-18T00:00:00Z", 2),
        "earlier": _asset("2026-07-16T00:00:00Z", 0),
        "mid": _asset("2026-07-17T00:00:00Z", 1),
    }
    ordered = ordered_cog_assets(cogs)
    assert [key for _t, key, _a in ordered] == ["earlier", "mid", "later"]


def test_infer_step_unit_hourly():
    times = [
        datetime(2026, 1, 1, h, tzinfo=timezone.utc) for h in (0, 6, 12, 18)
    ]
    assert infer_step_unit(times) == "hour"


def test_infer_step_unit_daily():
    times = [
        datetime(2026, 7, d, tzinfo=timezone.utc) for d in (16, 17, 18, 19)
    ]
    assert infer_step_unit(times) == "day"


def test_leadtime_axis_payload():
    cogs = {
        "b": _asset("2026-07-17T00:00:00Z", 1),
        "a": _asset("2026-07-16T00:00:00Z", 0),
    }
    payload = leadtime_axis_payload(cogs)
    assert payload["step_unit"] == "day"
    assert len(payload["times"]) == 2
    assert payload["times"][0].startswith("2026-07-16")


def test_cog_asset_valid_time_from_key():
    asset = Asset(href="x.tif", roles=["data"])
    assert cog_asset_valid_time(
        asset, "2026-07-16T00:00:00Z"
    ) == datetime(2026, 7, 16, tzinfo=timezone.utc)
