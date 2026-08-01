/**
 * Forecast map bridge.
 *
 * Dash writes `map-state`; this module shows the right host (OpenLayers or
 * Leaflet) and forwards the state to the active renderer. Skips work
 * when `revision` is unchanged so tile layers are not rebuilt unnecessarily.
 */

(function (global) {
  "use strict";

  var lastRevision = null;

  function applyState(state) {
    if (!state) {
      return;
    }
    if (state.revision === lastRevision) {
      return;
    }
    lastRevision = state.revision;

    var engine = state.engine || "openlayers";
    var leafletHost = document.getElementById("forecast-map-leaflet");

    if (leafletHost) {
      if (engine === "leaflet_legacy") {
        leafletHost.classList.remove("forecast-map-host--hidden");
      } else {
        leafletHost.classList.add("forecast-map-host--hidden");
      }
    }

    var htmlCbar = document.getElementById("forecast-cbar");
    if (htmlCbar) {
      // Leaflet still uses dl.Colorbar; hide the shared HTML ramp in legacy mode.
      htmlCbar.style.display = engine === "leaflet_legacy" ? "none" : "flex";
    }

    if (global.ForecastMapOpenLayers) {
      global.ForecastMapOpenLayers.applyState(state);
    }
  }

  global.ForecastMap = {
    applyState: applyState,
  };
})(window);
