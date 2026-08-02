/**
 * Forecast map bridge.
 *
 * Dash writes `map-state`; this module shows the right host (OpenLayers,
 * Cesium, or Leaflet) and forwards the state to the active renderer. Skips
 * work when `revision` is unchanged so tile layers are not rebuilt
 * unnecessarily.
 *
 * Tile readiness gates timeline playback: after a new forecast frame is
 * applied, play waits until the active renderer reports tiles loaded (with a
 * safety timeout so a hung tile cannot stall forever).
 */

(function (global) {
  "use strict";

  var lastRevision = null;
  var tilesReady = true;
  var readyTimeout = null;
  var READY_TIMEOUT_MS = 15000;

  function clearReadyTimeout() {
    if (readyTimeout) {
      clearTimeout(readyTimeout);
      readyTimeout = null;
    }
  }

  function setTilesReady(ready) {
    clearReadyTimeout();
    tilesReady = !!ready;
    if (tilesReady) {
      return;
    }
    // Hung / empty-viewport loads must not block play indefinitely.
    readyTimeout = setTimeout(function () {
      tilesReady = true;
      readyTimeout = null;
    }, READY_TIMEOUT_MS);
  }

  function isTilesReady() {
    return tilesReady;
  }

  function applyState(state) {
    if (!state) {
      return;
    }
    if (state.revision === lastRevision) {
      return;
    }
    lastRevision = state.revision;

    var engine = state.engine || "openlayers";
    var layers = state.layers || [];
    var leafletHost = document.getElementById("forecast-map-leaflet");
    var globeHost = document.getElementById("forecast-map-globe");
    var olHost = document.getElementById("forecast-map-ol");

    if (olHost) {
      if (engine === "openlayers") {
        olHost.classList.remove("forecast-map-host--hidden");
      } else {
        olHost.classList.add("forecast-map-host--hidden");
      }
    }

    if (leafletHost) {
      if (engine === "leaflet_legacy") {
        leafletHost.classList.remove("forecast-map-host--hidden");
      } else {
        leafletHost.classList.add("forecast-map-host--hidden");
      }
    }

    if (globeHost) {
      if (engine === "cesium") {
        globeHost.classList.remove("forecast-map-host--hidden");
      } else {
        globeHost.classList.add("forecast-map-host--hidden");
      }
    }

    var htmlCbar = document.getElementById("forecast-cbar");
    if (htmlCbar) {
      // Shared ramp lives in the timeline for every engine.
      htmlCbar.style.display = "flex";
    }

    // New frame: block play until the renderer calls setTilesReady(true).
    // Leaflet has no shared load hook here - treat as ready after apply.
    if (layers.length && engine !== "leaflet_legacy") {
      setTilesReady(false);
    } else {
      setTilesReady(true);
    }

    if (global.ForecastMapOpenLayers) {
      global.ForecastMapOpenLayers.applyState(state);
    }
    if (global.ForecastMapCesium) {
      global.ForecastMapCesium.applyState(state);
    }

    if (engine === "leaflet_legacy") {
      setTilesReady(true);
    }
  }

  global.ForecastMap = {
    applyState: applyState,
    setTilesReady: setTilesReady,
    isTilesReady: isTilesReady,
  };
})(window);
