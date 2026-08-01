/** OpenLayers renderer for the forecast map host. */

(function (global) {
  "use strict";

  var HOST_ID = "forecast-map-ol";
  var forecastLayersById = {};
  var map = null;
  var basemapLayer = null;
  var currentProjection = null;
  var currentTileGrid = null;
  var registeredProj4 = {};
  // Extent to fit again once the map has a real size on screen.
  var pendingFitExtent = null;

  function getHost() {
    return document.getElementById(HOST_ID);
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

    map = new ol.Map({
      target: host,
      layers: [basemapLayer],
      view: createGlobalView({ center: [0, 0], zoom: 0 }),
    });
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
      // Allow zooming out until the full Mercator square is visible (tall
      // dashboard layouts otherwise clamp before the poles fit).
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
    if (!olView || !extent) {
      return;
    }
    var size = map.getSize();
    if (!size || !size[0] || !size[1]) {
      return;
    }
    olView.fit(extent, { size: size, padding: [20, 20, 20, 20] });
  }

  function setBasemap(basemap, showBasemap) {
    if (!basemapLayer) {
      return;
    }
    basemapLayer.setVisible(showBasemap !== false);
    if (!basemap || !basemap.url || showBasemap === false) {
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
    Object.keys(forecastLayersById).forEach(function (layerId) {
      var layer = forecastLayersById[layerId];
      var source = layer.getSource();
      var url = source.getUrls
        ? source.getUrls()[0]
        : source.getUrl && source.getUrl();
      if (url) {
        layer.setSource(createXyzSource(url, currentTileGrid));
      }
    });
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

      var source = existing.getSource();
      var currentUrl = source.getUrls
        ? source.getUrls()[0]
        : source.getUrl && source.getUrl();
      if (currentUrl !== layer.tileUrl) {
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
    if (visible) {
      host.classList.remove("forecast-map-host--hidden");
      if (map) {
        map.updateSize();
      }
      return;
    }
    host.classList.add("forecast-map-host--hidden");
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
    // Size must be known before we can frame the full world or polar view.
    map.updateSize();
    applyView(state.view);
    setBasemap(state.basemap, state.view && state.view.showBasemap);
    syncLayers(state.layers);
    map.updateSize();
    // The first fit may happen before the map is laid out; try once more.
    if (pendingFitExtent) {
      fitViewExtent(map.getView(), pendingFitExtent);
      pendingFitExtent = null;
    }
  }

  global.ForecastMapOpenLayers = {
    applyState: applyState,
  };
})(window);
