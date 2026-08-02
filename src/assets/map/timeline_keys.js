/** Leadtime transport, pace, and keyboard shortcuts. */

(function (global) {
  "use strict";

  function isEditableTarget(target) {
    if (!target || !target.closest) {
      return false;
    }
    if (target.isContentEditable) {
      return true;
    }
    var tag = (target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") {
      return true;
    }
    return Boolean(
      target.closest(
        ".mantine-DatePickerInput-input, .mantine-Popover-dropdown, .Select-control, .Select-menu-outer, [contenteditable='true']"
      )
    );
  }

  function getSliderBounds() {
    var slider = document.getElementById("leadtime-slider");
    if (!slider) {
      return { min: 0, max: 0 };
    }
    // Mantine slider bounds are reflected on the Dash component props via DOM dataset when present.
    var minAttr = slider.getAttribute("data-min");
    var maxAttr = slider.getAttribute("data-max");
    return {
      min: minAttr != null ? Number(minAttr) : 0,
      max: maxAttr != null ? Number(maxAttr) : 0,
    };
  }

  global.ForecastTimelineKeys = {
    isEditableTarget: isEditableTarget,
    getSliderBounds: getSliderBounds,
  };
})(window);
