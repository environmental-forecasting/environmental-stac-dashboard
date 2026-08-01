/** OpenLayers renderer for the forecast map host. */

(function (global) {
  "use strict";

  var HOST_ID = "forecast-map-ol";
  var forecastLayersById = {};
  var map = null;
  var basemapLayer = null;

  function getHost() {
    return document.getElementById(HOST_ID);
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
      view: new ol.View({
        center: ol.proj.fromLonLat([0, 0]),
        zoom: 2,
      }),
    });
    return map;
  }

  function setBasemap(basemap) {
    if (!basemapLayer || !basemap || !basemap.url) {
      return;
    }
    basemapLayer.setSource(
      new ol.source.XYZ({
        url: basemap.url,
        attributions: "© OpenStreetMap contributors",
      })
    );
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
          source: new ol.source.XYZ({
            url: layer.tileUrl,
            crossOrigin: "anonymous",
          }),
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
        existing.setSource(
          new ol.source.XYZ({
            url: layer.tileUrl,
            crossOrigin: "anonymous",
          })
        );
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
    setBasemap(state.basemap);
    syncLayers(state.layers);
    map.updateSize();
  }

  global.ForecastMapOpenLayers = {
    applyState: applyState,
  };
})(window);
