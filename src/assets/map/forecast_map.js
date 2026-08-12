/**
 * Forecast map bridge.
 *
 * Dash writes `map-state`; this module shows the right host (OpenLayers
 * or Cesium) and forwards the state to the active renderer. Skips
 * work when `revision` is unchanged so tile layers are not rebuilt
 * unnecessarily.
 *
 * Tile readiness gates timeline playback: after a new forecast frame is
 * applied, play waits until the active renderer reports tiles loaded (with a
 * safety timeout so a hung tile cannot stall forever).
 *
 * Scrubbing and playback swap overlay URLs from the `leadtimeCogUrls` cache
 * that Python publishes with each rebuild, so a leadtime step paints without
 * a Dash round trip on OpenLayers and Cesium.
 *
 * Busy banner ownership: Dash owns catalog / dates / variables / map labels
 * on `#forecast-busy`. This module switches to "Loading tiles…" after a
 * rebuild that must wait for paint, and hides it when those tiles are ready.
 */

(function (global) {
  "use strict";

  var lastRevision = null;
  var lastState = null;
  var lastPlaceGoto = null;
  var activeEngine = "openlayers";
  var tilesReady = true;
  var readyTimeout = null;
  // Safety only: Play never arms this wait. Date / scrub can take longer
  // than a few seconds to fill the viewport, so do not hide the banner early.
  var READY_TIMEOUT_MS = 30000;
  // Prefetching cannot compete with the tiles the user is waiting on.
  var PREFETCH_DELAY_MS = 600;
  var prefetchTimer = null;
  // Warm a window around the current lead (±radius), near leads first.
  var PREFETCH_RADIUS = 4;
  // Hard cap on total Image() kicks across the whole window.
  var PREFETCH_MAX_TILES_TOTAL = 32;
  var PREFETCH_MAX_TILES_PER_LEAD = 6;
  // Optimistic engine switches use revisions above this so a later Python
  // map-state publish (revision N+1) still applies.
  var LOCAL_REVISION_BASE = 1000000000;
  // Live pill selection; ignore late Python map-state for a mode already left.
  var desiredMode = null;
  var busyTimer = null;
  var busyVisible = false;
  // JS only stores a tiles wait here; Dash owns every other busy label.
  var busyReasons = {};
  var BUSY_SHOW_DELAY_MS = 220;
  // Scrub/play should stay quiet unless a step is still waiting after this.
  var SCRUB_BUSY_DELAY_MS = 1000;
  var northUpEscBound = false;

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

  function scheduleBusyShow(delayMs) {
    if (busyVisible) {
      showBusyNow();
      return;
    }
    if (busyTimer) {
      clearTimeout(busyTimer);
    }
    var wait = delayMs == null ? BUSY_SHOW_DELAY_MS : delayMs;
    busyTimer = setTimeout(function () {
      busyTimer = null;
      showBusyNow();
    }, wait);
  }

  /**
   * Mark the UI as waiting on tiles. Only the tiles reason is used here;
   * Dash writes every other busy label straight onto `#forecast-busy`.
   *
   * options.delay: wait this many ms before showing (scrub uses 1000 so a
   * fast step never flashes the banner).
   */
  function setBusy(message, reason, options) {
    var key = reason || "tiles";
    if (key !== "tiles") {
      return;
    }
    var next = message || "Loading tiles…";
    if (busyReasons.tiles === next && busyVisible) {
      return;
    }
    busyReasons.tiles = next;
    var delayMs = options && options.delay;
    var el = busyEl();
    // Dash may already be showing "Updating map…". Switch the label now
    // rather than hiding, then waiting 220ms to show tiles.
    if (delayMs == null && el && !el.classList.contains("is-hidden")) {
      busyVisible = true;
      showBusyNow();
      return;
    }
    scheduleBusyShow(delayMs);
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
    if (
      /^Updating /.test(text) ||
      text === "Updating…" ||
      /^Loading variables/.test(text)
    ) {
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
    return "openlayers";
  }

  function tmsForMode(mode) {
    if (
      mode === "global_3857" ||
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
   * Build overlay layers for one leadtime from the published Item cache.
   *
   * Scrubbing only changes ``assets=``.
   */
  function layersFromLeadtimeCogUrls(cache, lead) {
    if (!cache || !cache.collections || lead == null || lead < 0) {
      return [];
    }
    if (!cache.tilerBase) {
      return [];
    }
    var viewMode = cache.viewMode || (lastState && lastState.mode) || "";
    var layers = [];
    var ids = Object.keys(cache.collections);
    var i;
    for (i = 0; i < ids.length; i += 1) {
      var id = ids[i];
      var meta = cache.collections[id];
      var hrefs = meta && meta.hrefs;
      if (!meta || !meta.itemId || !hrefs || lead >= hrefs.length || !hrefs[lead]) {
        continue;
      }
      if (!bboxFitsViewMode(meta.bbox, viewMode)) {
        continue;
      }
      var tileUrl = itemTileUrl(cache, id, meta.itemId, hrefs[lead]);
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
      layers.push({
        id: id,
        title: id,
        tileUrl: tileUrl,
        opacity: 1,
        visible: true,
        bbox: meta.bbox || null,
        gsd: meta.gsd > 0 ? Number(meta.gsd) : undefined,
      });
    }
    return layers;
  }

  function itemTileUrl(cache, collectionId, itemId, assetKey) {
    var assets = encodeURIComponent(assetKey);
    if (cache.bidx != null) {
      assets += encodeURIComponent("|bidx=" + cache.bidx);
    }
    return (
      cache.tilerBase.replace(/\/$/, "") +
      "/collections/" +
      encodeURIComponent(collectionId) +
      "/items/" +
      encodeURIComponent(itemId) +
      "/tiles/" +
      (cache.tileMatrixSet || "WebMercatorQuad") +
      "/{z}/{x}/{y}.webp?assets=" +
      assets
    );
  }

  function bboxFitsViewMode(bbox, mode) {
    if (
      !mode ||
      mode === "global_3857" ||
      mode === "globe_cesium"
    ) {
      return true;
    }
    if (!bbox || bbox.length < 4) {
      return true;
    }
    var centre = (Number(bbox[1]) + Number(bbox[3])) / 2;
    if (!isFinite(centre)) {
      return true;
    }
    if (mode === "EPSG6931") {
      return centre > 0;
    }
    if (mode === "EPSG6932") {
      return centre < 0;
    }
    return true;
  }

  function hasLeadtimeCogUrls() {
    return !!(
      lastState &&
      lastState.leadtimeCogUrls &&
      lastState.leadtimeCogUrls.collections &&
      Object.keys(lastState.leadtimeCogUrls.collections).length
    );
  }

  function activePrefetchFn() {
    if (
      activeEngine === "openlayers" &&
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.prefetchLayers === "function"
    ) {
      return global.ForecastMapOpenLayers.prefetchLayers;
    }
    if (
      activeEngine === "cesium" &&
      global.ForecastMapCesium &&
      typeof global.ForecastMapCesium.prefetchLayers === "function"
    ) {
      return global.ForecastMapCesium.prefetchLayers;
    }
    return null;
  }

  /**
   * Warm neighbouring leadtimes from `leadtimeCogUrls` (feat-branch style).
   *
   * Walks ±radius with near offsets first, spending a shared Image() budget
   * so play and scrub stay snappy without flooding TiTiler.
   */
  function schedulePrefetch(state) {
    if (prefetchTimer) {
      clearTimeout(prefetchTimer);
      prefetchTimer = null;
    }
    if (!state || !activePrefetchFn()) {
      return;
    }
    var cache = state.leadtimeCogUrls;
    var currentLead = state.lead;
    if (
      cache &&
      cache.collections &&
      currentLead != null &&
      !isNaN(Number(currentLead))
    ) {
      var lead = Number(currentLead);
      prefetchTimer = setTimeout(function () {
        prefetchTimer = null;
        // A newer frame arrived while waiting; its own prefetch takes over.
        if (lastState !== state) {
          return;
        }
        var prefetchFn = activePrefetchFn();
        if (!prefetchFn) {
          return;
        }
        // Prefer freshest lead if the user kept scrubbing during the delay.
        var centre =
          lastState && lastState.lead != null && !isNaN(Number(lastState.lead))
            ? Number(lastState.lead)
            : lead;
        var bank =
          (lastState && lastState.leadtimeCogUrls) || cache;
        var remaining = PREFETCH_MAX_TILES_TOTAL;
        var d;
        for (d = 1; d <= PREFETCH_RADIUS && remaining > 0; d += 1) {
          var offsets = [d, -d];
          var oi;
          for (oi = 0; oi < offsets.length && remaining > 0; oi += 1) {
            var step = centre + offsets[oi];
            if (step < 0) {
              continue;
            }
            var layers = layersFromLeadtimeCogUrls(bank, step);
            if (!layers.length) {
              continue;
            }
            var budget = Math.min(PREFETCH_MAX_TILES_PER_LEAD, remaining);
            prefetchFn(layers, {
              maxTiles: budget,
              zDelta: -1,
            });
            remaining -= budget;
          }
        }
      }, PREFETCH_DELAY_MS);
      return;
    }
    // Fallback: explicit prefetchLayers from Python (lead+1).
    if (!state.prefetchLayers || !state.prefetchLayers.length) {
      return;
    }
    prefetchTimer = setTimeout(function () {
      prefetchTimer = null;
      if (lastState !== state) {
        return;
      }
      var prefetchFn = activePrefetchFn();
      if (!prefetchFn) {
        return;
      }
      prefetchFn(state.prefetchLayers, {
        maxTiles: PREFETCH_MAX_TILES_PER_LEAD,
        zDelta: -1,
      });
    }, PREFETCH_DELAY_MS);
  }

  /**
   * Warm XYZ `{z}/{x}/{y}` templates into the browser (and TiTiler) cache.
   *
   * Shared by OpenLayers and Cesium: each renderer computes its own viewport
   * tile range, then this fills Image() requests up to maxTiles.
   *
   * @param {Array<{tileUrl?: string}|string>} layersOrUrls
   * @param {{z: number, minX: number, maxX: number, minY: number, maxY: number, maxTiles?: number}} range
   */
  function prefetchTileImages(layersOrUrls, range) {
    if (!layersOrUrls || !layersOrUrls.length || !range) {
      return;
    }
    var z = range.z;
    if (z == null || isNaN(Number(z))) {
      return;
    }
    z = Math.round(Number(z));
    var minX = Number(range.minX);
    var maxX = Number(range.maxX);
    var minY = Number(range.minY);
    var maxY = Number(range.maxY);
    if (
      !isFinite(minX) ||
      !isFinite(maxX) ||
      !isFinite(minY) ||
      !isFinite(maxY)
    ) {
      return;
    }
    var maxTiles =
      range.maxTiles != null ? Number(range.maxTiles) : 8;
    if (isNaN(maxTiles) || maxTiles < 1) {
      maxTiles = 8;
    }
    var queued = 0;
    var i;
    var x;
    var y;
    for (i = 0; i < layersOrUrls.length; i += 1) {
      var entry = layersOrUrls[i];
      var template =
        typeof entry === "string"
          ? entry
          : entry && entry.tileUrl;
      if (!template || typeof template !== "string") {
        continue;
      }
      for (x = minX; x <= maxX && queued < maxTiles; x += 1) {
        for (y = minY; y <= maxY && queued < maxTiles; y += 1) {
          var image = new Image();
          image.crossOrigin = "anonymous";
          image.src = template
            .replace("{z}", String(z))
            .replace("{x}", String(x))
            .replace("{y}", String(y));
          queued += 1;
        }
      }
    }
  }

  /**
   * Swap overlay URLs for a leadtime step using the published COG URL cache.
   *
   * Called from a clientside Dash callback on slider change so tile requests
   * start before Python confirms the step.
   */
  function applyLeadtimeIndex(lead, options) {
    if (lead == null || !lastState) {
      return false;
    }
    var playing = !!(options && options.playing);
    var nextLead = Number(lead);
    var layers = layersFromLeadtimeCogUrls(lastState.leadtimeCogUrls, nextLead);
    if (!layers.length) {
      return false;
    }
    if (layerUrlsKey(lastState.layers) === layerUrlsKey(layers)) {
      lastState = Object.assign({}, lastState, {
        layers: layers,
        lead: nextLead,
      });
      setTilesReady(true);
      publishDashMapState();
      return true;
    }
    var previousLead = lastState.lead;
    // Adjacent scrub/play uses progressive reveal (previous tiles show through).
    // Jumps hold the incoming frame until ready so mixed old/new tiles never flash.
    var holdUntilReady =
      previousLead != null &&
      !isNaN(Number(previousLead)) &&
      Math.abs(nextLead - Number(previousLead)) > 1;
    lastState = Object.assign({}, lastState, {
      layers: layers,
      lead: nextLead,
    });
    publishDashMapState();
    // Same contract on OpenLayers and Cesium. Play does not show a banner.
    // Scrub shows "Loading tiles…" if the step is still waiting after 1s,
    // and keeps it until those tiles have painted.
    var leadOpts = {
      holdUntilReady: holdUntilReady,
      // Cesium play must wait for the globe queue; OpenLayers play uses
      // hasPendingSwap so a missed rendercomplete cannot stall it.
      waitForTiles: !playing || activeEngine === "cesium",
    };
    if (!playing) {
      setBusy("Loading tiles…", "tiles", { delay: SCRUB_BUSY_DELAY_MS });
    }
    if (
      activeEngine === "openlayers" &&
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.applyLeadtime === "function"
    ) {
      global.ForecastMapOpenLayers.applyLeadtime(layers, leadOpts);
      schedulePrefetch(lastState);
      return true;
    }
    if (
      activeEngine === "cesium" &&
      global.ForecastMapCesium &&
      typeof global.ForecastMapCesium.applyLeadtime === "function"
    ) {
      global.ForecastMapCesium.applyLeadtime(layers, leadOpts);
      schedulePrefetch(lastState);
      return true;
    }
    // Unknown host: clear the play gate so ticks are not stuck waiting.
    setTilesReady(true);
    return false;
  }

  function applyBasemapFromState(state) {
    if (!state) {
      return;
    }
    var engine = state.engine || "openlayers";
    var show = state.view && state.view.showBasemap;
    if (
      engine === "openlayers" &&
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.setBasemap === "function"
    ) {
      global.ForecastMapOpenLayers.setBasemap(state.basemap, show);
      return;
    }
    if (
      engine === "cesium" &&
      global.ForecastMapCesium &&
      typeof global.ForecastMapCesium.setBasemap === "function"
    ) {
      global.ForecastMapCesium.setBasemap(state.basemap, show);
    }
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
    // Ignore late Python publishes for a TMS the user has already left.
    if (desiredMode && state.mode && state.mode !== desiredMode) {
      return;
    }
    if (state.mode) {
      desiredMode = state.mode;
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
    // Basemap still needs applying - a style toggle bumps revision with
    // identical overlay URLs and used to early-return before setBasemap.
    if (
      sameCamera &&
      engine === "openlayers" &&
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.applyLeadtime === "function"
    ) {
      applyBasemapFromState(state);
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

    if (
      sameCamera &&
      engine === "cesium" &&
      global.ForecastMapCesium &&
      typeof global.ForecastMapCesium.applyLeadtime === "function"
    ) {
      applyBasemapFromState(state);
      if (layerUrlsKey(previous.layers) === layerUrlsKey(layers)) {
        setTilesReady(true);
        endDashMapWait();
        schedulePrefetch(state);
        return;
      }
      if (layers.length) {
        setTilesReady(false);
        setBusy("Loading tiles…", "tiles");
        global.ForecastMapCesium.applyLeadtime(layers, {
          holdUntilReady: true,
          waitForTiles: true,
        });
      } else {
        setTilesReady(true);
        endDashMapWait();
        global.ForecastMapCesium.applyLeadtime(layers, {
          holdUntilReady: true,
        });
      }
      schedulePrefetch(state);
      return;
    }

    var globeHost = document.getElementById("forecast-map-globe");
    var olHost = document.getElementById("forecast-map-ol");

    if (olHost) {
      if (engine === "openlayers") {
        olHost.classList.remove("forecast-map-host--hidden");
      } else {
        olHost.classList.add("forecast-map-host--hidden");
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
    // Soft-swap rebuilds own the banner; scrub never calls this path.
    // A TMS switch clears the previous overlay immediately; keep
    // "Loading tiles…" up until the new grid has painted.
    var modeChanged =
      previous &&
      ((previous.engine || "openlayers") !== engine ||
        (previous.mode || "") !== (state.mode || ""));
    if (layers.length || modeChanged) {
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
      if (lastPlaceGoto) {
        global.requestAnimationFrame(function () {
          var result = flyTo(lastPlaceGoto);
          publishPlaceStatus(result);
        });
      }
    } else if (engine === "cesium" && global.ForecastMapCesium) {
      global.ForecastMapCesium.applyState(state);
      if (lastPlaceGoto) {
        global.requestAnimationFrame(function () {
          var result = flyTo(lastPlaceGoto);
          publishPlaceStatus(result);
        });
      }
    }

    // Still hide inactive hosts when applyState was skipped for them.
    if (engine !== "openlayers" && global.ForecastMapOpenLayers) {
      global.ForecastMapOpenLayers.applyState({ engine: "none", revision: -1 });
    }
    if (engine !== "cesium" && global.ForecastMapCesium) {
      global.ForecastMapCesium.applyState({ engine: "none", revision: -1 });
    }
  }

  /**
   * Apply a view-mode change immediately (engine + view preset).
   *
   * ``presets`` is ``{ mode: viewHint }`` from the Dash store, including polar
   * tile-grid hints so Arctic/Antarctic do not wait on Python. The previous
   * overlay is dropped immediately so a Web Mercator layer cannot sit on a
   * polar grid while the new tiles load.
   */
  function applyViewMode(mode, presets) {
    if (!mode) {
      return;
    }
    desiredMode = mode;
    if (!lastState) {
      return;
    }
    if (mode === (lastState.mode || "")) {
      // Same TMS / view mode: restore that mode's default framing.
      resetView();
      return;
    }
    if (prefetchTimer) {
      clearTimeout(prefetchTimer);
      prefetchTimer = null;
    }
    var engine = engineForMode(mode);
    // Always take the preset for this mode. Reusing lastState.view when switching
    // to Global reused the polar camera and looked like "the other" TMS.
    var view = presets && presets[mode] ? presets[mode] : null;
    var cache = lastState.leadtimeCogUrls;
    var nextCache = null;
    var nextLayers = [];
    if (cache && cache.collections) {
      nextCache = Object.assign({}, cache, {
        tileMatrixSet: tmsForMode(mode),
        viewMode: mode,
      });
      nextLayers = layersFromLeadtimeCogUrls(
        nextCache,
        lastState.lead != null ? lastState.lead : 0
      );
    }
    // Never keep the previous TMS painted on the new grid.
    applyState(
      Object.assign({}, lastState, {
        engine: engine,
        mode: mode,
        layers: nextLayers,
        leadtimeCogUrls: nextCache,
        view: view || lastState.view,
        revision: LOCAL_REVISION_BASE + (lastState.revision || 0) + 1,
      })
    );
    publishDashMapState();
  }

  /**
   * Restore the default framing for the active engine / TMS.
   *
   * Used when the user re-clicks the already-selected view-mode pill.
   */
  function resetView() {
    clearNorthUpSelection();
    var engine = currentEngine();
    if (
      engine === "cesium" &&
      global.ForecastMapCesium &&
      typeof global.ForecastMapCesium.resetView === "function"
    ) {
      global.ForecastMapCesium.resetView();
      return;
    }
    if (
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.resetView === "function"
    ) {
      global.ForecastMapOpenLayers.resetView();
    }
  }

  function ensureViewModeResetClick() {
    if (global.__forecastViewModeResetBound) {
      return;
    }
    global.__forecastViewModeResetBound = true;
    // RadioItems do not re-fire when the active pill is clicked again.
    // Capture "already checked" on mousedown, then reset on click.
    document.addEventListener(
      "mousedown",
      function (event) {
        var label = event.target.closest
          ? event.target.closest(".forecast-map-view-mode label")
          : null;
        if (!label) {
          global.__forecastResetViewPending = false;
          return;
        }
        var input = label.querySelector('input[type="radio"]');
        global.__forecastResetViewPending = !!(input && input.checked);
      },
      true
    );
    document.addEventListener("click", function (event) {
      if (
        !event.target.closest ||
        !event.target.closest(".forecast-map-view-mode")
      ) {
        return;
      }
      if (!global.__forecastResetViewPending) {
        return;
      }
      global.__forecastResetViewPending = false;
      resetView();
    });
  }

  function publishPlaceStatus(result) {
    if (!result || result.skipped) {
      return;
    }
    if (
      !global.dash_clientside ||
      typeof global.dash_clientside.set_props !== "function"
    ) {
      return;
    }
    if (result.ok === false) {
      global.dash_clientside.set_props("map-search-status", {
        children: result.message || "Outside this map's coverage",
        className: "forecast-map-search__status is-warning",
      });
      return;
    }
    global.dash_clientside.set_props("map-search-status", {
      children: "",
      className: "forecast-map-search__status",
    });
  }

  function currentEngine() {
    if (lastState && lastState.engine) {
      return lastState.engine;
    }
    if (activeEngine) {
      return activeEngine;
    }
    return "openlayers";
  }

  function flyTo(goto) {
    if (goto && goto.lon != null && goto.lat != null) {
      lastPlaceGoto = goto;
    }
    if (currentEngine() === "cesium") {
      if (
        global.ForecastMapCesium &&
        typeof global.ForecastMapCesium.flyToPlace === "function"
      ) {
        return global.ForecastMapCesium.flyToPlace(goto);
      }
      return { ok: false, message: "Globe map is not ready" };
    }
    if (
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.flyToPlace === "function"
    ) {
      return global.ForecastMapOpenLayers.flyToPlace(goto);
    }
    return { ok: true };
  }

  function applyFlyToSideEffects(result) {
    if (!result || result.skipped) {
      return result;
    }
    if (result.ok === false) {
      publishPlaceStatus(result);
      return result;
    }
    return result;
  }

  var REGION_MAX_BYTES = 5 * 1024 * 1024;
  var REGION_SOFT_VERTICES = 20000;
  var REGION_HARD_VERTICES = 50000;
  var REGION_WORKER_BYTES = 1024 * 1024;
  var REGION_SIMPLIFY_TOLERANCES = [
    0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05,
  ];

  function setRegionStatus(message, kind) {
    if (
      !global.dash_clientside ||
      typeof global.dash_clientside.set_props !== "function"
    ) {
      return;
    }
    var className = "forecast-map-search__status";
    if (kind === "warning") {
      className += " is-warning";
    } else if (kind === "info") {
      className += " is-info";
    }
    global.dash_clientside.set_props("map-search-status", {
      children: message || "",
      className: className,
    });
  }

  function setRegionMeta(meta) {
    if (
      !global.dash_clientside ||
      typeof global.dash_clientside.set_props !== "function"
    ) {
      return;
    }
    global.dash_clientside.set_props("map-region-meta", { data: meta || null });
  }

  function scanCoords(geojson) {
    var count = 0;
    var minX = Infinity;
    var minY = Infinity;
    var maxX = -Infinity;
    var maxY = -Infinity;
    var projected = false;

    function visit(coord) {
      var x = Number(coord[0]);
      var y = Number(coord[1]);
      if (!isFinite(x) || !isFinite(y)) {
        return;
      }
      count += 1;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
      if (Math.abs(x) > 180.0001 || Math.abs(y) > 90.0001) {
        projected = true;
      }
    }

    function walk(node) {
      if (!node) {
        return;
      }
      if (Array.isArray(node)) {
        if (
          node.length >= 2 &&
          typeof node[0] === "number" &&
          typeof node[1] === "number"
        ) {
          visit(node);
          return;
        }
        for (var i = 0; i < node.length; i += 1) {
          walk(node[i]);
        }
        return;
      }
      if (node.type === "Feature") {
        walk(node.geometry);
        return;
      }
      if (node.type === "FeatureCollection") {
        var features = node.features || [];
        for (var f = 0; f < features.length; f += 1) {
          walk(features[f]);
        }
        return;
      }
      if (node.coordinates) {
        walk(node.coordinates);
      } else if (node.geometries) {
        for (var g = 0; g < node.geometries.length; g += 1) {
          walk(node.geometries[g]);
        }
      }
    }

    walk(geojson);
    return {
      count: count,
      projected: projected,
      bbox: count
        ? [minX, minY, maxX, maxY]
        : null,
    };
  }

  function geometryIsDrawable(geometry) {
    if (!geometry || !geometry.type) {
      return false;
    }
    return (
      geometry.type === "Polygon" ||
      geometry.type === "MultiPolygon" ||
      geometry.type === "LineString" ||
      geometry.type === "MultiLineString" ||
      geometry.type === "GeometryCollection"
    );
  }

  function filterDrawableGeojson(geojson) {
    if (!geojson || !geojson.type) {
      return null;
    }
    if (geojson.type === "Feature") {
      if (!geometryIsDrawable(geojson.geometry)) {
        return null;
      }
      return geojson;
    }
    if (geojson.type === "FeatureCollection") {
      var kept = [];
      var features = geojson.features || [];
      for (var i = 0; i < features.length; i += 1) {
        var feature = features[i];
        if (
          feature &&
          feature.type === "Feature" &&
          geometryIsDrawable(feature.geometry)
        ) {
          kept.push(feature);
        } else if (geometryIsDrawable(feature)) {
          kept.push({
            type: "Feature",
            properties: {},
            geometry: feature,
          });
        }
      }
      if (!kept.length) {
        return null;
      }
      return { type: "FeatureCollection", features: kept };
    }
    if (!geometryIsDrawable(geojson)) {
      return null;
    }
    return {
      type: "Feature",
      properties: {},
      geometry: geojson,
    };
  }

  // OL is loaded via CDN for every map mode; use it to simplify regions.
  function requireOlSimplify() {
    if (
      typeof ol === "undefined" ||
      !ol.format ||
      typeof ol.format.GeoJSON !== "function"
    ) {
      throw new Error("OpenLayers failed to load; cannot simplify GeoJSON regions");
    }
  }

  function simplifyGeojsonWithOl(geojson, tolerance) {
    requireOlSimplify();
    var fmt = new ol.format.GeoJSON();
    var features = fmt.readFeatures(geojson, {
      dataProjection: "EPSG:4326",
      featureProjection: "EPSG:4326",
    });
    if (!features || !features.length) {
      return geojson;
    }
    for (var i = 0; i < features.length; i += 1) {
      var geom = features[i].getGeometry();
      if (!geom || typeof geom.simplify !== "function") {
        throw new Error("OpenLayers geometry.simplify is unavailable");
      }
      features[i].setGeometry(geom.simplify(tolerance));
    }
    return fmt.writeFeaturesObject(features, {
      dataProjection: "EPSG:4326",
      featureProjection: "EPSG:4326",
    });
  }

  function autoSimplifyGeojson(geojson) {
    var count = scanCoords(geojson).count;
    if (count <= REGION_SOFT_VERTICES) {
      return { geojson: geojson, simplified: false, vertexCount: count };
    }
    requireOlSimplify();
    var current = geojson;
    for (var i = 0; i < REGION_SIMPLIFY_TOLERANCES.length; i += 1) {
      current = simplifyGeojsonWithOl(geojson, REGION_SIMPLIFY_TOLERANCES[i]);
      count = scanCoords(current).count;
      if (count <= REGION_SOFT_VERTICES) {
        return { geojson: current, simplified: true, vertexCount: count };
      }
    }
    return { geojson: current, simplified: true, vertexCount: count };
  }

  function parseJsonText(text, useWorker) {
    if (!useWorker || typeof Worker === "undefined") {
      return Promise.resolve(JSON.parse(text));
    }
    return new Promise(function (resolve, reject) {
      var blob = new Blob(
        [
          "self.onmessage=function(e){try{self.postMessage({ok:1,data:JSON.parse(e.data)});}catch(err){self.postMessage({ok:0,message:String(err&&err.message||err)});}};",
        ],
        { type: "application/javascript" }
      );
      var url = URL.createObjectURL(blob);
      var worker = new Worker(url);
      worker.onmessage = function (event) {
        URL.revokeObjectURL(url);
        worker.terminate();
        if (event.data && event.data.ok) {
          resolve(event.data.data);
        } else {
          reject(
            new Error(
              (event.data && event.data.message) || "Invalid GeoJSON"
            )
          );
        }
      };
      worker.onerror = function (err) {
        URL.revokeObjectURL(url);
        worker.terminate();
        reject(err);
      };
      worker.postMessage(text);
    });
  }

  function zoomFromBbox(bbox) {
    var span = Math.max(bbox[2] - bbox[0], bbox[3] - bbox[1], 1e-6);
    var zoom = Math.log2(360 / span);
    if (!isFinite(zoom)) {
      return 8;
    }
    return Math.max(1, Math.min(14, Math.floor(zoom)));
  }

  function applyUploadedRegion(geojson, fileName) {
    try {
      requireOlSimplify();
    } catch (err) {
      setRegionStatus(
        (err && err.message) || "OpenLayers is required to display this region",
        "warning"
      );
      return;
    }
    var drawable = filterDrawableGeojson(geojson);
    if (!drawable) {
      setRegionStatus(
        "GeoJSON must include Polygon or LineString geometry",
        "warning"
      );
      return;
    }
    var scan = scanCoords(drawable);
    if (scan.projected) {
      setRegionStatus(
        "Coordinates look projected; export as WGS84 (EPSG:4326) lon/lat",
        "warning"
      );
      return;
    }
    var prepared;
    try {
      prepared = autoSimplifyGeojson(drawable);
    } catch (err) {
      setRegionStatus(
        (err && err.message) || "OpenLayers is required to display this region",
        "warning"
      );
      return;
    }
    if (prepared.vertexCount > REGION_HARD_VERTICES) {
      setRegionStatus(
        "Region too complex even after simplify; simplify offline then retry",
        "warning"
      );
      return;
    }
    var bbox = scanCoords(prepared.geojson).bbox;
    if (!bbox) {
      setRegionStatus("Could not read coordinates from GeoJSON", "warning");
      return;
    }
    var lon = (bbox[0] + bbox[2]) / 2;
    var lat = (bbox[1] + bbox[3]) / 2;
    var goto = {
      lon: lon,
      lat: lat,
      zoom: zoomFromBbox(bbox),
      bbox: bbox,
      geojson: prepared.geojson,
      ts: Date.now(),
    };
    var result = applyFlyToSideEffects(flyTo(goto));
    // Keep the selection (and clear control) even if this TMS cannot show it.
    setRegionMeta({
      name: fileName || null,
      bbox: bbox,
      vertexCount: prepared.vertexCount,
      simplified: !!prepared.simplified,
      ts: Date.now(),
    });
    if (result && result.ok === false) {
      return;
    }
    if (prepared.simplified) {
      setRegionStatus("Region simplified for display", "info");
    } else {
      setRegionStatus("", null);
    }
  }

  function handleRegionFile(file) {
    if (!file) {
      return;
    }
    if (file.size > REGION_MAX_BYTES) {
      setRegionStatus(
        "File too large (max 5 MB); simplify or crop offline then retry",
        "warning"
      );
      return;
    }
    var reader = new FileReader();
    reader.onerror = function () {
      setRegionStatus("Could not read file", "warning");
    };
    reader.onload = function () {
      var text = reader.result;
      if (typeof text !== "string") {
        setRegionStatus("Could not read file", "warning");
        return;
      }
      parseJsonText(text, file.size >= REGION_WORKER_BYTES)
        .then(function (parsed) {
          applyUploadedRegion(parsed, file.name);
        })
        .catch(function () {
          setRegionStatus("Invalid GeoJSON", "warning");
        });
    };
    reader.readAsText(file);
  }

  function ensureRegionFileInput() {
    var input = document.getElementById("map-region-file");
    if (input) {
      return input;
    }
    // dash.html has no Input component; inject a local file picker in the DOM.
    var actions = document.querySelector(".forecast-map-search__actions");
    if (!actions) {
      return null;
    }
    input = document.createElement("input");
    input.id = "map-region-file";
    input.type = "file";
    input.accept = ".geojson,.json,application/geo+json,application/json";
    input.className = "forecast-map-search__region-input";
    input.setAttribute("aria-hidden", "true");
    input.tabIndex = -1;
    actions.appendChild(input);
    return input;
  }

  function ensureRegionUpload() {
    if (global.__forecastRegionUploadBound) {
      return;
    }
    global.__forecastRegionUploadBound = true;
    document.addEventListener("click", function (event) {
      var btn =
        event.target && event.target.closest
          ? event.target.closest("#map-region-upload")
          : null;
      if (!btn) {
        return;
      }
      event.preventDefault();
      var input = ensureRegionFileInput();
      if (input) {
        input.click();
      }
    });
    document.addEventListener("change", function (event) {
      var input = event.target;
      if (!input || input.id !== "map-region-file") {
        return;
      }
      var file = input.files && input.files[0];
      handleRegionFile(file);
      input.value = "";
    });
  }

  function clearPlace() {
    lastPlaceGoto = null;
    if (
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.clearLastPlace === "function"
    ) {
      global.ForecastMapOpenLayers.clearLastPlace();
    }
    if (
      global.ForecastMapCesium &&
      typeof global.ForecastMapCesium.clearLastPlace === "function"
    ) {
      global.ForecastMapCesium.clearLastPlace();
    }
    publishPlaceStatus({ ok: true });
    setRegionMeta(null);
  }

  function setBtnClass(id, className) {
    var el = document.getElementById(id);
    if (el) {
      el.className = className;
    }
  }

  function clearNorthUpSelection() {
    global.__forecastNorthUpOn = false;
    global.__forecastNorthUpLockOn = false;
    setNorthUpClickEnabled(false);
    setNorthUpLockEnabled(false);
    setBtnClass("map-north-up-btn", "forecast-map-north-up__btn");
    setBtnClass("map-north-up-lock-btn", "forecast-map-north-up__btn");
  }

  /** Exit one-shot pick mode after a map click (keep the applied rotation). */
  function clearNorthUpPickMode() {
    global.__forecastNorthUpOn = false;
    setNorthUpClickEnabled(false);
    setBtnClass("map-north-up-btn", "forecast-map-north-up__btn");
  }

  function isOrientationRotated() {
    return !!(
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.isOrientationRotated === "function" &&
      global.ForecastMapOpenLayers.isOrientationRotated()
    );
  }

  function resetOrientation() {
    clearNorthUpSelection();
    if (
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.resetOrientation === "function"
    ) {
      global.ForecastMapOpenLayers.resetOrientation();
    }
  }

  function setNorthUpClickEnabled(enabled) {
    if (
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.setNorthUpClickEnabled === "function"
    ) {
      global.ForecastMapOpenLayers.setNorthUpClickEnabled(enabled);
    }
    ensureNorthUpEsc();
  }

  function setNorthUpLockEnabled(enabled) {
    if (
      global.ForecastMapOpenLayers &&
      typeof global.ForecastMapOpenLayers.setNorthUpLockEnabled === "function"
    ) {
      global.ForecastMapOpenLayers.setNorthUpLockEnabled(enabled);
    }
    ensureNorthUpEsc();
  }

  function ensureNorthUpEsc() {
    if (northUpEscBound) {
      return;
    }
    northUpEscBound = true;
    global.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") {
        return;
      }
      var picking = !!global.__forecastNorthUpOn;
      var locking = !!global.__forecastNorthUpLockOn;
      var rotated = isOrientationRotated();
      if (!picking && !locking && !rotated) {
        return;
      }
      if (
        global.ForecastTimelineKeys &&
        global.ForecastTimelineKeys.isEditableTarget(event.target)
      ) {
        return;
      }
      event.preventDefault();
      // Esc cancels pick/lock and restores default orientation.
      resetOrientation();
    });
  }

  function mapSearchHitButtons() {
    var root = document.getElementById("map-search-suggestions");
    if (!root) {
      return [];
    }
    return Array.prototype.slice.call(
      root.querySelectorAll("[data-search-index]")
    );
  }

  function setMapSearchActive(index) {
    var hits = mapSearchHitButtons();
    if (!hits.length) {
      return;
    }
    var next = ((index % hits.length) + hits.length) % hits.length;
    hits.forEach(function (btn, i) {
      var on = i === next;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      if (on && typeof btn.scrollIntoView === "function") {
        btn.scrollIntoView({ block: "nearest" });
      }
    });
    if (
      global.dash_clientside &&
      typeof global.dash_clientside.set_props === "function"
    ) {
      global.dash_clientside.set_props("map-search-active", { data: next });
    }
  }

  function currentMapSearchActive() {
    var hits = mapSearchHitButtons();
    for (var i = 0; i < hits.length; i += 1) {
      if (hits[i].classList.contains("is-active")) {
        return i;
      }
    }
    return hits.length ? 0 : -1;
  }

  function onMapSearchKeydown(event) {
    var input = document.getElementById("map-search-query");
    if (!input || document.activeElement !== input) {
      return;
    }
    var panel = document.getElementById("map-search");
    var open = panel && panel.classList.contains("has-results");
    var hits = mapSearchHitButtons();
    var key = event.key;

    if (key === "Escape") {
      event.preventDefault();
      if (open) {
        if (panel) {
          panel.classList.remove("has-results");
        }
        if (
          global.dash_clientside &&
          typeof global.dash_clientside.set_props === "function"
        ) {
          global.dash_clientside.set_props("map-search", {
            className: "forecast-map-search",
          });
          global.dash_clientside.set_props("map-search-active", { data: -1 });
        }
        return;
      }
      var shell = document.getElementById("map-search-shell");
      if (shell && !shell.classList.contains("is-collapsed")) {
        if (
          global.dash_clientside &&
          typeof global.dash_clientside.set_props === "function"
        ) {
          global.dash_clientside.set_props("map-search-shell", {
            className: "forecast-map-search-shell is-collapsed",
          });
        } else {
          shell.classList.add("is-collapsed");
        }
        input.blur();
      }
      return;
    }

    if (!open || !hits.length) {
      return;
    }

    if (key === "ArrowDown") {
      event.preventDefault();
      setMapSearchActive(currentMapSearchActive() + 1);
      return;
    }
    if (key === "ArrowUp") {
      event.preventDefault();
      setMapSearchActive(currentMapSearchActive() - 1);
      return;
    }
    if (key === "Home") {
      event.preventDefault();
      setMapSearchActive(0);
      return;
    }
    if (key === "End") {
      event.preventDefault();
      setMapSearchActive(hits.length - 1);
    }
    // Enter is handled by Dash n_submit using map-search-active.
  }

  function ensureMapSearchKeys() {
    if (global.__mapSearchKeysBound) {
      return;
    }
    global.__mapSearchKeysBound = true;
    document.addEventListener("keydown", onMapSearchKeydown);
    document.addEventListener("mouseover", function (event) {
      var btn =
        event.target && event.target.closest
          ? event.target.closest("[data-search-index]")
          : null;
      if (!btn) {
        return;
      }
      var panel = document.getElementById("map-search");
      if (!panel || !panel.classList.contains("has-results")) {
        return;
      }
      var index = Number(btn.getAttribute("data-search-index"));
      if (!isFinite(index)) {
        return;
      }
      if (btn.classList.contains("is-active")) {
        return;
      }
      setMapSearchActive(index);
    });
  }

  var forecastAbort = null;
  var forecastSearchGen = 0;
  var lastForecastSearchKey = "";
  var lastForecastItems = null;

  function collectionIdList(value) {
    if (!value) {
      return [];
    }
    if (Array.isArray(value)) {
      return value.filter(Boolean);
    }
    return [value];
  }

  function dateToRefTime(day) {
    if (!day || typeof day !== "string") {
      return null;
    }
    return day.indexOf("T") === -1 ? day + "T00:00:00Z" : day;
  }

  function publicTilerBase() {
    if (lastState && lastState.leadtimeCogUrls && lastState.leadtimeCogUrls.tilerBase) {
      return lastState.leadtimeCogUrls.tilerBase;
    }
    var origin =
      global.location && global.location.origin ? global.location.origin : "";
    return origin + "/tiles";
  }

  function isDataCog(asset) {
    if (!asset || typeof asset !== "object") {
      return false;
    }
    var roles = asset.roles || [];
    var media = String(asset.type || asset.media_type || "").toLowerCase();
    return roles.indexOf("data") !== -1 || media.indexOf("cog") !== -1;
  }

  var WEB_MERCATOR_Z0 = 156543.03392804097;

  function gsdFromAssets(assets) {
    var keys = Object.keys(assets || {});
    var i;
    for (i = 0; i < keys.length; i += 1) {
      var asset = assets[keys[i]];
      if (!isDataCog(asset)) {
        continue;
      }
      var transform = asset["proj:transform"];
      var gsd = transform && transform.length
        ? Math.abs(Number(transform[0]))
        : Number(asset.gsd);
      if (isFinite(gsd) && gsd > 0) {
        return gsd;
      }
    }
    return null;
  }

  /**
   * Highest TMS zoom to fetch for a COG.
   *
   * Native resolution is where the cell matches ``gsd``. A fitted world or
   * polar view is often already near that, so allow several extra octaves
   * for zoom-in before stretching. Extreme zooms (empty 25 km cells at
   * z=16) are still skipped.
   */
  function maxZoomForGsd(gsd, resolutions) {
    var size = Number(gsd);
    if (!isFinite(size) || size <= 0) {
      return null;
    }
    var minCell = size / 32;
    var i;
    if (resolutions && resolutions.length) {
      for (i = 0; i < resolutions.length; i += 1) {
        if (resolutions[i] < minCell) {
          return Math.max(0, i - 1);
        }
      }
      return resolutions.length - 1;
    }
    for (i = 0; i <= 22; i += 1) {
      if (WEB_MERCATOR_Z0 / Math.pow(2, i) < minCell) {
        return Math.max(0, i - 1);
      }
    }
    return null;
  }

  function orderedAssetKeys(assets) {
    var rows = [];
    Object.keys(assets || {}).forEach(function (key) {
      if (!isDataCog(assets[key])) {
        return;
      }
      var parsed = Date.parse(key);
      if (!isFinite(parsed)) {
        return;
      }
      rows.push({ key: key, t: parsed });
    });
    rows.sort(function (a, b) {
      return a.t - b.t;
    });
    return rows.map(function (row) {
      return row.key;
    });
  }

  function bandsFromAssets(assets) {
    var keys = Object.keys(assets || {});
    var i;
    for (i = 0; i < keys.length; i += 1) {
      var asset = assets[keys[i]];
      if (!isDataCog(asset)) {
        continue;
      }
      var bandProps = asset["forecast:bands"] || [];
      if (!bandProps.length) {
        continue;
      }
      var bands = {};
      var bi;
      for (bi = 0; bi < bandProps.length; bi += 1) {
        var band = bandProps[bi];
        if (band && band.name != null && band.index != null) {
          bands[String(band.name)] = Number(band.index);
        }
      }
      if (Object.keys(bands).length) {
        return { bands: bands, bandProps: bandProps };
      }
    }
    return { bands: {}, bandProps: [] };
  }

  function rescaleFromBands(bandProps, bandIndex) {
    var i;
    for (i = 0; i < (bandProps || []).length; i += 1) {
      var band = bandProps[i];
      if (!band || Number(band.index) !== Number(bandIndex)) {
        continue;
      }
      var minimum = band.STATISTICS_MINIMUM;
      var maximum = band.STATISTICS_MAXIMUM;
      if (minimum == null || maximum == null) {
        return null;
      }
      return [Number(minimum), Number(maximum)];
    }
    return null;
  }

  function inferStepUnit(times) {
    if (!times || times.length < 2) {
      return "day";
    }
    var gaps = [];
    var i;
    for (i = 1; i < times.length; i += 1) {
      var delta = Date.parse(times[i]) - Date.parse(times[i - 1]);
      if (isFinite(delta) && delta > 0) {
        gaps.push(delta / 1000);
      }
    }
    if (!gaps.length) {
      return "day";
    }
    var median = gaps.slice().sort(function (a, b) {
      return a - b;
    })[Math.floor(gaps.length / 2)];
    var day = 86400;
    if (median < day * 0.75) {
      return "hour";
    }
    if (median < 7 * day * 0.75) {
      return "day";
    }
    if (median < 30 * day * 0.75) {
      return "week";
    }
    return "month";
  }

  function publishDashMapState() {
    if (!lastState) {
      return;
    }
    setDashProps("map-state", { data: lastState });
  }

  function setDashProps(id, props) {
    if (
      global.dash_clientside &&
      typeof global.dash_clientside.set_props === "function"
    ) {
      global.dash_clientside.set_props(id, props);
    }
  }

  function paintLeadtimeCache(cache, lead) {
    var nextLead = lead == null ? 0 : Number(lead);
    var layers = layersFromLeadtimeCogUrls(cache, nextLead);
    if (!layers.length) {
      return false;
    }
    var mode =
      desiredMode ||
      cache.viewMode ||
      (lastState && lastState.mode) ||
      "global_3857";
    var base = lastState || {};
    // Full applyState so a globe switch that has not yet painted still
    // creates Cesium imagery. Scrub continues to use applyLeadtimeIndex.
    applyState(
      Object.assign({}, base, {
        engine: engineForMode(mode),
        mode: mode,
        layers: layers,
        leadtimeCogUrls: cache,
        lead: nextLead,
        view: base.view,
        revision: LOCAL_REVISION_BASE + (base.revision || 0) + 1,
      })
    );
    publishDashMapState();
    return true;
  }

  /**
   * One slim STAC search per date / collection. Fills the leadtime axis and
   * variables, then paints Item tiles without waiting on Dash.
   */
  function loadForecast(options) {
    var opts = options || {};
    var day = opts.date;
    var ids = collectionIdList(opts.collections);
    var datetime = dateToRefTime(day);
    if (!ids.length) {
      lastForecastSearchKey = "";
      if (forecastAbort && typeof forecastAbort.abort === "function") {
        forecastAbort.abort();
      }
      if (lastState && (lastState.layers || lastState.leadtimeCogUrls)) {
        applyState(
          Object.assign({}, lastState, {
            layers: [],
            leadtimeCogUrls: null,
            revision: LOCAL_REVISION_BASE + (lastState.revision || 0) + 1,
          })
        );
        publishDashMapState();
      }
      hideBusyChrome();
      return;
    }
    if (!datetime) {
      hideBusyChrome();
      return;
    }
    var searchKey = ids.join(",") + "|" + datetime;
    if (searchKey === lastForecastSearchKey && hasLeadtimeCogUrls()) {
      if (opts.variable != null && lastState && lastState.leadtimeCogUrls) {
        applyBand(opts.variable, opts.displayStyle);
      }
      return;
    }
    if (forecastAbort && typeof forecastAbort.abort === "function") {
      forecastAbort.abort();
    }
    forecastAbort =
      typeof AbortController === "function" ? new AbortController() : null;
    var gen = (forecastSearchGen += 1);
    var signal = forecastAbort ? forecastAbort.signal : undefined;
    fetch("/api/search", {
      method: "POST",
      headers: {
        Accept: "application/geo+json, application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        collections: ids,
        "filter-lang": "cql2-json",
        filter: {
          op: "=",
          args: [{ property: "datetime" }, { timestamp: datetime }],
        },
        limit: ids.length,
        fields: {
          include: ["id", "bbox", "collection", "assets"],
          exclude: ["geometry", "links", "assets.*.href", "assets.*.alternate"],
        },
      }),
      signal: signal,
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("STAC search failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (gen !== forecastSearchGen) {
          return;
        }
        var features = (body && body.features) || [];
        if (!features.length) {
          endDashMapWait();
          return;
        }
        applySearchFeatures(features, {
          date: day,
          datetime: datetime,
          collections: ids,
          variable: opts.variable,
          colormap: opts.colormap,
          viewMode: opts.viewMode,
          displayStyle: opts.displayStyle,
        });
        lastForecastSearchKey = searchKey;
      })
      .catch(function (error) {
        if (error && error.name === "AbortError") {
          return;
        }
        if (gen === forecastSearchGen) {
          lastForecastSearchKey = "";
          endDashMapWait();
        }
      });
  }

  function applySearchFeatures(features, opts) {
    var collections = {};
    var shortestTimes = null;
    var bandTable = { bands: {}, bandProps: [] };
    var i;
    for (i = 0; i < features.length; i += 1) {
      var feature = features[i];
      var collectionId = feature.collection || (opts.collections || [])[0];
      if (!collectionId || !feature.id) {
        continue;
      }
      var assets = feature.assets || {};
      var keys = orderedAssetKeys(assets);
      if (!keys.length) {
        continue;
      }
      if (!Object.keys(bandTable.bands).length) {
        bandTable = bandsFromAssets(assets);
      }
      collections[collectionId] = {
        hrefs: keys,
        itemId: feature.id,
        bbox: feature.bbox || null,
      };
      var gsd = gsdFromAssets(assets);
      if (gsd) {
        collections[collectionId].gsd = gsd;
      }
      if (!shortestTimes || keys.length < shortestTimes.length) {
        shortestTimes = keys;
      }
    }
    if (!Object.keys(collections).length || !shortestTimes) {
      endDashMapWait();
      return;
    }
    var previousIds = Object.keys(
      (lastForecastItems && lastForecastItems.collections) || {}
    );
    lastForecastItems = { collections: collections, bands: bandTable };
    var times = shortestTimes;
    setDashProps("leadtime-axis", {
      data: { times: times, step_unit: inferStepUnit(times) },
    });
    var bandIndex = resolveBandIndex(bandTable.bands, opts.variable);
    var previousStyle = opts.displayStyle || {};
    var collectionsChanged =
      previousIds.length > 0 &&
      previousIds.slice().sort().join("\0") !==
        Object.keys(collections).sort().join("\0");
    var keepLock =
      !collectionsChanged &&
      previousStyle.locked &&
      previousStyle.vmin != null &&
      previousStyle.vmax != null;
    var rescale = null;
    if (keepLock) {
      rescale = [Number(previousStyle.vmin), Number(previousStyle.vmax)];
    } else {
      rescale = rescaleFromBands(bandTable.bandProps, bandIndex);
    }
    if (!rescale) {
      rescale =
        previousStyle.vmin != null && previousStyle.vmax != null
          ? [Number(previousStyle.vmin), Number(previousStyle.vmax)]
          : [0, 1];
    }
    var colormap =
      opts.colormap || previousStyle.colormap || "blues_r";
    if (!keepLock) {
      setDashProps("display-style", {
        data: {
          colormap: colormap,
          vmin: rescale[0],
          vmax: rescale[1],
          domain_min: rescale[0],
          domain_max: rescale[1],
          locked: false,
          source: "stats",
        },
      });
    }
    var mode = opts.viewMode || desiredMode || (lastState && lastState.mode) || "";
    var cache = {
      tilerBase: publicTilerBase(),
      tileMatrixSet: tmsForMode(mode),
      viewMode: mode,
      colormap: colormap,
      rescale: rescale,
      bidx: bandIndex,
      refTime: opts.datetime,
      collections: collections,
    };
    paintLeadtimeCache(cache, 0);
    if (Object.keys(bandTable.bands).length) {
      var options = Object.keys(bandTable.bands).map(function (name) {
        return { label: name, value: bandTable.bands[name] };
      });
      setDashProps("variable-dropdown", {
        options: options,
        value: bandIndex,
      });
    }
  }

  function resolveBandIndex(bands, preferred) {
    var values = Object.keys(bands || {}).map(function (name) {
      return bands[name];
    });
    if (preferred != null && values.indexOf(Number(preferred)) !== -1) {
      return Number(preferred);
    }
    if (preferred != null && values.indexOf(preferred) !== -1) {
      return preferred;
    }
    return values.length ? values[0] : null;
  }

  function applyBand(bandIndex, displayStyle) {
    if (!lastState || !lastState.leadtimeCogUrls || bandIndex == null) {
      return;
    }
    var cache = Object.assign({}, lastState.leadtimeCogUrls);
    if (Number(cache.bidx) === Number(bandIndex)) {
      return;
    }
    cache.bidx = Number(bandIndex);
    var style = displayStyle || {};
    // A new variable must not keep a pinned range from the previous band.
    if (lastForecastItems && lastForecastItems.bands) {
      var rescale = rescaleFromBands(
        lastForecastItems.bands.bandProps,
        cache.bidx
      );
      if (rescale) {
        cache.rescale = rescale;
        setDashProps("display-style", {
          data: {
            colormap: cache.colormap || style.colormap || "blues_r",
            vmin: rescale[0],
            vmax: rescale[1],
            domain_min: rescale[0],
            domain_max: rescale[1],
            locked: false,
            source: "stats",
          },
        });
      }
    }
    paintLeadtimeCache(cache, lastState.lead || 0);
  }

  function applyStyle(style) {
    if (!lastState || !lastState.leadtimeCogUrls || !style) {
      return;
    }
    var cache = lastState.leadtimeCogUrls;
    var nextCmap = style.colormap || cache.colormap;
    var nextScale =
      style.vmin != null && style.vmax != null
        ? [Number(style.vmin), Number(style.vmax)]
        : cache.rescale;
    if (
      nextCmap === cache.colormap &&
      cache.rescale &&
      nextScale &&
      Number(cache.rescale[0]) === Number(nextScale[0]) &&
      Number(cache.rescale[1]) === Number(nextScale[1])
    ) {
      return;
    }
    cache = Object.assign({}, cache, {
      colormap: nextCmap,
      rescale: nextScale,
    });
    paintLeadtimeCache(cache, lastState.lead || 0);
  }

  function applyAutoScale() {
    if (!lastState || !lastState.leadtimeCogUrls || !lastForecastItems) {
      return;
    }
    var cache = lastState.leadtimeCogUrls;
    var rescale = rescaleFromBands(
      lastForecastItems.bands && lastForecastItems.bands.bandProps,
      cache.bidx
    );
    if (!rescale) {
      return;
    }
    setDashProps("display-style", {
      data: {
        colormap: cache.colormap || "blues_r",
        vmin: rescale[0],
        vmax: rescale[1],
        domain_min: rescale[0],
        domain_max: rescale[1],
        locked: false,
        source: "stats",
      },
    });
    paintLeadtimeCache(
      Object.assign({}, cache, { rescale: rescale }),
      lastState.lead || 0
    );
  }

  ensureMapSearchKeys();
  ensureViewModeResetClick();
  ensureRegionUpload();

  global.ForecastMap = {
    applyState: applyState,
    applyViewMode: applyViewMode,
    applyLeadtimeIndex: applyLeadtimeIndex,
    loadForecast: loadForecast,
    applyBand: applyBand,
    applyStyle: applyStyle,
    applyAutoScale: applyAutoScale,
    setTilesReady: setTilesReady,
    isTilesReady: isTilesReady,
    prefetchTileImages: prefetchTileImages,
    maxZoomForGsd: maxZoomForGsd,
    flyTo: flyTo,
    clearPlace: clearPlace,
    setNorthUpClickEnabled: setNorthUpClickEnabled,
    setNorthUpLockEnabled: setNorthUpLockEnabled,
    clearNorthUpPickMode: clearNorthUpPickMode,
  };
})(window);
