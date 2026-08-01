/** Cesium globe renderer for the forecast map host. */

(function (global) {
  "use strict";

  var HOST_ID = "forecast-map-globe";
  var OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  var forecastLayersById = {};
  var forecastUrlsById = {};
  var viewer = null;
  var basemapLayer = null;
  var basemapUrl = null;

  function getHost() {
    return document.getElementById(HOST_ID);
  }

  function osmImageryLayer(url) {
    return new Cesium.ImageryLayer(
      new Cesium.UrlTemplateImageryProvider({
        url: url || OSM_URL,
        credit: new Cesium.Credit("© OpenStreetMap contributors"),
      })
    );
  }

  function ensureViewer() {
    if (viewer) {
      return viewer;
    }
    if (typeof Cesium === "undefined") {
      console.error("ForecastMap: Cesium is not loaded");
      return null;
    }
    var host = getHost();
    if (!host) {
      return null;
    }

    // Not using Cesium ion
    Cesium.Ion.defaultAccessToken = undefined;
    Cesium.CreditDisplay.cesiumCredit = new Cesium.Credit("", false);

    viewer = new Cesium.Viewer(host, {
      animation: false,
      timeline: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      fullscreenButton: true,
      infoBox: false,
      selectionIndicator: false,
      // Default ellipsoid only
      baseLayer: osmImageryLayer(OSM_URL),
      // No star field / sun / moon
      skyBox: false,
    });

    basemapLayer = viewer.imageryLayers.get(0);
    basemapUrl = OSM_URL;
    viewer.scene.globe.enableLighting = false;
    viewer.scene.fog.enabled = false;
    if (viewer.scene.skyAtmosphere) {
      viewer.scene.skyAtmosphere.show = true;
    }

    // Start with a whole-Earth view.
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(0, 20, 18000000),
    });

    return viewer;
  }

  function setBasemap(basemap, showBasemap) {
    if (!viewer || !basemapLayer) {
      return;
    }
    basemapLayer.show = showBasemap !== false;
    if (!basemap || !basemap.url || showBasemap === false) {
      return;
    }
    // Avoid tearing down OSM on every map-state revision.
    if (basemap.url === basemapUrl) {
      return;
    }
    var index = viewer.imageryLayers.indexOf(basemapLayer);
    viewer.imageryLayers.remove(basemapLayer, false);
    basemapLayer = osmImageryLayer(basemap.url);
    basemapUrl = basemap.url;
    if (index >= 0) {
      viewer.imageryLayers.add(basemapLayer, index);
    } else {
      viewer.imageryLayers.add(basemapLayer, 0);
    }
  }

  function syncLayers(layers) {
    if (!viewer) {
      return;
    }
    var nextIds = {};
    var i;
    var layer;
    var existing;
    var imagery;

    layers = layers || [];
    for (i = 0; i < layers.length; i += 1) {
      layer = layers[i];
      if (!layer || !layer.id || !layer.tileUrl) {
        continue;
      }
      nextIds[layer.id] = true;
      existing = forecastLayersById[layer.id];
      if (!existing) {
        imagery = new Cesium.ImageryLayer(
          new Cesium.UrlTemplateImageryProvider({
            url: layer.tileUrl,
            credit: new Cesium.Credit(layer.title || layer.id),
          })
        );
        imagery.alpha = layer.opacity == null ? 1 : layer.opacity;
        imagery.show = layer.visible !== false;
        viewer.imageryLayers.add(imagery);
        forecastLayersById[layer.id] = imagery;
        forecastUrlsById[layer.id] = layer.tileUrl;
        continue;
      }

      if (forecastUrlsById[layer.id] !== layer.tileUrl) {
        var idx = viewer.imageryLayers.indexOf(existing);
        viewer.imageryLayers.remove(existing, false);
        imagery = new Cesium.ImageryLayer(
          new Cesium.UrlTemplateImageryProvider({
            url: layer.tileUrl,
            credit: new Cesium.Credit(layer.title || layer.id),
          })
        );
        imagery.alpha = layer.opacity == null ? 1 : layer.opacity;
        imagery.show = layer.visible !== false;
        if (idx >= 0) {
          viewer.imageryLayers.add(imagery, idx);
        } else {
          viewer.imageryLayers.add(imagery);
        }
        forecastLayersById[layer.id] = imagery;
        forecastUrlsById[layer.id] = layer.tileUrl;
        continue;
      }

      existing.alpha = layer.opacity == null ? 1 : layer.opacity;
      existing.show = layer.visible !== false;
    }

    Object.keys(forecastLayersById).forEach(function (layerId) {
      if (nextIds[layerId]) {
        return;
      }
      viewer.imageryLayers.remove(forecastLayersById[layerId], false);
      delete forecastLayersById[layerId];
      delete forecastUrlsById[layerId];
    });
  }

  function setHostVisible(visible) {
    var host = getHost();
    if (!host) {
      return;
    }
    if (visible) {
      host.classList.remove("forecast-map-host--hidden");
      if (viewer) {
        viewer.resize();
      }
      return;
    }
    host.classList.add("forecast-map-host--hidden");
  }

  function applyState(state) {
    if (!state || state.engine !== "cesium") {
      setHostVisible(false);
      return;
    }
    setHostVisible(true);
    if (!ensureViewer()) {
      return;
    }
    setBasemap(state.basemap, state.view && state.view.showBasemap);
    syncLayers(state.layers);
    viewer.resize();
  }

  global.ForecastMapCesium = {
    applyState: applyState,
  };
})(window);
