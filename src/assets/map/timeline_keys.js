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

  global.ForecastTimelineKeys = {
    isEditableTarget: isEditableTarget,
  };
})(window);
