"""
Leadtime axis from STAC COG assets.

The scrubber is indexed 0..N-1 over forecast leads. Valid times and the display
step unit come from each COG's ``custom:valid_time`` (or asset key), not from a
calendar day span between init and end.
"""

from datetime import datetime, timezone

from pystac import Asset

from .timefmt import parse_stac_datetime


def cog_asset_valid_time(asset: Asset, asset_key: str | None = None) -> datetime:
    """
    Resolve the absolute valid time for a forecast COG asset.

    Prefers ``custom:valid_time``, then the asset key when it parses as a STAC
    datetime (generator uses RFC3339 keys).
    """
    extras = asset.extra_fields or {}
    raw = extras.get("custom:valid_time")
    if raw:
        return parse_stac_datetime(raw)
    if asset_key:
        return parse_stac_datetime(asset_key)
    raise ValueError("COG asset has no custom:valid_time or datetime key")


def ordered_cog_assets(cogs: dict[str, Asset]) -> list[tuple[datetime, str, Asset]]:
    """
    Sort COG assets by valid time ascending.

    Returns triples ``(valid_time, asset_key, asset)``.
    """
    rows: list[tuple[datetime, str, Asset]] = []
    for key, asset in (cogs or {}).items():
        try:
            rows.append((cog_asset_valid_time(asset, key), key, asset))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda row: row[0])
    return rows


def infer_step_unit(valid_times: list[datetime]) -> str:
    """
    Map median lead spacing to a UI step unit for labels/subtitle.

    Returns one of ``hour``, ``day``, ``week``, ``month``.
    """
    if len(valid_times) < 2:
        return "day"

    seconds: list[float] = []
    for earlier, later in zip(valid_times, valid_times[1:]):
        a = earlier if earlier.tzinfo else earlier.replace(tzinfo=timezone.utc)
        b = later if later.tzinfo else later.replace(tzinfo=timezone.utc)
        delta = (b - a).total_seconds()
        if delta > 0:
            seconds.append(delta)
    if not seconds:
        return "day"

    median_s = sorted(seconds)[len(seconds) // 2]
    hour = 3600.0
    day = 86400.0
    week = 7 * day
    month = 30 * day

    if median_s < day * 0.75:
        return "hour"
    if median_s < week * 0.75:
        return "day"
    if median_s < month * 0.75:
        return "week"
    return "month"


def leadtime_axis_payload(cogs: dict[str, Asset]) -> dict:
    """
    Build a store payload for the leadtime scrubber.

    Returns:
        ``{"times": [RFC3339, ...], "step_unit": str}`` sorted by valid time.
        ``times`` may be empty when no COG valid times are available.
    """
    ordered = ordered_cog_assets(cogs)
    times = [row[0] for row in ordered]
    from .timefmt import to_stac_datetime

    return {
        "times": [to_stac_datetime(t) for t in times],
        "step_unit": infer_step_unit(times),
    }
