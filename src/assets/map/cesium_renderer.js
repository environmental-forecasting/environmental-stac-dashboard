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
  // WebMercator meters/pixel at zoom 0 on the equator (EPSG:3857).
  var WEB_MERCATOR_MPP_Z0 = 156543.03392804097;
  var lastPlaceGoto = null;
  var placeHighlightSource = null;
  var placeOutlinePrimitives = [];

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

  /**
   * Camera height that approximately matches OpenLayers / Leaflet zoom.
   *
   * Uses equatorial WebMercator resolution, canvas height, and the active
   * vertical FOV so Globe framing tracks the 2D maps instead of overshooting.
   */
  function heightForZoom(zoom, latitude) {
    var z = Math.max(isFinite(zoom) ? Number(zoom) : 14, 0);
    var canvas = viewer && viewer.scene && viewer.scene.canvas;
    var heightPx =
      (canvas && (canvas.clientHeight || canvas.height)) || 720;
    var latRad = Cesium.Math.toRadians(isFinite(latitude) ? Number(latitude) : 0);
    var metersPerPixel =
      (WEB_MERCATOR_MPP_Z0 * Math.cos(latRad)) / Math.pow(2, z);
    var fovy = Math.PI / 3;
    if (
      viewer &&
      viewer.camera &&
      viewer.camera.frustum &&
      isFinite(viewer.camera.frustum.fovy)
    ) {
      fovy = viewer.camera.frustum.fovy;
    }
    var groundHeightM = metersPerPixel * heightPx;
    var height = (groundHeightM * 0.5) / Math.tan(fovy * 0.5);
    // Keep within the controller range used for this globe.
    return Math.min(
      Math.max(height, 5.0e2),
      FULL_GLOBE_HEIGHT_M * 1.5
    );
  }

  function paddedRectangleDegrees(west, south, east, north) {
    // Roughly match the 56px padding used by OL / Leaflet fitBounds.
    var padLon = Math.max((east - west) * 0.14, 0.01);
    var padLat = Math.max((north - south) * 0.14, 0.01);
    return Cesium.Rectangle.fromDegrees(
      Math.max(west - padLon, -180),
      Math.max(south - padLat, -90),
      Math.min(east + padLon, 180),
      Math.min(north + padLat, 90)
    );
  }

  function nadirOrientation() {
    return {
      heading: 0,
      pitch: Cesium.Math.toRadians(-90),
      roll: 0,
    };
  }

  function geojsonIsPointOnly(geojson) {
    if (!geojson || !geojson.type) {
      return true;
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
        !features.length ||
        features.every(function (feature) {
          return geojsonIsPointOnly(feature);
        })
      );
    }
    return false;
  }

  function ensurePlaceHighlight() {
    if (!viewer) {
      return null;
    }
    if (placeHighlightSource) {
      return placeHighlightSource;
    }
    placeHighlightSource = new Cesium.CustomDataSource("place-search-highlight");
    viewer.dataSources.add(placeHighlightSource);
    return placeHighlightSource;
  }

  function clearPlaceHighlight() {
    if (placeHighlightSource) {
      placeHighlightSource.entities.removeAll();
    }
    if (viewer && placeOutlinePrimitives.length) {
      for (var i = 0; i < placeOutlinePrimitives.length; i += 1) {
        viewer.scene.groundPrimitives.remove(placeOutlinePrimitives[i]);
      }
      placeOutlinePrimitives = [];
    }
  }

  // Match OpenLayers / Leaflet highlight styling.
  function strokeColor() {
    return Cesium.Color.fromCssColorString("#5b8def").withAlpha(0.95);
  }

  function fillColor() {
    return Cesium.Color.fromCssColorString("#5b8def").withAlpha(0.16);
  }

  /** Flatten a ring of [lon, lat] pairs for Cartesian3.fromDegreesArray. */
  function flatLonLat(ring) {
    var out = [];
    for (var i = 0; i < ring.length; i += 1) {
      var pt = ring[i];
      if (!pt || pt.length < 2) {
        continue;
      }
      out.push(Number(pt[0]), Number(pt[1]));
    }
    return out;
  }

  function closeRing(flat) {
    if (flat.length < 6) {
      return flat;
    }
    if (flat[0] !== flat[flat.length - 2] || flat[1] !== flat[flat.length - 1]) {
      return flat.concat([flat[0], flat[1]]);
    }
    return flat;
  }

  /**
   * Polygon parts from GeoJSON: each entry is ``{exterior, holes}`` as lon/lat rings.
   */
  function polygonsFromGeoJson(geojson) {
    var polygons = [];

    function addPolygonCoords(coords) {
      if (!coords || !coords.length) {
        return;
      }
      polygons.push({
        exterior: coords[0],
        holes: coords.slice(1),
      });
    }

    function fromGeometry(geometry) {
      if (!geometry || !geometry.type) {
        return;
      }
      if (geometry.type === "Polygon") {
        addPolygonCoords(geometry.coordinates);
      } else if (geometry.type === "MultiPolygon") {
        var polys = geometry.coordinates || [];
        for (var p = 0; p < polys.length; p += 1) {
          addPolygonCoords(polys[p]);
        }
      } else if (geometry.type === "GeometryCollection" && geometry.geometries) {
        for (var g = 0; g < geometry.geometries.length; g += 1) {
          fromGeometry(geometry.geometries[g]);
        }
      }
    }

    if (!geojson) {
      return polygons;
    }
    if (geojson.type === "Feature") {
      fromGeometry(geojson.geometry);
    } else if (geojson.type === "FeatureCollection") {
      var features = geojson.features || [];
      for (var f = 0; f < features.length; f += 1) {
        if (features[f]) {
          fromGeometry(features[f].geometry);
        }
      }
    } else {
      fromGeometry(geojson);
    }
    return polygons;
  }

  function addGroundOutline(source, flatDegrees) {
    var closed = closeRing(flatDegrees);
    if (closed.length < 6 || !viewer) {
      return;
    }
    var positions = Cesium.Cartesian3.fromDegreesArray(closed);
    // GroundPolylinePrimitive keeps a constant screen-pixel width (like OL/Leaflet
    // strokes). Entity clampToGround polylines look softer and foreshorten.
    if (
      typeof Cesium.GroundPolylineGeometry !== "undefined" &&
      typeof Cesium.GroundPolylinePrimitive !== "undefined"
    ) {
      var primitive = new Cesium.GroundPolylinePrimitive({
        geometryInstances: new Cesium.GeometryInstance({
          geometry: new Cesium.GroundPolylineGeometry({
            positions: positions,
            width: 2.5,
          }),
          attributes: {
            color: Cesium.ColorGeometryInstanceAttribute.fromColor(strokeColor()),
          },
        }),
        appearance: new Cesium.PolylineColorAppearance({ translucent: true }),
        asynchronous: true,
      });
      viewer.scene.groundPrimitives.add(primitive);
      placeOutlinePrimitives.push(primitive);
      return;
    }
    // Older Cesium fallback.
    source.entities.add({
      polyline: {
        positions: positions,
        width: 2.5,
        material: strokeColor(),
        clampToGround: true,
        arcType: Cesium.ArcType.GEODESIC,
      },
    });
  }

  function addGroundPolygon(source, exteriorFlat, holeFlats) {
    if (exteriorFlat.length < 6) {
      return;
    }
    var hierarchy = new Cesium.PolygonHierarchy(
      Cesium.Cartesian3.fromDegreesArray(exteriorFlat),
      (holeFlats || [])
        .filter(function (flat) {
          return flat && flat.length >= 6;
        })
        .map(function (flat) {
          return new Cesium.PolygonHierarchy(
            Cesium.Cartesian3.fromDegreesArray(flat)
          );
        })
    );
    source.entities.add({
      polygon: {
        hierarchy: hierarchy,
        material: fillColor(),
        outline: false,
        classificationType: Cesium.ClassificationType.BOTH,
        height: 0,
      },
    });
  }

  function showPlaceHighlight(opts) {
    var source = ensurePlaceHighlight();
    if (!source) {
      return;
    }
    clearPlaceHighlight();
    source = ensurePlaceHighlight();
    var geojson = opts && opts.geojson;
    var bbox = opts && opts.bbox;
    var lon = opts && opts.lon;
    var lat = opts && opts.lat;
    var stroke = strokeColor();

    function addPoint(lonDeg, latDeg) {
      source.entities.add({
        position: Cesium.Cartesian3.fromDegrees(Number(lonDeg), Number(latDeg)),
        point: {
          pixelSize: 11,
          color: stroke,
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    }

    if (geojson && !geojsonIsPointOnly(geojson)) {
      var polygons = polygonsFromGeoJson(geojson);
      if (polygons.length) {
        for (var i = 0; i < polygons.length; i += 1) {
          var part = polygons[i];
          var exterior = flatLonLat(part.exterior);
          var holes = (part.holes || []).map(flatLonLat);
          addGroundPolygon(source, exterior, holes);
          addGroundOutline(source, exterior);
          for (var h = 0; h < holes.length; h += 1) {
            addGroundOutline(source, holes[h]);
          }
        }
        return;
      }
    }

    if (bbox && bbox.length >= 4) {
      var west = Number(bbox[0]);
      var south = Number(bbox[1]);
      var east = Number(bbox[2]);
      var north = Number(bbox[3]);
      if ([west, south, east, north].every(isFinite) && east > west && north > south) {
        var box = [west, south, east, south, east, north, west, north, west, south];
        addGroundPolygon(source, [west, south, east, south, east, north, west, north]);
        addGroundOutline(source, box);
        return;
      }
    }

    if (lon != null && lat != null && isFinite(Number(lon)) && isFinite(Number(lat))) {
      addPoint(lon, lat);
    }
  }

  function flyToPlace(opts) {
    if (opts && opts.lon != null && opts.lat != null) {
      lastPlaceGoto = opts;
    }
    if (!opts || !ensureViewer()) {
      return { ok: false, message: "Map is not ready" };
    }
    var lon = Number(opts.lon);
    var lat = Number(opts.lat);
    var zoom = opts.zoom != null ? Number(opts.zoom) : 14;
    var bbox = opts.bbox;
    if (!isFinite(lon) || !isFinite(lat)) {
      return { ok: false, message: "Invalid location" };
    }

    showPlaceHighlight(opts);

    var duration = 0.45;
    var orientation = nadirOrientation();

    if (bbox && bbox.length >= 4) {
      var west = Number(bbox[0]);
      var south = Number(bbox[1]);
      var east = Number(bbox[2]);
      var north = Number(bbox[3]);
      if ([west, south, east, north].every(isFinite) && east > west && north > south) {
        var span = Math.max(east - west, north - south, 1e-6);
        var fittedZoom = Math.log2(360 / span);
        // Match OL: keep suggested zoom for wide-area places when fit is lower.
        if (isFinite(zoom) && zoom <= 8 && isFinite(fittedZoom) && fittedZoom < zoom - 0.05) {
          viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(
              lon,
              lat,
              heightForZoom(zoom, lat)
            ),
            orientation: orientation,
            duration: duration,
          });
          return { ok: true };
        }
        viewer.camera.flyTo({
          destination: paddedRectangleDegrees(west, south, east, north),
          duration: duration,
        });
        return { ok: true };
      }
    }

    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat, heightForZoom(zoom, lat)),
      orientation: orientation,
      duration: duration,
    });
    return { ok: true };
  }

  function clearLastPlace() {
    lastPlaceGoto = null;
    clearPlaceHighlight();
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
    // Allow place-search zoom-in while still framing the full globe when zoomed out.
    viewer.scene.screenSpaceCameraController.minimumZoomDistance = 5.0e2;
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
    resetView: showFullGlobe,
    flyToPlace: flyToPlace,
    clearLastPlace: clearLastPlace,
  };
})(window);
