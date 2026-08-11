/** OpenLayers renderer for the forecast map host. */

(function (global) {
  "use strict";

  var HOST_ID = "forecast-map-ol";
  // Free Carto Voyager (OSM-derived); reprojected into polar/custom views.
  var DEFAULT_BASEMAP_URL =
    "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png";
  var DEFAULT_BASEMAP_ATTRIBUTION = "© OpenStreetMap contributors © CARTO";
  var forecastLayersById = {};
  // Leadtime / style swaps in flight: the incoming tiles paint above the
  // stable overlay so the previous step stays visible until they are ready.
  var pendingById = {};
  // One parked overlay per collection id (previous lead/style). Adjacent
  // step-back reuses it instead of refetching the same XYZ URL.
  var previousById = {};
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
  var tilesWaitCleanup = null;
  // Polar / custom EPSG: click rotates so geographic north is screen-up.
  var northUpClickEnabled = false;
  // Continuous lock: re-apply north-up at the view centre while panning.
  var northUpLockEnabled = false;
  var northUpFollowRaf = null;
  // Pause follow during place-search camera moves so setRotation cannot cancel
  // the in-flight center/zoom animation.
  var northUpFollowPaused = false;
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

  /** COG path from a TiTiler XYZ template (`?url=`). */
  function tileAssetKey(tileUrl) {
    if (!tileUrl || typeof tileUrl !== "string") {
      return "";
    }
    var match = /[?&]url=([^&]*)/.exec(tileUrl);
    if (!match) {
      return tileUrl;
    }
    try {
      return decodeURIComponent(match[1]);
    } catch (err) {
      return match[1];
    }
  }

  /** Colour / band query fingerprint; lead reuse must keep the same style. */
  function tileStyleKey(tileUrl) {
    if (!tileUrl || typeof tileUrl !== "string") {
      return "";
    }
    var cmap = (/[?&]colormap_name=([^&]*)/.exec(tileUrl) || [])[1] || "";
    var rescale = (/[?&]rescale=([^&]*)/.exec(tileUrl) || [])[1] || "";
    var bidx = (/[?&]bidx=([^&]*)/.exec(tileUrl) || [])[1] || "";
    return cmap + "\0" + rescale + "\0" + bidx;
  }

  /**
   * True when two XYZ templates paint the same COG with the same style.
   * Tolerates minor string differences (float formatting, key order) that
   * would otherwise force a soft-swap refetch.
   */
  function urlsMatchForReuse(a, b) {
    if (!a || !b) {
      return false;
    }
    if (a === b) {
      return true;
    }
    return (
      tileAssetKey(a) === tileAssetKey(b) && tileStyleKey(a) === tileStyleKey(b)
    );
  }

  function clearPrevious(layerId) {
    var prev = previousById[layerId];
    if (!prev) {
      return;
    }
    if (map && prev.layer) {
      map.removeLayer(prev.layer);
    }
    delete previousById[layerId];
  }

  function parkLayerAsPrevious(layerId, layer) {
    if (!layer) {
      return;
    }
    var prev = previousById[layerId];
    if (prev && prev.layer && prev.layer !== layer) {
      if (map) {
        map.removeLayer(prev.layer);
      }
    }
    // Hide completely so OpenLayers does not fetch tiles for the parked lead
    // while panning (opacity 0 alone still loads). The XYZ source keeps its
    // tile cache for an instant step-back promote.
    layer.setOpacity(0);
    layer.setVisible(false);
    layer.setZIndex(1);
    var url = layerSourceUrl(layer);
    previousById[layerId] = {
      layer: layer,
      url: url,
      assetKey: tileAssetKey(url),
      styleKey: tileStyleKey(url),
    };
  }

  function clearForecastOverlays() {
    Object.keys(pendingById).forEach(cancelPending);
    Object.keys(previousById).forEach(clearPrevious);
    Object.keys(forecastLayersById).forEach(function (layerId) {
      if (map) {
        map.removeLayer(forecastLayersById[layerId]);
      }
      delete forecastLayersById[layerId];
    });
  }

  function refreshOverlaySources() {
    Object.keys(pendingById).forEach(cancelPending);
    Object.keys(previousById).forEach(clearPrevious);
    Object.keys(forecastLayersById).forEach(function (layerId) {
      var layer = forecastLayersById[layerId];
      var url = layerSourceUrl(layer);
      if (url) {
        layer.setSource(
          createXyzSource(
            url,
            currentTileGrid,
            layer.get("forecastBbox"),
            layer.get("forecastGsd")
          )
        );
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
   * Instantly promote the parked previous overlay when it matches the target
   * lead (same COG + style). Returns true when no new XYZ fetch is needed.
   */
  function tryPromotePrevious(layerId, layerDesc, index) {
    var zIndex = 100 + index;
    var targetUrl = layerDesc.tileUrl;
    var targetOpacity = layerDesc.opacity == null ? 1 : layerDesc.opacity;
    var prev = previousById[layerId];
    if (!prev || !prev.layer || !urlsMatchForReuse(prev.url, targetUrl)) {
      return false;
    }
    cancelPending(layerId);
    var current = forecastLayersById[layerId];
    // Detach the parked overlay from the slot before demoting current (so
    // parkLayerAsPrevious does not destroy the layer we are promoting).
    delete previousById[layerId];
    if (current && current !== prev.layer) {
      parkLayerAsPrevious(layerId, current);
    }
    applyLayerExtent(prev.layer, layerDesc);
    prev.layer.setOpacity(targetOpacity);
    prev.layer.setVisible(layerDesc.visible !== false);
    prev.layer.setZIndex(zIndex);
    forecastLayersById[layerId] = prev.layer;
    return true;
  }

  /**
   * Stack a new XYZ source above the stable overlay and promote it once ready.
   *
   * The default is a progressive reveal: unloaded tiles are transparent so the
   * previous step shows through. For jumps (`holdUntilReady`) the incoming
   * layer stays invisible until its viewport tiles have loaded, then cuts over
   * in one go so the user never sees a patchwork of two steps.
   *
   * When the target URL is the parked previous lead, that overlay is promoted
   * instead of refetching (pair reuse: current + previous only).
   */
  function beginSmoothSwap(layerId, layerDesc, index, options) {
    var holdUntilReady = !!(options && options.holdUntilReady);
    var zIndex = 100 + index;
    var targetUrl = layerDesc.tileUrl;
    var targetOpacity = layerDesc.opacity == null ? 1 : layerDesc.opacity;
    var existingPending = pendingById[layerId];
    if (
      existingPending &&
      urlsMatchForReuse(layerSourceUrl(existingPending.layer), targetUrl)
    ) {
      existingPending.zIndex = zIndex;
      existingPending.holdUntilReady = holdUntilReady;
      if (!holdUntilReady) {
        existingPending.layer.setOpacity(targetOpacity);
      }
      existingPending.layer.setVisible(layerDesc.visible !== false);
      applyLayerExtent(existingPending.layer, layerDesc);
      return;
    }
    if (tryPromotePrevious(layerId, layerDesc, index)) {
      return;
    }
    cancelPending(layerId);

    var generation = (transitionGeneration += 1);
    var source = createXyzSource(
      targetUrl,
      currentTileGrid,
      layerDesc.bbox,
      layerDesc.gsd
    );
    var incoming = new ol.layer.Tile({
      source: source,
      opacity: holdUntilReady ? 0 : targetOpacity,
      visible: layerDesc.visible !== false,
      zIndex: zIndex + 50,
    });
    applyLayerExtent(incoming, layerDesc);

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
        parkLayerAsPrevious(layerId, old);
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

  function overlayMaxZoom(gsd, tileGrid) {
    if (!global.ForecastMap || !global.ForecastMap.maxZoomForGsd) {
      return null;
    }
    return global.ForecastMap.maxZoomForGsd(
      gsd,
      tileGrid && tileGrid.getResolutions && tileGrid.getResolutions()
    );
  }

  function overlayTileGrid(tileGrid, maxZoom) {
    if (!tileGrid || maxZoom == null || !isFinite(maxZoom)) {
      return tileGrid;
    }
    var resolutions =
      typeof tileGrid.getResolutions === "function"
        ? tileGrid.getResolutions()
        : null;
    if (!resolutions || maxZoom >= resolutions.length - 1) {
      return tileGrid;
    }
    return new ol.tilegrid.TileGrid({
      extent: tileGrid.getExtent(),
      origin: tileGrid.getOrigin(0),
      resolutions: resolutions.slice(0, maxZoom + 1),
      tileSize: tileGrid.getTileSize(0),
    });
  }

  function createXyzSource(url, tileGrid, bbox, gsd) {
    var wrapX = !tileGrid;
    var maxZoom = overlayMaxZoom(gsd, tileGrid);
    var options = {
      url: url,
      crossOrigin: "anonymous",
      // Retain decoded tile bitmaps in GPU/browser memory across leadtime scrub.
      cacheSize: 2048,
      // Global/WebMercator: wrap across ±180 so ice COGs can paint on both
      // sides of the date line. Custom polar tile grids stay unwrapped.
      wrapX: wrapX,
    };
    if (tileGrid) {
      options.tileGrid = overlayTileGrid(tileGrid, maxZoom);
      options.projection = currentProjection;
      options.wrapX = false;
    } else if (maxZoom != null && isFinite(maxZoom)) {
      options.maxZoom = maxZoom;
    }
    var source = new ol.source.XYZ(options);
    // Drop tiles outside the COG footprint (TiTiler outside-bounds 404s).
    // Near-global footprints skip setExtent so wrap still works; filter here.
    // Custom polar TMS: do not filter. Full-lon STAC bboxes (e.g. IceNet
    // [-180, ~17, 180, 90]) collapse under transformExtent in EPSG:6931/6932
    // (±180 and the pole map to a line), which wrongly skips most tiles.
    if (tileGrid) {
      return source;
    }
    var extent = layerExtentFromBbox(bbox, { allowWorldWide: true });
    if (!extent) {
      return source;
    }
    var grid = source.getTileGrid();
    var worldW = wrapX
      ? ol.extent.getWidth(ol.proj.get("EPSG:3857").getExtent())
      : 0;
    var base = source.getTileUrlFunction();
    source.setTileUrlFunction(function (coord, pixelRatio, projection) {
      if (coord && grid) {
        var te = grid.getTileCoordExtent(coord);
        var hit = false;
        var s;
        for (s = -1; s <= 1; s += 1) {
          if (
            ol.extent.intersects(te, [
              extent[0] + s * worldW,
              extent[1],
              extent[2] + s * worldW,
              extent[3],
            ])
          ) {
            hit = true;
            break;
          }
        }
        if (!hit) {
          return undefined;
        }
      }
      return base.call(this, coord, pixelRatio, projection);
    });
    return source;
  }

  /** WGS84 bbox to map extent. Near-global lon is null unless allowWorldWide. */
  function layerExtentFromBbox(bbox, options) {
    if (!bbox || bbox.length < 4 || typeof ol === "undefined" || !ol.proj) {
      return undefined;
    }
    var allowWorldWide = !!(options && options.allowWorldWide);
    var west = Number(bbox[0]);
    var south = Number(bbox[1]);
    var east = Number(bbox[2]);
    var north = Number(bbox[3]);
    if (
      !isFinite(west) ||
      !isFinite(south) ||
      !isFinite(east) ||
      !isFinite(north) ||
      west >= east ||
      south >= north
    ) {
      return undefined;
    }
    // Full-lon polar footprints: setExtent as wide as the world kills wrapX.
    if (!allowWorldWide && east - west >= 350) {
      return undefined;
    }
    var target = currentProjection || "EPSG:3857";
    try {
      var extent = ol.proj.transformExtent(
        [west, south, east, north],
        "EPSG:4326",
        target
      );
      if (!extent || extent.length < 4 || !extent.every(isFinite)) {
        return undefined;
      }
      if (!allowWorldWide) {
        var world = worldExtentFor(target);
        if (world && world[2] > world[0]) {
          if ((extent[2] - extent[0]) / (world[2] - world[0]) > 0.85) {
            return undefined;
          }
        }
      }
      return extent;
    } catch (err) {
      // Unknown projection / transform failure - leave uncapped.
    }
    return undefined;
  }

  function applyLayerExtent(tileLayer, layerDesc) {
    if (!tileLayer || typeof tileLayer.setExtent !== "function") {
      return;
    }
    tileLayer.set("forecastBbox", (layerDesc && layerDesc.bbox) || null);
    tileLayer.set("forecastGsd", layerDesc && layerDesc.gsd);
    tileLayer.setExtent(
      layerExtentFromBbox(layerDesc && layerDesc.bbox) || undefined
    );
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
        url: DEFAULT_BASEMAP_URL,
        projection: "EPSG:3857",
        crossOrigin: "anonymous",
        cacheSize: 2048,
        attributions: DEFAULT_BASEMAP_ATTRIBUTION,
      }),
      zIndex: 0,
    });
    basemapUrl = DEFAULT_BASEMAP_URL;

    map = new ol.Map({
      target: host,
      layers: [basemapLayer],
      view: createGlobalView({ center: [0, 0], zoom: 0 }),
    });
    // User navigation cancels any deferred world-fit so leadtime / resize
    // cannot yank the camera back out to the default extent.
    map.on("pointerdrag", clearPendingFit);
    map.on("singleclick", onNorthUpClick);
    // Keep the hidden Leaflet Global camera aligned while the user pans/zooms.
    map.on("moveend", function () {
      if (
        global.ForecastMap &&
        typeof global.ForecastMap.syncLeafletCameraFromOpenLayers === "function"
      ) {
        global.ForecastMap.syncLeafletCameraFromOpenLayers();
      }
    });
    attachNorthUpViewListeners(map.getView());
    syncRotateInteractions();
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
      // Full-viewport extent + non-zero rotation shrinks the allowed centre
      // so polar corners become unreachable after North up. Constrain centre
      // only so those corners can still be panned on-screen.
      if (projectionCode !== "EPSG:3857") {
        options.constrainOnlyCenter = true;
      }
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
    // on every leadtime tick reloads the basemap and makes it flicker.
    if (basemap.url === basemapUrl) {
      return;
    }
    // XYZ basemap is EPSG:3857; OL reprojects into polar/custom views.
    basemapLayer.setSource(
      new ol.source.XYZ({
        url: basemap.url,
        projection: "EPSG:3857",
        crossOrigin: "anonymous",
        cacheSize: 2048,
        attributions:
          basemap.attribution || DEFAULT_BASEMAP_ATTRIBUTION,
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
    // Always assign (including null) so polar to Global clears the custom grid.
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
          // See createGlobalView: rotated viewport + full extent constraint
          // otherwise blocks panning to polar map corners.
          constrainOnlyCenter: true,
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

    attachNorthUpViewListeners(nextView);
    // Rebuild overlay sources so polar tiles use the matching tile grid.
    refreshOverlaySources();
    syncNorthUpCursor();
    syncPolarRotateControl();
    syncRotateInteractions();
    if (northUpLockEnabled && isPolarProjection(currentProjection)) {
      applyNorthUpAtCenter(false);
    } else if (northUpLockEnabled) {
      setNorthUpLockEnabled(false);
    }
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
        clearPrevious(layer.id);
        tileLayer = new ol.layer.Tile({
          source: createXyzSource(
            layer.tileUrl,
            currentTileGrid,
            layer.bbox,
            layer.gsd
          ),
          opacity: layer.opacity == null ? 1 : layer.opacity,
          visible: layer.visible !== false,
          zIndex: 100 + i,
        });
        applyLayerExtent(tileLayer, layer);
        map.addLayer(tileLayer);
        forecastLayersById[layer.id] = tileLayer;
        continue;
      }

      if (!urlsMatchForReuse(layerSourceUrl(existing), layer.tileUrl)) {
        if (smooth) {
          beginSmoothSwap(layer.id, layer, i, {
            holdUntilReady: holdUntilReady,
          });
          continue;
        }
        cancelPending(layer.id);
        clearPrevious(layer.id);
        existing.setSource(
          createXyzSource(
            layer.tileUrl,
            currentTileGrid,
            layer.bbox,
            layer.gsd
          )
        );
      } else {
        // The stable layer already shows this COG/style; drop any stale swap.
        cancelPending(layer.id);
      }
      existing.setOpacity(layer.opacity == null ? 1 : layer.opacity);
      existing.setVisible(layer.visible !== false);
      existing.setZIndex(100 + i);
      applyLayerExtent(existing, layer);
    }

    Object.keys(forecastLayersById).forEach(function (layerId) {
      if (nextIds[layerId]) {
        return;
      }
      cancelPending(layerId);
      clearPrevious(layerId);
      map.removeLayer(forecastLayersById[layerId]);
      delete forecastLayersById[layerId];
    });
    Object.keys(pendingById).forEach(function (layerId) {
      if (!nextIds[layerId]) {
        cancelPending(layerId);
      }
    });
    Object.keys(previousById).forEach(function (layerId) {
      if (!nextIds[layerId]) {
        clearPrevious(layerId);
      }
    });
  }

  /**
   * Warm tile URLs for the current viewport so the next step paints sooner.
   * Cap budget and clamp to each layer bbox so polar COGs do not 404-flood.
   */
  function prefetchLayers(layers, options) {
    if (!map || !layers || !layers.length || !mapHasSize()) {
      return;
    }
    if (
      !global.ForecastMap ||
      typeof global.ForecastMap.prefetchTileImages !== "function"
    ) {
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
    var viewExtent;
    try {
      viewExtent = view.calculateExtent(map.getSize());
    } catch (err) {
      return;
    }
    if (!viewExtent) {
      return;
    }
    var maxTiles =
      options && options.maxTiles != null ? Number(options.maxTiles) : 8;
    if (isNaN(maxTiles) || maxTiles < 1) {
      maxTiles = 8;
    }
    var remaining = maxTiles;
    var i;
    for (i = 0; i < layers.length && remaining > 0; i += 1) {
      var layer = layers[i];
      if (!layer || !layer.tileUrl) {
        continue;
      }
      var warmExtent = viewExtent;
      var layerExtent = layerExtentFromBbox(layer.bbox, { allowWorldWide: true });
      if (layerExtent) {
        warmExtent = ol.extent.getIntersection(viewExtent, layerExtent);
        if (!warmExtent || ol.extent.isEmpty(warmExtent)) {
          continue;
        }
      }
      var range;
      var layerZ = z;
      var layerMax = overlayMaxZoom(layer.gsd, tileGrid);
      if (layerMax != null && layerZ > layerMax) {
        layerZ = layerMax;
      }
      try {
        range = tileGrid.getTileRangeForExtentAndZ(warmExtent, layerZ);
      } catch (err) {
        continue;
      }
      if (!range) {
        continue;
      }
      var budget = remaining;
      global.ForecastMap.prefetchTileImages([layer], {
        z: layerZ,
        minX: range.minX,
        maxX: range.maxX,
        minY: range.minY,
        maxY: range.maxY,
        maxTiles: budget,
      });
      // Approximate spend: rows*cols capped by budget.
      var cols = Math.max(0, range.maxX - range.minX + 1);
      var rows = Math.max(0, range.maxY - range.minY + 1);
      remaining -= Math.min(budget, cols * rows);
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
    if (tilesWaitCleanup) {
      tilesWaitCleanup();
    }
    if (!map) {
      markTilesReady(generation);
      return;
    }
    // Ignore rendercomplete until a forecast tile event has fired, so an
    // idle frame before XYZ requests start cannot clear the banner.
    var saw = false;
    var attached = [];
    var cachedTimer = null;
    var safetyTimer = null;

    function onTile() {
      saw = true;
    }

    function attach(source) {
      if (!source || attached.indexOf(source) >= 0) {
        return;
      }
      attached.push(source);
      source.on("tileloadstart", onTile);
      source.on("tileloadend", onTile);
      source.on("tileloaderror", onTile);
    }

    Object.keys(forecastLayersById).forEach(function (id) {
      var layer = forecastLayersById[id];
      attach(layer && layer.getSource && layer.getSource());
    });
    Object.keys(pendingById).forEach(function (id) {
      attach(pendingById[id] && pendingById[id].source);
    });

    function cleanup() {
      attached.forEach(function (source) {
        source.un("tileloadstart", onTile);
        source.un("tileloadend", onTile);
        source.un("tileloaderror", onTile);
      });
      if (map) {
        map.un("rendercomplete", onRender);
      }
      if (cachedTimer) {
        clearTimeout(cachedTimer);
      }
      if (safetyTimer) {
        clearTimeout(safetyTimer);
      }
      tilesWaitCleanup = null;
    }

    function finish() {
      if (generation !== applyGeneration) {
        cleanup();
        return;
      }
      cleanup();
      markTilesReady(generation);
    }

    function onRender() {
      if (saw) {
        finish();
      }
    }

    tilesWaitCleanup = cleanup;
    map.on("rendercomplete", onRender);
    map.render();
    cachedTimer = setTimeout(function () {
      if (!saw) {
        finish();
      }
    }, 800);
    safetyTimer = setTimeout(finish, 30000);
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
      if (state.layers && state.layers.length) {
        waitForTiles(generation);
      } else {
        markTilesReady(generation);
      }
      return;
    }
    // Drop the previous TMS immediately. Holding Web Mercator tiles on a
    // polar grid (or the reverse) leaves a remnant overlay in the wrong CRS.
    clearForecastOverlays();
    applyView(state.view);
    setBasemap(state.basemap, state.view && state.view.showBasemap);
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

  function syncNorthUpCursor() {
    var host = getHost();
    if (!host) {
      return;
    }
    if (northUpClickEnabled && isPolarProjection(currentProjection)) {
      host.classList.add("is-north-up-pick");
    } else {
      host.classList.remove("is-north-up-pick");
    }
  }

  function syncRotateInteractions() {
    if (!map) {
      return;
    }
    var allowRotate = !northUpLockEnabled;
    map.getInteractions().forEach(function (interaction) {
      if (
        interaction instanceof ol.interaction.DragRotate ||
        interaction instanceof ol.interaction.PinchRotate
      ) {
        interaction.setActive(allowRotate);
      }
    });
  }

  /**
   * OpenLayers view rotation that makes geographic north point up at ``coord``.
   *
   * Rotation 0 keeps projection +Y screen-up. ``atan2(dx, dy)`` is the
   * clockwise angle from +Y to the map-space north vector; OL rotation is
   * also clockwise, but the view transform needs the opposite sign to bring
   * that vector to screen-up.
   */
  function rotationForNorthUp(coordinate, projectionCode) {
    var lonLat = ol.proj.toLonLat(coordinate, projectionCode);
    if (!lonLat || lonLat.length < 2) {
      return 0;
    }
    var lon = lonLat[0];
    var lat = lonLat[1];
    // Geographic north is undefined at the poles.
    if (!isFinite(lat) || Math.abs(lat) > 89.5) {
      return map && map.getView() ? map.getView().getRotation() : 0;
    }
    var northLat = Math.max(-90, Math.min(90, lat + 0.05));
    var northMap = ol.proj.fromLonLat([lon, northLat], projectionCode);
    if (!northMap) {
      return 0;
    }
    var dx = northMap[0] - coordinate[0];
    var dy = northMap[1] - coordinate[1];
    if (!dx && !dy) {
      return 0;
    }
    return -Math.atan2(dx, dy);
  }

  function applyNorthUpAtCenter(animate) {
    if (
      !map ||
      !northUpLockEnabled ||
      northUpFollowPaused ||
      !isPolarProjection(currentProjection)
    ) {
      return;
    }
    var view = map.getView();
    if (!view) {
      return;
    }
    var center = view.getCenter();
    if (!center) {
      return;
    }
    var rotation = rotationForNorthUp(center, currentProjection);
    // Skip no-op writes: setRotation mid-zoom forces extra tile work.
    if (Math.abs(view.getRotation() - rotation) < 1e-4) {
      return;
    }
    if (animate) {
      view.animate({
        rotation: rotation,
        duration: 280,
      });
    } else {
      view.setRotation(rotation);
    }
  }

  function scheduleNorthUpFollow() {
    if (
      !northUpLockEnabled ||
      northUpFollowPaused ||
      northUpFollowRaf != null
    ) {
      return;
    }
    northUpFollowRaf = global.requestAnimationFrame(function () {
      northUpFollowRaf = null;
      applyNorthUpAtCenter(false);
    });
  }

  function attachNorthUpViewListeners(view) {
    if (!view || view.__forecastNorthUpBound) {
      return;
    }
    view.__forecastNorthUpBound = true;
    // Geographic north depends on map centre, not zoom. Listening to
    // change:resolution called setRotation every wheel frame and made zoom
    // feel stuck while tiles re-projected.
    view.on("change:center", scheduleNorthUpFollow);
  }

  function syncPolarRotateControl() {
    var host = getHost();
    if (!host) {
      return;
    }
    // Stock OL rotate arrow tracks projection +Y / view rotation reset, not
    // geographic north. Hide it in polar modes where North up controls own that.
    if (isPolarProjection(currentProjection)) {
      host.classList.add("is-polar-projection");
    } else {
      host.classList.remove("is-polar-projection");
    }
  }

  function setNorthUpClickEnabled(enabled) {
    northUpClickEnabled = !!enabled;
    if (northUpClickEnabled && northUpLockEnabled) {
      setNorthUpLockEnabled(false);
    }
    syncNorthUpCursor();
  }

  function setNorthUpLockEnabled(enabled) {
    var wasLocked = northUpLockEnabled;
    northUpLockEnabled = !!enabled;
    if (northUpLockEnabled) {
      northUpClickEnabled = false;
      syncNorthUpCursor();
      if (map) {
        clearPendingFit();
        attachNorthUpViewListeners(map.getView());
        applyNorthUpAtCenter(true);
      }
    } else {
      northUpFollowPaused = false;
      if (northUpFollowRaf != null) {
        global.cancelAnimationFrame(northUpFollowRaf);
        northUpFollowRaf = null;
      }
      // Turning Keep N up off restores the default projection orientation.
      if (wasLocked) {
        animateDefaultOrientation();
      }
    }
    syncRotateInteractions();
  }

  /** Animate view rotation back to projection +Y up (does not clear modes). */
  function animateDefaultOrientation() {
    if (!map) {
      return;
    }
    clearPendingFit();
    var view = map.getView();
    if (!view) {
      return;
    }
    if (Math.abs(view.getRotation()) < 1e-4) {
      return;
    }
    view.animate({
      rotation: 0,
      duration: 280,
    });
  }

  function isOrientationRotated() {
    if (!map) {
      return false;
    }
    var view = map.getView();
    return !!(view && Math.abs(view.getRotation()) >= 1e-4);
  }

  /** Clear north-up follow and animate rotation back to projection +Y up. */
  function resetOrientation() {
    if (northUpFollowRaf != null) {
      global.cancelAnimationFrame(northUpFollowRaf);
      northUpFollowRaf = null;
    }
    northUpLockEnabled = false;
    northUpFollowPaused = false;
    northUpClickEnabled = false;
    syncNorthUpCursor();
    syncRotateInteractions();
    animateDefaultOrientation();
  }

  /**
   * Fit the default extent for the active TMS / projection (world or polar
   * grid), with rotation cleared. Used when re-clicking the active view mode.
   */
  function resetView() {
    if (northUpFollowRaf != null) {
      global.cancelAnimationFrame(northUpFollowRaf);
      northUpFollowRaf = null;
    }
    northUpLockEnabled = false;
    northUpFollowPaused = false;
    northUpClickEnabled = false;
    syncNorthUpCursor();
    syncRotateInteractions();
    if (!ensureMap()) {
      return;
    }
    clearPendingFit();
    var view = map.getView();
    if (!view) {
      return;
    }
    var projectionCode =
      (view.getProjection() && view.getProjection().getCode()) ||
      currentProjection ||
      "EPSG:3857";
    var extent = currentViewExtent || worldExtentFor(projectionCode);
    view.setRotation(0);
    if (extent) {
      fitViewExtent(view, extent);
    } else {
      view.setCenter(ol.proj.fromLonLat([0, 0], projectionCode));
      view.setZoom(0);
    }
    if (
      global.ForecastMap &&
      typeof global.ForecastMap.syncLeafletCameraFromOpenLayers === "function"
    ) {
      global.ForecastMap.syncLeafletCameraFromOpenLayers();
    }
  }

  function resumeNorthUpFollow() {
    northUpFollowPaused = false;
    if (northUpLockEnabled) {
      applyNorthUpAtCenter(false);
    }
  }

  /**
   * Animate center/zoom for place search. With Keep N up, include the
   * destination rotation in the same animation and pause follow so mid-flight
   * setRotation cannot cancel the move.
   */
  function animatePlaceCamera(view, props) {
    var duration = props.duration != null ? props.duration : 450;
    if (
      northUpLockEnabled &&
      isPolarProjection(currentProjection) &&
      props.center
    ) {
      northUpFollowPaused = true;
      view.animate(
        Object.assign({}, props, {
          duration: duration,
          rotation: rotationForNorthUp(props.center, currentProjection),
        }),
        resumeNorthUpFollow
      );
      return;
    }
    view.animate(props);
  }

  function onNorthUpClick(evt) {
    if (!northUpClickEnabled || !map) {
      return;
    }
    if (!isPolarProjection(currentProjection)) {
      return;
    }
    clearPendingFit();
    var view = map.getView();
    if (!view) {
      return;
    }
    var rotation = rotationForNorthUp(evt.coordinate, currentProjection);
    view.animate({
      rotation: rotation,
      duration: 280,
    });
    // One-shot: leave pick mode after applying so the button is not sticky.
    if (
      global.ForecastMap &&
      typeof global.ForecastMap.clearNorthUpPickMode === "function"
    ) {
      global.ForecastMap.clearNorthUpPickMode();
    }
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
          animatePlaceCamera(view, {
            center: center,
            zoom: zoom,
            duration: 450,
          });
          return { ok: true };
        }
        if (northUpLockEnabled && isPolarProjection(currentProjection)) {
          northUpFollowPaused = true;
          view.fit(extent, {
            size: size,
            padding: [pad, pad, pad, pad],
            maxZoom: Math.max(zoom, 16),
            duration: 450,
            callback: resumeNorthUpFollow,
          });
        } else {
          view.fit(extent, {
            size: size,
            padding: [pad, pad, pad, pad],
            maxZoom: Math.max(zoom, 16),
            duration: 450,
          });
        }
        return { ok: true };
      }
    }

    animatePlaceCamera(view, {
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

  function getCameraLonLat() {
    if (!map) {
      return null;
    }
    var view = map.getView();
    if (!view) {
      return null;
    }
    var center = view.getCenter();
    var zoom = view.getZoom();
    if (!center || zoom == null || !isFinite(zoom)) {
      return null;
    }
    var projection = view.getProjection();
    var lonLat = ol.proj.toLonLat(center, projection);
    if (!lonLat || !isFinite(lonLat[0]) || !isFinite(lonLat[1])) {
      return null;
    }
    return {
      lon: lonLat[0],
      lat: lonLat[1],
      zoom: zoom,
      projection: projection && projection.getCode ? projection.getCode() : null,
    };
  }

  global.ForecastMapOpenLayers = {
    applyState: applyState,
    applyLeadtime: applyLeadtime,
    prefetchLayers: prefetchLayers,
    hasPendingSwap: hasPendingSwap,
    setBasemap: setBasemap,
    setNorthUpClickEnabled: setNorthUpClickEnabled,
    setNorthUpLockEnabled: setNorthUpLockEnabled,
    resetOrientation: resetOrientation,
    resetView: resetView,
    isOrientationRotated: isOrientationRotated,
    flyToPlace: flyToPlace,
    clearLastPlace: clearLastPlace,
    getCameraLonLat: getCameraLonLat,
  };
})(window);
