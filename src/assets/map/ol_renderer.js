/** OpenLayers renderer for the forecast map host. */

(function (global) {
  "use strict";

  var HOST_ID = "forecast-map-ol";
  var forecastLayersById = {};
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
    Object.keys(forecastLayersById).forEach(function (layerId) {
      var layer = forecastLayersById[layerId];
      var url = layerSourceUrl(layer);
      if (url) {
        layer.setSource(createXyzSource(url, currentTileGrid));
      }
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
      // Allow zooming out past one world so forecast overlays can repeat on X.
      multiWorld: view && view.multiWorld === false ? false : true,
      showFullExtent: view && view.showFullExtent === false ? false : true,
      minZoom: view && view.minZoom != null ? view.minZoom : 0,
    };
    var extent = (view && view.extent) || worldExtentFor(projectionCode);
    if (extent) {
      options.extent = extent;
    }
    return new ol.View(options);
  }

  function fitViewExtent(olView, extent) {
    if (!olView || !extent || !mapHasSize()) {
      return;
    }
    olView.fit(extent, { size: map.getSize(), padding: [20, 20, 20, 20] });
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
    if (!projectionChanged) {
      return;
    }

    currentProjection = projectionCode;
    currentTileGrid = tileGrid;
    pendingFitExtent = null;

    var nextView;
    var fitExtent = null;
    if (view.fit) {
      fitExtent = view.extent || worldExtentFor(projectionCode);
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

  function syncLayers(layers) {
    if (!map) {
      return;
    }
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
        existing.setSource(createXyzSource(layer.tileUrl, currentTileGrid));
      }
      existing.setOpacity(layer.opacity == null ? 1 : layer.opacity);
      existing.setVisible(layer.visible !== false);
      existing.setZIndex(100 + i);
    }

    Object.keys(forecastLayersById).forEach(function (layerId) {
      if (nextIds[layerId]) {
        return;
      }
      map.removeLayer(forecastLayersById[layerId]);
      delete forecastLayersById[layerId];
    });
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
      map.once("rendercomplete", function () {
        markTilesReady(generation);
      });
      map.render();
    });
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
    applyView(state.view);
    setBasemap(state.basemap, state.view && state.view.showBasemap);
    syncLayers(state.layers);
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
  };
})(window);
