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
  var applyGeneration = 0;
  var progressListener = null;
  // Height above ellipsoid that frames the whole Earth in a typical map pane.
  var FULL_GLOBE_HEIGHT_M = 2.4e7;

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

  /** Frame the whole Earth (equatorial, looking straight down). */
  function showFullGlobe() {
    if (!viewer) {
      return;
    }
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(0, 0, FULL_GLOBE_HEIGHT_M),
      orientation: {
        heading: 0,
        pitch: Cesium.Math.toRadians(-90),
        roll: 0,
      },
    });
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
      fullscreenButton: false,
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
    // Ground atmosphere washes OSM/forecast tiles out when zoomed out.
    viewer.scene.globe.showGroundAtmosphere = false;
    if (viewer.scene.skyAtmosphere) {
      viewer.scene.skyAtmosphere.show = true;
    }
    // Allow zooming out far enough to keep the whole globe in frame.
    viewer.scene.screenSpaceCameraController.minimumZoomDistance = 1.0e5;
    viewer.scene.screenSpaceCameraController.maximumZoomDistance =
      FULL_GLOBE_HEIGHT_M * 1.5;

    // Host is often still hidden (0×0) here; applyState re-frames after resize.
    showFullGlobe();

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
    var wasHidden = host.classList.contains("forecast-map-host--hidden");
    if (visible) {
      host.classList.remove("forecast-map-host--hidden");
      if (viewer) {
        viewer.resize();
        // Camera set while 0×0 is wrong; re-frame the whole globe on first show.
        if (wasHidden) {
          showFullGlobe();
        }
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
    if (!viewer) {
      markTilesReady(generation);
      return;
    }
    if (progressListener) {
      viewer.scene.globe.tileLoadProgressEvent.removeEventListener(progressListener);
      progressListener = null;
    }
    // Already idle (cached tiles / empty queue).
    if (viewer.scene.globe.tilesLoaded) {
      markTilesReady(generation);
      return;
    }
    progressListener = function (remaining) {
      if (generation !== applyGeneration) {
        return;
      }
      if (remaining > 0) {
        return;
      }
      if (progressListener) {
        viewer.scene.globe.tileLoadProgressEvent.removeEventListener(progressListener);
        progressListener = null;
      }
      markTilesReady(generation);
    };
    viewer.scene.globe.tileLoadProgressEvent.addEventListener(progressListener);
    viewer.scene.requestRender();
  }

  function applyState(state) {
    if (!state || state.engine !== "cesium") {
      setHostVisible(false);
      return;
    }
    var host = getHost();
    var wasHidden = !!(
      host && host.classList.contains("forecast-map-host--hidden")
    );
    setHostVisible(true);
    if (!ensureViewer()) {
      return;
    }
    var generation = (applyGeneration += 1);
    setBasemap(state.basemap, state.view && state.view.showBasemap);
    syncLayers(state.layers);
    viewer.resize();
    // ensureViewer may have run while the host was still hidden.
    if (wasHidden) {
      showFullGlobe();
    }
    if (state.layers && state.layers.length) {
      waitForTiles(generation);
    } else {
      markTilesReady(generation);
    }
  }

  global.ForecastMapCesium = {
    applyState: applyState,
  };
})(window);
