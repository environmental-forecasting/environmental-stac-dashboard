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
 *
 * Scrubbing and playback swap overlay URLs from the `leadtimeCogUrls` cache
 * that Python publishes with each rebuild, so a leadtime step paints without
 * a Dash round trip.
 *
 * Busy banner ownership: Dash owns catalog / dates / variables / map labels
 * on `#forecast-busy`. This module only shows "Loading tiles…" after a soft
 * swap or full apply that must wait for paint, so the two sides do not fight.
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
  // Warm the next step only once the current one has had a head start, so
  // prefetching cannot compete with the tiles the user is waiting on.
  var PREFETCH_DELAY_MS = 600;
  var prefetchTimer = null;
  // Optimistic engine switches use revisions above this so a later Python
  // map-state publish (revision N+1) still applies.
  var LOCAL_REVISION_BASE = 1000000000;
  var busyTimer = null;
  var busyVisible = false;
  // JS only stores a tiles wait here; Dash owns every other busy label.
  var busyReasons = {};
  var BUSY_SHOW_DELAY_MS = 220;

  function busyEl() {
    return document.getElementById("forecast-busy");
  }

  function busyLabelEl() {
    return document.getElementById("forecast-busy-label");
  }

  function busyReasonCount() {
    return Object.keys(busyReasons).length;
  }

  function hideBusyChrome() {
    if (busyTimer) {
      clearTimeout(busyTimer);
      busyTimer = null;
    }
    if (global.dash_clientside && typeof global.dash_clientside.set_props === "function") {
      global.dash_clientside.set_props("forecast-busy", {
        className: "forecast-busy is-hidden",
      });
    } else {
      var el = busyEl();
      if (el) {
        el.classList.add("is-hidden");
      }
    }
    busyVisible = false;
  }

  function showBusyNow() {
    if (!busyReasonCount()) {
      hideBusyChrome();
      return;
    }
    var message = busyReasons.tiles || "Loading tiles…";
    if (global.dash_clientside && typeof global.dash_clientside.set_props === "function") {
      global.dash_clientside.set_props("forecast-busy", { className: "forecast-busy" });
      global.dash_clientside.set_props("forecast-busy-label", { children: message });
    } else {
      var el = busyEl();
      var label = busyLabelEl();
      if (label) {
        label.textContent = message;
      }
      if (el) {
        el.classList.remove("is-hidden");
      }
    }
    busyVisible = true;
  }

  function scheduleBusyShow() {
    if (busyVisible) {
      showBusyNow();
      return;
    }
    if (busyTimer) {
      clearTimeout(busyTimer);
    }
    busyTimer = setTimeout(function () {
      busyTimer = null;
      showBusyNow();
    }, BUSY_SHOW_DELAY_MS);
  }

  /**
   * Mark the UI as waiting on tiles. Only the tiles reason is used here;
   * Dash writes every other busy label straight onto `#forecast-busy`.
   */
  function setBusy(message, reason) {
    var key = reason || "tiles";
    if (key !== "tiles") {
      return;
    }
    var next = message || "Loading tiles…";
    if (busyReasons.tiles === next && busyVisible) {
      return;
    }
    busyReasons.tiles = next;
    scheduleBusyShow();
  }

  function clearBusy(reason) {
    if (reason && reason !== "tiles") {
      return;
    }
    if (reason) {
      delete busyReasons[reason];
    } else {
      busyReasons = {};
    }
    if (!busyReasonCount()) {
      hideBusyChrome();
    }
  }

  /**
   * Drop a Dash "Updating …" wait once map-state has applied with nothing
   * left to paint. Leave Loading catalog / dates / variables alone.
   */
  function endDashMapWait() {
    var label = busyLabelEl();
    var text = label ? String(label.textContent || "") : "";
    if (/^Updating /.test(text) || text === "Updating…") {
      hideBusyChrome();
    }
  }

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
      // Only clear when this module armed a tiles wait; play/scrub readiness
      // must not wipe a Dash catalog or map label.
      if (busyReasons.tiles) {
        clearBusy("tiles");
      }
      return;
    }
    // Hung / empty-viewport loads must not block play indefinitely.
    readyTimeout = setTimeout(function () {
      tilesReady = true;
      readyTimeout = null;
      if (busyReasons.tiles) {
        clearBusy("tiles");
      }
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

  function layerUrlsKey(layers) {
    if (!layers || !layers.length) {
      return "";
    }
    var parts = [];
    var i;
    for (i = 0; i < layers.length; i += 1) {
      var layer = layers[i];
      parts.push((layer && layer.id) || "", (layer && layer.tileUrl) || "");
    }
    return parts.join("\0");
  }

  /**
   * Format a rescale bound the way Python renders a float.
   *
   * Whole numbers keep a decimal point so a swapped URL is byte-identical to
   * the one Python publishes on confirm: identical URLs reuse the tiles the
   * browser has already fetched instead of requesting them again.
   */
  function formatRescaleBound(value) {
    var number = Number(value);
    if (!isFinite(number)) {
      return String(value);
    }
    return Number.isInteger(number) ? number.toFixed(1) : String(number);
  }

  /**
   * Build overlay layers for one leadtime from the published COG URL cache.
   *
   * Mirrors `layers_from_leadtime_cog_urls` in Python so a client-side swap
   * and a Python confirm produce the same tile URLs.
   */
  function layersFromLeadtimeCogUrls(cache, lead) {
    if (!cache || !cache.collections || lead == null || lead < 0) {
      return [];
    }
    var tilerBase = cache.tilerBase;
    if (!tilerBase) {
      return [];
    }
    var tms = cache.tileMatrixSet || "WebMercatorQuad";
    var layers = [];
    var ids = Object.keys(cache.collections);
    var i;
    for (i = 0; i < ids.length; i += 1) {
      var id = ids[i];
      var meta = cache.collections[id];
      var hrefs = meta && meta.hrefs;
      if (!hrefs || lead >= hrefs.length || !hrefs[lead]) {
        continue;
      }
      var tileUrl =
        tilerBase.replace(/\/$/, "") +
        "/cog/tiles/" +
        tms +
        "/{z}/{x}/{y}?url=" +
        hrefs[lead];
      if (cache.colormap) {
        tileUrl += "&colormap_name=" + cache.colormap;
      }
      if (cache.rescale && cache.rescale.length >= 2) {
        tileUrl +=
          "&rescale=" +
          formatRescaleBound(cache.rescale[0]) +
          "," +
          formatRescaleBound(cache.rescale[1]);
      }
      if (cache.bidx != null) {
        tileUrl += "&bidx=" + cache.bidx;
      }
      layers.push({
        id: id,
        title: id,
        tileUrl: tileUrl,
        opacity: 1,
        visible: true,
      });
    }
    return layers;
  }

  function hasLeadtimeCogUrls() {
    return !!(
      lastState &&
      lastState.leadtimeCogUrls &&
      lastState.leadtimeCogUrls.collections &&
      Object.keys(lastState.leadtimeCogUrls.collections).length
    );
  }

  /** Drop the cache so a stale forecast cannot be swapped in. */
  function clearLeadtimeCogUrls() {
    if (!lastState) {
      return;
    }
    lastState = Object.assign({}, lastState, { leadtimeCogUrls: null });
  }

  function schedulePrefetch(state) {
    if (prefetchTimer) {
      clearTimeout(prefetchTimer);
      prefetchTimer = null;
    }
    var layers = state && state.prefetchLayers;
    if (
      !layers ||
      !layers.length ||
      !global.ForecastMapOpenLayers ||
      typeof global.ForecastMapOpenLayers.prefetchLayers !== "function"
    ) {
      return;
    }
    prefetchTimer = setTimeout(function () {
      prefetchTimer = null;
      // A newer frame arrived while waiting; its own prefetch takes over.
      if (lastState !== state) {
        return;
      }
      global.ForecastMapOpenLayers.prefetchLayers(layers, {
        maxTiles: 6,
        zDelta: -1,
      });
    }, PREFETCH_DELAY_MS);
  }

  /**
   * Swap overlay URLs for a leadtime step using the published COG URL cache.
   *
   * Called from a clientside Dash callback on slider change so tile requests
   * start before Python confirms the step.
   */
  function applyLeadtimeIndex(lead) {
    if (lead == null || !lastState) {
      return false;
    }
    var nextLead = Number(lead);
    var layers = layersFromLeadtimeCogUrls(lastState.leadtimeCogUrls, nextLead);
    if (!layers.length) {
      return false;
    }
    if (activeEngine !== "openlayers") {
      // Other hosts still wait on Python; keep the tracked lead in step.
      lastState = Object.assign({}, lastState, {
        layers: layers,
        lead: nextLead,
      });
      return false;
    }
    if (layerUrlsKey(lastState.layers) === layerUrlsKey(layers)) {
      setTilesReady(true);
      return true;
    }
    var previousLead = lastState.lead;
    // A jump of more than one step (first / last, long drag) would show a
    // mottled mix of old and new tiles, so hold the incoming frame back.
    var holdUntilReady =
      previousLead != null &&
      !isNaN(Number(previousLead)) &&
      Math.abs(nextLead - Number(previousLead)) > 1;
    lastState = Object.assign({}, lastState, {
      layers: layers,
      lead: nextLead,
    });
    if (
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.applyLeadtime === "function"
    ) {
      // The renderer reports readiness itself; play pacing then waits on
      // hasPendingSwap rather than on this frame.
      global.ForecastMapOpenLayers.applyLeadtime(layers, {
        holdUntilReady: holdUntilReady,
      });
    } else {
      setTilesReady(true);
    }
    schedulePrefetch(lastState);
    return true;
  }

  function applyState(state) {
    if (!state) {
      return;
    }
    if (state.revision === lastRevision) {
      // No visual rebuild, but a Dash round-trip may have finished.
      endDashMapWait();
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
      // A confirm for a step the browser already swapped in needs no repaint.
      if (layerUrlsKey(previous.layers) === layerUrlsKey(layers)) {
        setTilesReady(true);
        endDashMapWait();
        schedulePrefetch(state);
        return;
      }
      // Date / variable / style rebuilds soft-swap in place. Keep the busy
      // banner until the new viewport tiles have painted. Scrub/play still
      // uses applyLeadtimeIndex (no banner).
      if (layers.length) {
        setTilesReady(false);
        setBusy("Loading tiles…", "tiles");
        global.ForecastMapOpenLayers.applyLeadtime(layers, {
          holdUntilReady: true,
          waitForTiles: true,
        });
      } else {
        setTilesReady(true);
        endDashMapWait();
        global.ForecastMapOpenLayers.applyLeadtime(layers, {
          holdUntilReady: true,
        });
      }
      schedulePrefetch(state);
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
    // Soft-swap rebuilds own the banner; scrub never calls this path.
    if (layers.length && engine !== "leaflet_legacy") {
      setTilesReady(false);
      setBusy("Loading tiles…", "tiles");
    } else {
      setTilesReady(true);
      endDashMapWait();
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
      endDashMapWait();
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
    // Keep the cache on the new tile matrix set so a scrub before Python
    // confirms does not swap back to the previous projection's tiles.
    var nextCogUrls = lastState.leadtimeCogUrls
      ? Object.assign({}, lastState.leadtimeCogUrls, { tileMatrixSet: tms })
      : lastState.leadtimeCogUrls;
    var next = Object.assign({}, lastState, {
      engine: engine,
      mode: mode,
      layers: rewriteLayersTms(lastState.layers || [], tms),
      leadtimeCogUrls: nextCogUrls,
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
    applyLeadtimeIndex: applyLeadtimeIndex,
    layersFromLeadtimeCogUrls: layersFromLeadtimeCogUrls,
    hasLeadtimeCogUrls: hasLeadtimeCogUrls,
    clearLeadtimeCogUrls: clearLeadtimeCogUrls,
    setTilesReady: setTilesReady,
    isTilesReady: isTilesReady,
    setBusy: setBusy,
    clearBusy: clearBusy,
  };
})(window);
