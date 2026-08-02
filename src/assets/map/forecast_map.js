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
  var lastState = null;
  var activeEngine = "openlayers";
  var tilesReady = true;
  var readyTimeout = null;
  // Playback gates on tilesReady; keep this short so a missed rendercomplete
  // cannot freeze Play for tens of seconds when switching TMS / engines.
  var READY_TIMEOUT_MS = 4000;
  // Optimistic engine switches use revisions above this so a later Python
  // map-state publish (revision N+1) still applies.
  var LOCAL_REVISION_BASE = 1000000000;

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

  function engineForMode(mode) {
    if (mode === "globe_cesium") {
      return "cesium";
    }
    if (mode === "global_leaflet") {
      return "leaflet_legacy";
    }
    return "openlayers";
  }

  function tmsForMode(mode) {
    if (
      mode === "global_3857" ||
      mode === "global_leaflet" ||
      mode === "globe_cesium" ||
      !mode
    ) {
      return "WebMercatorQuad";
    }
    if (/^EPSG\d+$/.test(mode)) {
      return mode;
    }
    return "WebMercatorQuad";
  }

  function rewriteLayersTms(layers, tileMatrixSet) {
    if (!layers || !layers.length || !tileMatrixSet) {
      return layers || [];
    }
    var out = [];
    var i;
    for (i = 0; i < layers.length; i += 1) {
      var layer = layers[i];
      if (!layer || typeof layer.tileUrl !== "string") {
        out.push(layer);
        continue;
      }
      var nextUrl = layer.tileUrl.replace(
        /(\/cog\/tiles\/)([^/]+)(\/)/,
        "$1" + tileMatrixSet + "$3"
      );
      out.push(Object.assign({}, layer, { tileUrl: nextUrl }));
    }
    return out;
  }

  function projectionOf(state) {
    return (state && state.view && state.view.projection) || "";
  }

  function applyState(state) {
    if (!state) {
      return;
    }
    if (state.revision === lastRevision) {
      return;
    }
    var previous = lastState;
    lastRevision = state.revision;
    // Keep a copy for optimistic engine switches (before Python round-trips).
    lastState = state;

    var engine = state.engine || "openlayers";
    activeEngine = engine;
    var layers = state.layers || [];
    var sameCamera =
      previous &&
      (previous.engine || "openlayers") === engine &&
      (previous.mode || "") === (state.mode || "") &&
      projectionOf(previous) === projectionOf(state);

    // Same projection/engine: only swap overlay URLs (preserve camera / zoom).
    if (
      sameCamera &&
      engine === "openlayers" &&
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.applyLeadtime === "function"
    ) {
      if (layers.length) {
        setTilesReady(false);
      } else {
        setTilesReady(true);
      }
      global.ForecastMapOpenLayers.applyLeadtime(layers);
      return;
    }

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

    // Only drive the active host. Inactive renderers stay warm but are not
    // asked to rebuild layers on every engine / TMS switch.
    if (engine === "openlayers" && global.ForecastMapOpenLayers) {
      global.ForecastMapOpenLayers.applyState(state);
    } else if (engine === "cesium" && global.ForecastMapCesium) {
      global.ForecastMapCesium.applyState(state);
    }

    // Still hide inactive hosts when applyState was skipped for them.
    if (engine !== "openlayers" && global.ForecastMapOpenLayers) {
      global.ForecastMapOpenLayers.applyState({ engine: "none", revision: -1 });
    }
    if (engine !== "cesium" && global.ForecastMapCesium) {
      global.ForecastMapCesium.applyState({ engine: "none", revision: -1 });
    }

    if (engine === "leaflet_legacy") {
      setTilesReady(true);
    }
  }

  /**
   * Switch map host immediately using the last known layers/view.
   *
   * Used when the user changes view mode so the UI does not wait on the
   * Python ``update_cog_layer`` round-trip (keeps playback speed responsive).
   */
  function applyEngine(engine) {
    if (!engine || !lastState) {
      return;
    }
    if (engine === (lastState.engine || "openlayers")) {
      return;
    }
    applyState(
      Object.assign({}, lastState, {
        engine: engine,
        revision: LOCAL_REVISION_BASE + (lastState.revision || 0) + 1,
      })
    );
  }

  /**
   * Apply a view-mode change immediately (engine + TMS rewrite + view preset).
   *
   * ``presets`` is ``{ mode: viewHint }`` from the Dash store, including polar
   * tile-grid hints so Arctic/Antarctic do not wait on Python.
   */
  function applyViewMode(mode, presets) {
    if (!mode || !lastState) {
      return;
    }
    if (mode === (lastState.mode || "")) {
      // Same mode: still allow engine-only recovery.
      applyEngine(engineForMode(mode));
      return;
    }
    var engine = engineForMode(mode);
    var tms = tmsForMode(mode);
    var view = null;
    if (presets && presets[mode]) {
      view = presets[mode];
    } else if (lastState.view && tms === "WebMercatorQuad") {
      view = lastState.view;
    }
    var next = Object.assign({}, lastState, {
      engine: engine,
      mode: mode,
      layers: rewriteLayersTms(lastState.layers || [], tms),
      revision: LOCAL_REVISION_BASE + (lastState.revision || 0) + 1,
    });
    if (view) {
      next.view = view;
    }
    applyState(next);
  }

  global.ForecastMap = {
    applyState: applyState,
    applyEngine: applyEngine,
    applyViewMode: applyViewMode,
    setTilesReady: setTilesReady,
    isTilesReady: isTilesReady,
  };
})(window);
