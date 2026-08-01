"""Tests for shared map-state helpers."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.state import build_map_state, initial_map_state  # noqa: E402


def test_initial_map_state_defaults_to_openlayers_global():
    state = initial_map_state()
    assert state["engine"] == "openlayers"
    assert state["mode"] == "global_3857"
    assert state["layers"] == []
    assert state["revision"] == 0


def test_build_map_state_bumps_revision_only_when_content_changes():
    previous = initial_map_state()
    same = build_map_state(
        previous=previous,
        engine="openlayers",
        mode="global_3857",
        layers=[],
    )
    assert same["revision"] == 0

    changed = build_map_state(
        previous=previous,
        engine="openlayers",
        mode="global_3857",
        layers=[
            {
                "id": "demo",
                "title": "demo",
                "tileUrl": "http://example/{z}/{x}/{y}",
                "opacity": 1,
                "visible": True,
            }
        ],
    )
    assert changed["revision"] == 1
    assert len(changed["layers"]) == 1
