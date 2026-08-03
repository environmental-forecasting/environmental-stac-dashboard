"""Tests for display-style colourbar helpers."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from callbacks.display_style import (  # noqa: E402
    cbar_slider_step,
    normalise_display_style,
)


def test_normalise_display_style_fills_defaults_and_spans_domain():
    style = normalise_display_style({"vmin": 2, "vmax": 5, "locked": 1})
    assert style["vmin"] == 2.0
    assert style["vmax"] == 5.0
    assert style["domain_min"] <= 2.0
    assert style["domain_max"] >= 5.0
    assert style["locked"] is True
    assert style["colormap"]


def test_normalise_display_style_swaps_inverted_range():
    style = normalise_display_style({"vmin": 8, "vmax": 3})
    assert style["vmin"] == 3.0
    assert style["vmax"] == 8.0


def test_cbar_slider_step_scales_with_domain():
    assert cbar_slider_step(0, 100) >= 1.0
    assert cbar_slider_step(0, 1) <= 0.1
