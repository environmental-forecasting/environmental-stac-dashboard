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
  var currentViewExtent = null;
  var registeredProj4 = {};
  // Last search selection; rechecked when the TMS / projection changes.
  var lastPlaceGoto = null;
  // Extent to fit again once the map has a real size on screen.
  var pendingFitExtent = null;
  // Overlays added while size was 0 need a source refresh once layout runs.
  var overlaysAwaitingSize = false;
  var applyGeneration = 0;
  // Search result highlight (polygon / bbox / point).
  var placeHighlightLayer = null;
  var placeHighlightSource = null;

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
    currentViewExtent = view.extent || worldExtentFor(projectionCode);
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

  function isPolarProjection(code) {
    return !!(code && code !== "EPSG:3857");
  }

  function clearPlaceHighlight() {
    if (placeHighlightSource) {
      placeHighlightSource.clear();
    }
  }

  function ensurePlaceHighlightLayer() {
    if (!map) {
      return null;
    }
    if (placeHighlightLayer) {
      return placeHighlightSource;
    }
    placeHighlightSource = new ol.source.Vector();
    placeHighlightLayer = new ol.layer.Vector({
      source: placeHighlightSource,
      zIndex: 250,
      style: new ol.style.Style({
        stroke: new ol.style.Stroke({
          color: "rgba(91, 141, 239, 0.95)",
          width: 2.5,
        }),
        fill: new ol.style.Fill({
          color: "rgba(91, 141, 239, 0.16)",
        }),
        image: new ol.style.Circle({
          radius: 7,
          fill: new ol.style.Fill({ color: "rgba(91, 141, 239, 0.9)" }),
          stroke: new ol.style.Stroke({ color: "#fff", width: 2 }),
        }),
      }),
    });
    map.addLayer(placeHighlightLayer);
    return placeHighlightSource;
  }

  function geojsonIsPointOnly(geojson) {
    if (!geojson || !geojson.type) {
      return false;
    }
    if (geojson.type === "Point" || geojson.type === "MultiPoint") {
      return true;
    }
    if (geojson.type === "Feature") {
      return geojsonIsPointOnly(geojson.geometry);
    }
    if (geojson.type === "FeatureCollection") {
      var features = geojson.features || [];
      return (
        features.length > 0 &&
        features.every(function (feature) {
          return geojsonIsPointOnly(feature);
        })
      );
    }
    return false;
  }

  function showPlaceHighlight(opts, projectionCode) {
    var source = ensurePlaceHighlightLayer();
    if (!source) {
      return;
    }
    source.clear();
    var geojson = opts && opts.geojson;
    var bbox = opts && opts.bbox;
    var lon = opts && opts.lon;
    var lat = opts && opts.lat;
    try {
      // Prefer area geometry. Point geojson (common for Nominatim natural
      // features) is skipped when a bbox outline is available.
      var useGeojson =
        geojson &&
        !geojsonIsPointOnly(geojson) &&
        typeof ol.format !== "undefined" &&
        ol.format.GeoJSON;
      if (useGeojson) {
        var features = new ol.format.GeoJSON().readFeatures(geojson, {
          dataProjection: "EPSG:4326",
          featureProjection: projectionCode,
        });
        if (features && features.length) {
          source.addFeatures(features);
          return;
        }
      }
      if (bbox && bbox.length >= 4) {
        var ring = [
          [bbox[0], bbox[1]],
          [bbox[2], bbox[1]],
          [bbox[2], bbox[3]],
          [bbox[0], bbox[3]],
          [bbox[0], bbox[1]],
        ];
        var polygon = new ol.geom.Polygon([ring]).transform(
          "EPSG:4326",
          projectionCode
        );
        source.addFeature(new ol.Feature({ geometry: polygon }));
        return;
      }
      if (geojson && typeof ol.format !== "undefined" && ol.format.GeoJSON) {
        var pointFeatures = new ol.format.GeoJSON().readFeatures(geojson, {
          dataProjection: "EPSG:4326",
          featureProjection: projectionCode,
        });
        if (pointFeatures && pointFeatures.length) {
          source.addFeatures(pointFeatures);
          return;
        }
      }
      if (lon != null && lat != null) {
        source.addFeature(
          new ol.Feature({
            geometry: new ol.geom.Point(
              ol.proj.fromLonLat([Number(lon), Number(lat)], projectionCode)
            ),
          })
        );
      }
    } catch (err) {
      console.warn("ForecastMap: place highlight failed", err);
    }
  }

  function placeFitsCurrentView(lon, lat) {
    // Global views accept any lon/lat.
    if (!isPolarProjection(currentProjection)) {
      return true;
    }
    var latN = Number(lat);
    var lonN = Number(lon);
    if (!isFinite(latN) || !isFinite(lonN)) {
      return false;
    }
    // Match dashboard hemisphere rules for known polar TMS ids.
    var code = String(currentProjection || "");
    var epsg = (code.match(/(\d+)$/) || [])[1];
    if (epsg === "6931" && !(latN > 0)) {
      return false;
    }
    if (epsg === "6932" && !(latN < 0)) {
      return false;
    }
    var coord = ol.proj.fromLonLat([lonN, latN], currentProjection);
    if (!coord || !isFinite(coord[0]) || !isFinite(coord[1])) {
      return false;
    }
    var extent = currentViewExtent || worldExtentFor(currentProjection);
    if (!extent || extent.length < 4) {
      return true;
    }
    var padX = (extent[2] - extent[0]) * 0.02;
    var padY = (extent[3] - extent[1]) * 0.02;
    return ol.extent.containsXY(
      [extent[0] + padX, extent[1] + padY, extent[2] - padX, extent[3] - padY],
      coord[0],
      coord[1]
    );
  }

  /**
   * Animate center/zoom for place search and draw an outline highlight.
   */
  function flyToPlace(opts) {
    if (opts && opts.lon != null && opts.lat != null) {
      lastPlaceGoto = opts;
    }
    if (!opts || !ensureMap()) {
      return { ok: false, message: "Map is not ready" };
    }
    var view = map.getView();
    if (!view) {
      return { ok: false, message: "Map is not ready" };
    }
    var projectionCode = currentProjection || "EPSG:3857";
    var lon = Number(opts.lon);
    var lat = Number(opts.lat);
    var zoom = opts.zoom != null ? Number(opts.zoom) : 14;
    var bbox = opts.bbox;

    if (!placeFitsCurrentView(lon, lat)) {
      // Stay on the current TMS; do not zoom into empty / clamped space.
      clearPlaceHighlight();
      return { ok: false, message: "Outside this map's coverage" };
    }

    clearPendingFit();
    showPlaceHighlight(opts, projectionCode);

    var center = ol.proj.fromLonLat([lon, lat], projectionCode);
    if (!center) {
      return { ok: false, message: "Outside this map's coverage" };
    }

    if (bbox && bbox.length >= 4) {
      var extent = ol.proj.transformExtent(
        [bbox[0], bbox[1], bbox[2], bbox[3]],
        "EPSG:4326",
        projectionCode
      );
      if (extent && extent.every(isFinite)) {
        var size = map.getSize() || [0, 0];
        var pad = 56;
        var fitSize = [
          Math.max(size[0] - pad * 2, 1),
          Math.max(size[1] - pad * 2, 1),
        ];
        var resolution = view.getResolutionForExtent(extent, fitSize);
        var fittedZoom =
          resolution != null && isFinite(resolution)
            ? view.getZoomForResolution(resolution)
            : null;
        // Large outlines (Hudson Bay, seas) can fit far below the place zoom.
        // Keep the suggested/previous zoom at the centroid; still draw the outline.
        // Only for wide-area zooms (<=8); higher values are fit maxZoom caps.
        if (
          isFinite(zoom) &&
          zoom <= 8 &&
          fittedZoom != null &&
          isFinite(fittedZoom) &&
          fittedZoom < zoom - 0.05
        ) {
          view.animate({
            center: center,
            zoom: zoom,
            duration: 450,
          });
          return { ok: true };
        }
        view.fit(extent, {
          size: size,
          padding: [pad, pad, pad, pad],
          maxZoom: Math.max(zoom, 16),
          duration: 450,
        });
        return { ok: true };
      }
    }

    view.animate({
      center: center,
      zoom: isFinite(zoom) ? zoom : 14,
      duration: 450,
    });
    return { ok: true };
  }

  function clearLastPlace() {
    lastPlaceGoto = null;
    clearPlaceHighlight();
  }

  global.ForecastMapOpenLayers = {
    applyState: applyState,
    applyLeadtime: applyLeadtime,
    prefetchLayers: prefetchLayers,
    hasPendingSwap: hasPendingSwap,
    flyToPlace: flyToPlace,
    clearLastPlace: clearLastPlace,
  };
})(window);
