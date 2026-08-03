/** OpenLayers renderer for the forecast map host. */

(function (global) {
  "use strict";

  var HOST_ID = "forecast-map-ol";
  var forecastLayersById = {};
  // Leadtime / style swaps in flight: the incoming tiles paint above the
  // stable overlay so the previous step stays visible until they are ready.
  var pendingById = {};
  var transitionGeneration = 0;
  var map = null;
  var basemapLayer = null;
  var basemapUrl = null;
  var currentProjection = null;
  var currentTileGrid = null;
  var registeredProj4 = {};
  // Extent to fit again once the map has a real size on screen.
  var pendingFitExtent = null;
  // Overlays added while size was 0 need a source refresh once layout runs.
  var overlaysAwaitingSize = false;
  var applyGeneration = 0;

  function getHost() {
    return document.getElementById(HOST_ID);
  }

  function mapHasSize() {
    var size = map && map.getSize();
    return !!(size && size[0] && size[1]);
  }

  function layerSourceUrl(layer) {
    var source = layer && layer.getSource && layer.getSource();
    if (!source) {
      return null;
    }
    if (source.getUrls) {
      return source.getUrls()[0];
    }
    return source.getUrl && source.getUrl();
  }

  function refreshOverlaySources() {
    Object.keys(pendingById).forEach(cancelPending);
    Object.keys(forecastLayersById).forEach(function (layerId) {
      var layer = forecastLayersById[layerId];
      var url = layerSourceUrl(layer);
      if (url) {
        layer.setSource(createXyzSource(url, currentTileGrid));
      }
    });
  }

  function cancelPending(layerId) {
    var pending = pendingById[layerId];
    if (!pending) {
      return;
    }
    if (pending.timeout) {
      clearTimeout(pending.timeout);
    }
    if (pending.onRender && map) {
      map.un("rendercomplete", pending.onRender);
    }
    if (pending.source && pending.onTileStart) {
      pending.source.un("tileloadstart", pending.onTileStart);
      pending.source.un("tileloadend", pending.onTileEnd);
      pending.source.un("tileloaderror", pending.onTileEnd);
    }
    if (map && pending.layer) {
      map.removeLayer(pending.layer);
    }
    delete pendingById[layerId];
  }

  function hasPendingSwap() {
    return Object.keys(pendingById).length > 0;
  }

  /**
   * Stack a new XYZ source above the stable overlay and promote it once ready.
   *
   * The default is a progressive reveal: unloaded tiles are transparent so the
   * previous step shows through. For jumps (`holdUntilReady`) the incoming
   * layer stays invisible until its viewport tiles have loaded, then cuts over
   * in one go so the user never sees a patchwork of two steps.
   */
  function beginSmoothSwap(layerId, layerDesc, index, options) {
    var holdUntilReady = !!(options && options.holdUntilReady);
    var zIndex = 100 + index;
    var targetUrl = layerDesc.tileUrl;
    var targetOpacity = layerDesc.opacity == null ? 1 : layerDesc.opacity;
    var existingPending = pendingById[layerId];
    if (existingPending && layerSourceUrl(existingPending.layer) === targetUrl) {
      existingPending.zIndex = zIndex;
      existingPending.holdUntilReady = holdUntilReady;
      if (!holdUntilReady) {
        existingPending.layer.setOpacity(targetOpacity);
      }
      existingPending.layer.setVisible(layerDesc.visible !== false);
      return;
    }
    cancelPending(layerId);

    var generation = (transitionGeneration += 1);
    var source = createXyzSource(targetUrl, currentTileGrid);
    var incoming = new ol.layer.Tile({
      source: source,
      opacity: holdUntilReady ? 0 : targetOpacity,
      visible: layerDesc.visible !== false,
      zIndex: zIndex + 50,
    });

    var entry = {
      layer: incoming,
      source: source,
      generation: generation,
      zIndex: zIndex,
      holdUntilReady: holdUntilReady,
      timeout: null,
      onRender: null,
      onTileStart: null,
      onTileEnd: null,
    };
    pendingById[layerId] = entry;

    var finished = false;
    var tilesLoading = 0;
    var tilesDone = 0;
    var armed = false;

    function finish() {
      if (finished) {
        return;
      }
      var current = pendingById[layerId];
      if (!current || current.generation !== generation) {
        return;
      }
      finished = true;
      if (entry.timeout) {
        clearTimeout(entry.timeout);
        entry.timeout = null;
      }
      if (entry.onRender) {
        map.un("rendercomplete", entry.onRender);
        entry.onRender = null;
      }
      if (entry.onTileStart) {
        source.un("tileloadstart", entry.onTileStart);
        source.un("tileloadend", entry.onTileEnd);
        source.un("tileloaderror", entry.onTileEnd);
        entry.onTileStart = null;
        entry.onTileEnd = null;
      }
      incoming.setOpacity(targetOpacity);
      var old = forecastLayersById[layerId];
      if (old && old !== incoming) {
        map.removeLayer(old);
      }
      incoming.setZIndex(zIndex);
      forecastLayersById[layerId] = incoming;
      delete pendingById[layerId];
    }

    function tryFinishHold() {
      if (!armed || finished || !entry.holdUntilReady) {
        return;
      }
      if (tilesLoading > 0 || tilesDone < 1) {
        return;
      }
      finish();
    }

    if (holdUntilReady) {
      entry.onTileStart = function () {
        tilesLoading += 1;
      };
      entry.onTileEnd = function () {
        tilesLoading = Math.max(0, tilesLoading - 1);
        tilesDone += 1;
        tryFinishHold();
      };
      source.on("tileloadstart", entry.onTileStart);
      source.on("tileloadend", entry.onTileEnd);
      source.on("tileloaderror", entry.onTileEnd);
    }

    map.addLayer(incoming);

    requestAnimationFrame(function () {
      if (!pendingById[layerId] || pendingById[layerId].generation !== generation) {
        return;
      }
      if (holdUntilReady) {
        // Two frames so OpenLayers can queue the viewport tile range first.
        requestAnimationFrame(function () {
          if (
            !pendingById[layerId] ||
            pendingById[layerId].generation !== generation
          ) {
            return;
          }
          armed = true;
          tryFinishHold();
          entry.onRender = function () {
            if (tilesLoading > 0) {
              return;
            }
            if (tilesDone >= 1) {
              finish();
              return;
            }
            // Cached tiles can skip load events: promote after an idle frame.
            requestAnimationFrame(function () {
              if (tilesLoading > 0 || finished) {
                return;
              }
              finish();
            });
          };
          map.once("rendercomplete", entry.onRender);
          map.render();
        });
        entry.timeout = setTimeout(finish, 2000);
        return;
      }

      entry.onRender = function () {
        finish();
      };
      map.once("rendercomplete", entry.onRender);
      map.render();
      entry.timeout = setTimeout(finish, 1500);
    });
  }

  /** Remeasure and apply a pending fit only when the host has a real size. */
  function tryPendingFit() {
    if (!map || !pendingFitExtent) {
      return;
    }
    map.updateSize();
    if (!mapHasSize()) {
      return;
    }
    fitViewExtent(map.getView(), pendingFitExtent);
    pendingFitExtent = null;
  }

  function registerProjection(code, proj4Def, extent) {
    if (!code) {
      return;
    }
    // Custom projections are defined in Python and passed through map-state.
    // Web Mercator is built into OpenLayers already.
    if (
      proj4Def &&
      typeof proj4 !== "undefined" &&
      ol.proj.proj4 &&
      !registeredProj4[code]
    ) {
      proj4.defs(code, proj4Def);
      ol.proj.proj4.register(proj4);
      registeredProj4[code] = true;
    }
    var projection = ol.proj.get(code);
    if (projection && extent && extent.length >= 4) {
      projection.setExtent(extent);
    }
    return projection;
  }

  function buildTileGrid(view) {
    if (
      !view ||
      !view.extent ||
      !view.origin ||
      !view.resolutions ||
      !view.resolutions.length
    ) {
      return null;
    }
    return new ol.tilegrid.TileGrid({
      extent: view.extent,
      origin: view.origin,
      resolutions: view.resolutions,
      tileSize: 256,
    });
  }

  function createXyzSource(url, tileGrid) {
    var options = {
      url: url,
      crossOrigin: "anonymous",
    };
    if (tileGrid) {
      options.tileGrid = tileGrid;
      options.projection = currentProjection;
    }
    return new ol.source.XYZ(options);
  }

  function ensureMap() {
    if (map) {
      return map;
    }
    if (typeof ol === "undefined") {
      console.error("ForecastMap: OpenLayers (ol) is not loaded");
      return null;
    }
    var host = getHost();
    if (!host) {
      return null;
    }

    basemapLayer = new ol.layer.Tile({
      source: new ol.source.XYZ({
        url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        attributions: "© OpenStreetMap contributors",
      }),
      zIndex: 0,
    });
    basemapUrl = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

    map = new ol.Map({
      target: host,
      layers: [basemapLayer],
      view: createGlobalView({ center: [0, 0], zoom: 0 }),
    });
    // User navigation cancels any deferred world-fit so leadtime / resize
    // cannot yank the camera back out to the default extent.
    map.on("pointerdrag", clearPendingFit);
    var viewport = map.getViewport();
    if (viewport) {
      viewport.addEventListener("wheel", clearPendingFit, { passive: true });
      viewport.addEventListener("dblclick", clearPendingFit);
    }
    // Sidebar open/close changes the host size without a map-state bump.
    if (typeof ResizeObserver !== "undefined") {
      var resizeObserver = new ResizeObserver(function () {
        if (!map) {
          return;
        }
        map.updateSize();
        tryPendingFit();
        if (overlaysAwaitingSize && mapHasSize()) {
          overlaysAwaitingSize = false;
          refreshOverlaySources();
        }
      });
      resizeObserver.observe(host);
    }
    // Leave unset so the first applyView configures projection / fit.
    currentProjection = null;
    currentTileGrid = null;
    return map;
  }

  function worldExtentFor(projectionCode) {
    var projection = ol.proj.get(projectionCode);
    return projection && projection.getExtent ? projection.getExtent() : null;
  }

  function createGlobalView(view) {
    var projectionCode = (view && view.projection) || "EPSG:3857";
    var center = (view && view.center) || [0, 0];
    var options = {
      projection: projectionCode,
      center: ol.proj.fromLonLat(center, projectionCode),
      zoom: view && view.zoom != null ? view.zoom : 0,
      // Default off so a full-world fit is one Earth, not repeated lobes.
      multiWorld: !!(view && view.multiWorld),
      showFullExtent: view && view.showFullExtent === false ? false : true,
      minZoom: view && view.minZoom != null ? view.minZoom : 0,
    };
    var extent = (view && view.extent) || worldExtentFor(projectionCode);
    if (extent) {
      options.extent = extent;
    }
    return new ol.View(options);
  }

  function clearPendingFit() {
    pendingFitExtent = null;
  }

  function fitViewExtent(olView, extent) {
    if (!olView || !extent || !mapHasSize()) {
      return;
    }
    olView.fit(extent, { size: map.getSize(), padding: [20, 20, 20, 20] });
    // Successful fit: do not re-apply on later resize / leadtime ticks.
    pendingFitExtent = null;
  }

  function setBasemap(basemap, showBasemap) {
    if (!basemapLayer) {
      return;
    }
    basemapLayer.setVisible(showBasemap !== false);
    if (!basemap || !basemap.url || showBasemap === false) {
      return;
    }
    // Keep the existing XYZ source when the URL is unchanged - recreating it
    // on every leadtime tick reloads OSM and makes the basemap flicker.
    if (basemap.url === basemapUrl) {
      return;
    }
    // OSM XYZ is always EPSG:3857; OL reprojects into polar/custom views.
    basemapLayer.setSource(
      new ol.source.XYZ({
        url: basemap.url,
        projection: "EPSG:3857",
        crossOrigin: "anonymous",
        attributions: "© OpenStreetMap contributors",
      })
    );
    basemapUrl = basemap.url;
  }

  function applyView(view) {
    if (!map || !view || !view.projection) {
      return;
    }

    var projectionCode = view.projection;
    registerProjection(projectionCode, view.proj4, view.extent);
    var tileGrid = buildTileGrid(view);
    var projectionChanged = projectionCode !== currentProjection;
    // Prefer data footprint (fitExtent) so polar forecasts fill the view;
    // otherwise fit the CRS world so Global shows the entire map on load.
    var fitExtent = view.fit
      ? view.fitExtent || view.extent || worldExtentFor(projectionCode)
      : null;

    var previousTileGrid = currentTileGrid;
    // Always assign (including null) so polar -> Global clears the custom grid.
    currentTileGrid = tileGrid;
    var gridChanged = previousTileGrid !== currentTileGrid;

    if (!projectionChanged) {
      // Keep the user's centre/zoom across leadtime and style updates.
      // Re-fitting here was resetting Global to the full world on every tick.
      if (gridChanged) {
        refreshOverlaySources();
      }
      return;
    }

    currentProjection = projectionCode;
    clearPendingFit();

    var nextView;
    if (view.fit) {
      if (view.extent && projectionCode !== "EPSG:3857") {
        nextView = new ol.View({
          projection: projectionCode,
          extent: view.extent,
          showFullExtent: true,
        });
      } else {
        nextView = createGlobalView(view);
      }
      map.setView(nextView);
      pendingFitExtent = fitExtent;
      fitViewExtent(nextView, fitExtent);
    } else {
      nextView = createGlobalView(view);
      map.setView(nextView);
    }

    // Rebuild overlay sources so polar tiles use the matching tile grid.
    refreshOverlaySources();
  }

  function syncLayers(layers, options) {
    if (!map) {
      return;
    }
    var smooth = !!(options && options.smooth);
    var holdUntilReady = !!(options && options.holdUntilReady);
    var nextIds = {};
    var i;
    var layer;
    var existing;
    var tileLayer;

    layers = layers || [];
    for (i = 0; i < layers.length; i += 1) {
      layer = layers[i];
      if (!layer || !layer.id || !layer.tileUrl) {
        continue;
      }
      nextIds[layer.id] = true;
      existing = forecastLayersById[layer.id];
      if (!existing) {
        cancelPending(layer.id);
        tileLayer = new ol.layer.Tile({
          source: createXyzSource(layer.tileUrl, currentTileGrid),
          opacity: layer.opacity == null ? 1 : layer.opacity,
          visible: layer.visible !== false,
          zIndex: 100 + i,
        });
        map.addLayer(tileLayer);
        forecastLayersById[layer.id] = tileLayer;
        continue;
      }

      if (layerSourceUrl(existing) !== layer.tileUrl) {
        if (smooth) {
          beginSmoothSwap(layer.id, layer, i, {
            holdUntilReady: holdUntilReady,
          });
          continue;
        }
        cancelPending(layer.id);
        existing.setSource(createXyzSource(layer.tileUrl, currentTileGrid));
      } else {
        // The stable layer already shows this URL; drop any stale swap.
        cancelPending(layer.id);
      }
      existing.setOpacity(layer.opacity == null ? 1 : layer.opacity);
      existing.setVisible(layer.visible !== false);
      existing.setZIndex(100 + i);
    }

    Object.keys(forecastLayersById).forEach(function (layerId) {
      if (nextIds[layerId]) {
        return;
      }
      cancelPending(layerId);
      map.removeLayer(forecastLayersById[layerId]);
      delete forecastLayersById[layerId];
    });
    Object.keys(pendingById).forEach(function (layerId) {
      if (!nextIds[layerId]) {
        cancelPending(layerId);
      }
    });
  }

  /**
   * Warm tile URLs for the current viewport so the next step paints sooner.
   *
   * Capped so warming the next leadtime cannot flood TiTiler and starve the
   * step the user is actually looking at.
   */
  function prefetchLayers(layers, options) {
    if (!map || !layers || !layers.length || !mapHasSize()) {
      return;
    }
    var view = map.getView();
    if (!view) {
      return;
    }
    var z = view.getZoom();
    if (z == null || isNaN(z)) {
      return;
    }
    z = Math.round(z);
    var zDelta = options && options.zDelta != null ? Number(options.zDelta) : 0;
    if (!isNaN(zDelta) && zDelta) {
      z = Math.max(0, z + zDelta);
    }
    var tileGrid =
      currentTileGrid ||
      ol.tilegrid.createXYZ({
        extent: ol.proj.get("EPSG:3857").getExtent(),
        maxZoom: 22,
      });
    var range;
    try {
      range = tileGrid.getTileRangeForExtentAndZ(
        view.calculateExtent(map.getSize()),
        z
      );
    } catch (err) {
      return;
    }
    if (!range) {
      return;
    }
    var maxTiles =
      options && options.maxTiles != null ? Number(options.maxTiles) : 8;
    if (isNaN(maxTiles) || maxTiles < 1) {
      maxTiles = 8;
    }
    var queued = 0;
    var i;
    var x;
    var y;
    for (i = 0; i < layers.length; i += 1) {
      var template = layers[i] && layers[i].tileUrl;
      if (!template || typeof template !== "string") {
        continue;
      }
      for (x = range.minX; x <= range.maxX && queued < maxTiles; x += 1) {
        for (y = range.minY; y <= range.maxY && queued < maxTiles; y += 1) {
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

  function setHostVisible(visible) {
    var host = getHost();
    if (!host) {
      return;
    }
    var wasHidden = host.classList.contains("forecast-map-host--hidden");
    if (visible) {
      host.classList.remove("forecast-map-host--hidden");
      // Only remeasure when the host was actually hidden - calling this on
      // every leadtime tick forces a full map redraw.
      if (wasHidden && map) {
        map.updateSize();
        tryPendingFit();
      }
      return;
    }
    host.classList.add("forecast-map-host--hidden");
  }

  function markTilesReady(generation) {
    if (generation !== applyGeneration) {
      return;
    }
    if (global.ForecastMap && global.ForecastMap.setTilesReady) {
      global.ForecastMap.setTilesReady(true);
    }
  }

  function waitForTiles(generation) {
    if (!map) {
      markTilesReady(generation);
      return;
    }
    // Defer one frame so the new XYZ sources can queue tile requests before
    // we arm rendercomplete (avoids an immediate "idle" complete).
    requestAnimationFrame(function () {
      if (generation !== applyGeneration) {
        return;
      }
      var attempts = 0;
      function tryReady() {
        if (generation !== applyGeneration) {
          return;
        }
        // Held swaps stay pending until their incoming tiles have loaded.
        if (hasPendingSwap() && attempts < 60) {
          attempts += 1;
          map.once("rendercomplete", tryReady);
          map.render();
          return;
        }
        markTilesReady(generation);
      }
      map.once("rendercomplete", tryReady);
      map.render();
    });
  }

  /**
   * Swap forecast overlay URLs for a new leadtime without changing view or
   * basemap. Used so scrub/play keep the user's zoom and centre.
   *
   * @param {Array} layers
   * @param {{holdUntilReady?: boolean, waitForTiles?: boolean}} [options]
   */
  function applyLeadtime(layers, options) {
    if (!ensureMap()) {
      if (global.ForecastMap && global.ForecastMap.setTilesReady) {
        global.ForecastMap.setTilesReady(true);
      }
      return;
    }
    var generation = (applyGeneration += 1);
    var holdUntilReady = !!(options && options.holdUntilReady);
    var waitForPaint = !!(options && options.waitForTiles);
    if (holdUntilReady) {
      // Warm the jump target so the held frame can cut over quickly.
      prefetchLayers(layers || [], { maxTiles: 16, zDelta: 0 });
    }
    // The previous step stays painted until the new tiles load (no blank frame).
    syncLayers(layers || [], {
      smooth: true,
      holdUntilReady: holdUntilReady,
    });
    // Scrub/play must not wait on rendercomplete: that stalls when the event
    // is missed. Playback pace uses hasPendingSwap instead. Date / variable
    // rebuilds pass waitForTiles so the busy banner stays until paint.
    if (waitForPaint) {
      waitForTiles(generation);
      return;
    }
    markTilesReady(generation);
  }

  function applyState(state) {
    if (!state || state.engine !== "openlayers") {
      setHostVisible(false);
      return;
    }
    setHostVisible(true);
    if (!ensureMap()) {
      return;
    }
    var generation = (applyGeneration += 1);
    if (!mapHasSize()) {
      map.updateSize();
    }
    var nextProjection = state.view && state.view.projection;
    var projectionUnchanged =
      currentProjection && nextProjection && nextProjection === currentProjection;
    if (projectionUnchanged) {
      // Leadtime / style / TMS confirmation: swap overlays only.
      setBasemap(state.basemap, state.view && state.view.showBasemap);
      syncLayers(state.layers, { smooth: true });
      markTilesReady(generation);
      return;
    }
    applyView(state.view);
    setBasemap(state.basemap, state.view && state.view.showBasemap);
    // Hard swap on a projection change: the tile grid and CRS must rebuild.
    syncLayers(state.layers, { smooth: false });
    tryPendingFit();
    // Tiles requested at 0x0 stay cached for the same z/x/y after layout.
    // Flag that case and refresh once ResizeObserver (or a later apply) has size.
    if (state.layers && state.layers.length) {
      if (!mapHasSize()) {
        overlaysAwaitingSize = true;
      } else if (overlaysAwaitingSize) {
        overlaysAwaitingSize = false;
        refreshOverlaySources();
      }
      waitForTiles(generation);
    } else {
      markTilesReady(generation);
    }
  }

  global.ForecastMapOpenLayers = {
    applyState: applyState,
    applyLeadtime: applyLeadtime,
    prefetchLayers: prefetchLayers,
    hasPendingSwap: hasPendingSwap,
  };
})(window);
