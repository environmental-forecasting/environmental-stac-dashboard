/** Cesium globe renderer for the forecast map host. */

(function (global) {
  "use strict";

  var HOST_ID = "forecast-map-globe";
  // Free Carto Voyager (OSM-derived); kept in polar views via OL/Cesium.
  var DEFAULT_BASEMAP_URL =
    "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png";
  var DEFAULT_BASEMAP_CREDIT = "© OpenStreetMap contributors © CARTO";
  var forecastLayersById = {};
  var forecastUrlsById = {};
  // URL swaps stack a hidden/incoming layer above the stable one until ready.
  var pendingById = {};
  var transitionGeneration = 0;
  var viewer = null;
  var basemapLayer = null;
  var basemapUrl = null;
  var applyGeneration = 0;
  var progressListener = null;
  var tilesWaitCleanup = null;
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

  function basemapImageryLayer(url, credit) {
    return new Cesium.ImageryLayer(
      new Cesium.UrlTemplateImageryProvider({
        url: url || DEFAULT_BASEMAP_URL,
        credit: new Cesium.Credit(credit || DEFAULT_BASEMAP_CREDIT),
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
      baseLayer: basemapImageryLayer(DEFAULT_BASEMAP_URL),
      // No star field / sun / moon
      skyBox: false,
    });

    basemapLayer = viewer.imageryLayers.get(0);
    basemapUrl = DEFAULT_BASEMAP_URL;
    viewer.scene.globe.enableLighting = false;
    viewer.scene.fog.enabled = false;
    // Ground atmosphere washes basemap/forecast tiles out when zoomed out.
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
    // Avoid tearing down the basemap on every map-state revision.
    if (basemap.url === basemapUrl) {
      return;
    }
    var index = viewer.imageryLayers.indexOf(basemapLayer);
    viewer.imageryLayers.remove(basemapLayer, false);
    basemapLayer = basemapImageryLayer(
      basemap.url,
      basemap.attribution || DEFAULT_BASEMAP_CREDIT
    );
    basemapUrl = basemap.url;
    if (index >= 0) {
      viewer.imageryLayers.add(basemapLayer, index);
    } else {
      viewer.imageryLayers.add(basemapLayer, 0);
    }
  }

  function hasPendingSwap() {
    return Object.keys(pendingById).length > 0;
  }

  function cancelPending(layerId) {
    var pending = pendingById[layerId];
    if (!pending) {
      return;
    }
    if (pending.timeout) {
      clearTimeout(pending.timeout);
      pending.timeout = null;
    }
    if (pending.progressListener && viewer) {
      viewer.scene.globe.tileLoadProgressEvent.removeEventListener(
        pending.progressListener
      );
      pending.progressListener = null;
    }
    if (viewer && pending.imagery) {
      viewer.imageryLayers.remove(pending.imagery, false);
    }
    delete pendingById[layerId];
  }

  function makeForecastImagery(layerDesc, alpha) {
    var imagery = new Cesium.ImageryLayer(
      new Cesium.UrlTemplateImageryProvider({
        url: layerDesc.tileUrl,
        credit: new Cesium.Credit(layerDesc.title || layerDesc.id),
      })
    );
    imagery.alpha = alpha;
    imagery.show = layerDesc.visible !== false;
    return imagery;
  }

  /**
   * Stack a new imagery layer above the stable overlay and promote it once
   * the globe tile queue is idle. The old forecast stays painted so the user
   * never sees a bare basemap flash between leadtimes.
   *
   * For jumps (`holdUntilReady`) the incoming layer stays at alpha 0 until
   * ready, then cuts over in one go.
   */
  function beginSmoothSwap(layerId, layerDesc, options) {
    var holdUntilReady = !!(options && options.holdUntilReady);
    var waitForPaint = !!(options && options.waitForPaint);
    var targetUrl = layerDesc.tileUrl;
    var targetOpacity = layerDesc.opacity == null ? 1 : layerDesc.opacity;
    var existingPending = pendingById[layerId];
    if (existingPending && existingPending.url === targetUrl) {
      existingPending.holdUntilReady = holdUntilReady;
      existingPending.targetOpacity = targetOpacity;
      if (!holdUntilReady) {
        existingPending.imagery.alpha = targetOpacity;
      }
      existingPending.imagery.show = layerDesc.visible !== false;
      return;
    }
    cancelPending(layerId);

    var old = forecastLayersById[layerId];
    var idx = old ? viewer.imageryLayers.indexOf(old) : -1;
    var generation = (transitionGeneration += 1);
    var imagery = makeForecastImagery(
      layerDesc,
      holdUntilReady ? 0 : targetOpacity
    );
    // Keep the stable overlay underneath until finish() removes it.
    if (idx >= 0) {
      viewer.imageryLayers.add(imagery, idx + 1);
    } else {
      viewer.imageryLayers.add(imagery);
    }

    var entry = {
      imagery: imagery,
      url: targetUrl,
      generation: generation,
      holdUntilReady: holdUntilReady,
      targetOpacity: targetOpacity,
      timeout: null,
      progressListener: null,
    };
    pendingById[layerId] = entry;
    // Match the target early so a Python confirm for the same URL is a no-op.
    forecastUrlsById[layerId] = targetUrl;

    var finished = false;
    var sawLoading = false;

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
      if (entry.progressListener) {
        viewer.scene.globe.tileLoadProgressEvent.removeEventListener(
          entry.progressListener
        );
        entry.progressListener = null;
      }
      imagery.alpha = entry.targetOpacity;
      imagery.show = layerDesc.visible !== false;
      if (old && old !== imagery) {
        viewer.imageryLayers.remove(old, false);
      }
      forecastLayersById[layerId] = imagery;
      forecastUrlsById[layerId] = targetUrl;
      delete pendingById[layerId];
      viewer.scene.requestRender();
    }

    entry.progressListener = function (remaining) {
      if (!pendingById[layerId] || pendingById[layerId].generation !== generation) {
        return;
      }
      if (remaining > 0) {
        sawLoading = true;
        return;
      }
      if (sawLoading) {
        finish();
      }
    };
    viewer.scene.globe.tileLoadProgressEvent.addEventListener(
      entry.progressListener
    );
    viewer.scene.requestRender();

    // Play: cached frames may never bump the globe load counter.
    // Scrub/rebuilds wait for a real load so the banner stays until
    // forecast imagery has painted, not just terrain.
    if (!holdUntilReady && !waitForPaint) {
      requestAnimationFrame(function () {
        if (!pendingById[layerId] || pendingById[layerId].generation !== generation) {
          return;
        }
        requestAnimationFrame(function () {
          if (
            !pendingById[layerId] ||
            pendingById[layerId].generation !== generation
          ) {
            return;
          }
          if (viewer.scene.globe.tilesLoaded && !sawLoading) {
            finish();
          }
        });
      });
    }
    entry.timeout = setTimeout(finish, holdUntilReady ? 2000 : 1500);
  }

  /**
   * @param {Array} layers
   * @param {{smooth?: boolean, holdUntilReady?: boolean}} [options]
   */
  function syncLayers(layers, options) {
    if (!viewer) {
      return;
    }
    var smooth = !!(options && options.smooth);
    var holdUntilReady = !!(options && options.holdUntilReady);
    var waitForPaint = !!(options && options.waitForPaint);
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
        cancelPending(layer.id);
        imagery = makeForecastImagery(
          layer,
          layer.opacity == null ? 1 : layer.opacity
        );
        viewer.imageryLayers.add(imagery);
        forecastLayersById[layer.id] = imagery;
        forecastUrlsById[layer.id] = layer.tileUrl;
        continue;
      }

      if (forecastUrlsById[layer.id] !== layer.tileUrl) {
        if (smooth) {
          beginSmoothSwap(layer.id, layer, {
            holdUntilReady: holdUntilReady,
            waitForPaint: waitForPaint,
          });
          continue;
        }
        cancelPending(layer.id);
        var idx = viewer.imageryLayers.indexOf(existing);
        viewer.imageryLayers.remove(existing, false);
        imagery = makeForecastImagery(
          layer,
          layer.opacity == null ? 1 : layer.opacity
        );
        if (idx >= 0) {
          viewer.imageryLayers.add(imagery, idx);
        } else {
          viewer.imageryLayers.add(imagery);
        }
        forecastLayersById[layer.id] = imagery;
        forecastUrlsById[layer.id] = layer.tileUrl;
        continue;
      }

      // Already on this URL (stable or still fading in).
      if (pendingById[layer.id]) {
        pendingById[layer.id].targetOpacity =
          layer.opacity == null ? 1 : layer.opacity;
        if (!pendingById[layer.id].holdUntilReady) {
          pendingById[layer.id].imagery.alpha =
            pendingById[layer.id].targetOpacity;
        }
        pendingById[layer.id].imagery.show = layer.visible !== false;
        continue;
      }
      existing.alpha = layer.opacity == null ? 1 : layer.opacity;
      existing.show = layer.visible !== false;
    }

    Object.keys(forecastLayersById).forEach(function (layerId) {
      if (nextIds[layerId]) {
        return;
      }
      cancelPending(layerId);
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
    if (tilesWaitCleanup) {
      tilesWaitCleanup();
    }
    if (!viewer) {
      markTilesReady(generation);
      return;
    }
    // Ignore terrain idle from the previous frame. After a short warmup,
    // wait until the queue has gone busy and then quiet again.
    var remainingNow = 0;
    var watching = false;
    var saw = false;
    var idleTimer = null;
    var warmupTimer = null;
    var safetyTimer = null;

    function cleanup() {
      if (progressListener && viewer) {
        viewer.scene.globe.tileLoadProgressEvent.removeEventListener(
          progressListener
        );
      }
      progressListener = null;
      if (idleTimer) {
        clearTimeout(idleTimer);
      }
      if (warmupTimer) {
        clearTimeout(warmupTimer);
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

    progressListener = function (remaining) {
      if (generation !== applyGeneration) {
        cleanup();
        return;
      }
      remainingNow = remaining;
      if (!watching) {
        return;
      }
      if (remaining > 0) {
        saw = true;
        if (idleTimer) {
          clearTimeout(idleTimer);
          idleTimer = null;
        }
        return;
      }
      if (saw) {
        if (idleTimer) {
          clearTimeout(idleTimer);
        }
        idleTimer = setTimeout(finish, 300);
      }
    };
    viewer.scene.globe.tileLoadProgressEvent.addEventListener(progressListener);
    viewer.scene.requestRender();

    warmupTimer = setTimeout(function () {
      watching = true;
      if (remainingNow > 0) {
        saw = true;
        return;
      }
      finish();
    }, 800);
    safetyTimer = setTimeout(finish, 30000);
    tilesWaitCleanup = cleanup;
  }

  /**
   * Approximate OpenLayers zoom from camera height (inverse of heightForZoom).
   */
  function zoomForHeight(height, latitude) {
    var h = isFinite(height) ? Number(height) : FULL_GLOBE_HEIGHT_M;
    var canvas = viewer && viewer.scene && viewer.scene.canvas;
    var heightPx =
      (canvas && (canvas.clientHeight || canvas.height)) || 720;
    var latRad = Cesium.Math.toRadians(isFinite(latitude) ? Number(latitude) : 0);
    var fovy = Math.PI / 3;
    if (
      viewer &&
      viewer.camera &&
      viewer.camera.frustum &&
      isFinite(viewer.camera.frustum.fovy)
    ) {
      fovy = viewer.camera.frustum.fovy;
    }
    var groundHeightM = (h * 2 * Math.tan(fovy * 0.5));
    var metersPerPixel = groundHeightM / Math.max(heightPx, 1);
    var cosLat = Math.max(Math.cos(latRad), 0.1);
    var zoom = Math.log2((WEB_MERCATOR_MPP_Z0 * cosLat) / metersPerPixel);
    if (!isFinite(zoom)) {
      return 0;
    }
    return Math.max(0, Math.min(22, Math.round(zoom)));
  }

  function lonLatToTileXY(lon, lat, z) {
    var n = Math.pow(2, z);
    var x = Math.floor(((lon + 180) / 360) * n);
    var latRad = (lat * Math.PI) / 180;
    var y = Math.floor(
      ((1 -
        Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) /
        2) *
        n
    );
    return {
      x: Math.max(0, Math.min(n - 1, x)),
      y: Math.max(0, Math.min(n - 1, y)),
    };
  }

  /**
   * Warm tile URLs for the current globe viewport so the next steps paint sooner.
   *
   * Viewport range is Cesium-specific; Image() warming is shared via
   * ForecastMap.prefetchTileImages.
   */
  function prefetchLayers(layers, options) {
    if (!viewer || !layers || !layers.length) {
      return;
    }
    if (
      !global.ForecastMap ||
      typeof global.ForecastMap.prefetchTileImages !== "function"
    ) {
      return;
    }
    var canvas = viewer.scene && viewer.scene.canvas;
    if (!canvas || !(canvas.clientWidth || canvas.width)) {
      return;
    }
    var carto = Cesium.Cartographic.fromCartesian(viewer.camera.positionWC);
    if (!carto) {
      return;
    }
    var lat = Cesium.Math.toDegrees(carto.latitude);
    var z = zoomForHeight(carto.height, lat);
    var zDelta = options && options.zDelta != null ? Number(options.zDelta) : 0;
    if (!isNaN(zDelta) && zDelta) {
      z = Math.max(0, z + zDelta);
    }
    var rect = viewer.camera.computeViewRectangle(
      viewer.scene.globe.ellipsoid
    );
    var west;
    var south;
    var east;
    var north;
    if (rect) {
      west = Cesium.Math.toDegrees(rect.west);
      south = Cesium.Math.toDegrees(rect.south);
      east = Cesium.Math.toDegrees(rect.east);
      north = Cesium.Math.toDegrees(rect.north);
    } else {
      // Camera may not yield a rectangle when pitched / zoomed out; warm a
      // small patch around the look target instead.
      var lon = Cesium.Math.toDegrees(carto.longitude);
      west = lon - 20;
      east = lon + 20;
      south = Math.max(lat - 15, -85);
      north = Math.min(lat + 15, 85);
    }
    if (east < west) {
      // Dateline wrap: prefetch the larger contiguous side only.
      if (east + 180 > 180 - west) {
        west = -180;
      } else {
        east = 180;
      }
    }
    var sw = lonLatToTileXY(west, south, z);
    var ne = lonLatToTileXY(east, north, z);
    var maxTiles =
      options && options.maxTiles != null ? Number(options.maxTiles) : 8;
    global.ForecastMap.prefetchTileImages(layers, {
      z: z,
      minX: Math.min(sw.x, ne.x),
      maxX: Math.max(sw.x, ne.x),
      minY: Math.min(sw.y, ne.y),
      maxY: Math.max(sw.y, ne.y),
      maxTiles: maxTiles,
    });
  }

  /**
   * Swap forecast imagery URLs for a leadtime step without rebuilding the viewer.
   *
   * Play paces on hasPendingSwap and does not wait here. Scrub and
   * rebuilds pass waitForTiles so "Loading tiles…" stays until imagery
   * has settled.
   *
   * @param {Array} layers
   * @param {{holdUntilReady?: boolean, waitForTiles?: boolean}} [options]
   */
  function applyLeadtime(layers, options) {
    if (!ensureViewer()) {
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
    syncLayers(layers || [], {
      smooth: true,
      holdUntilReady: holdUntilReady,
      waitForPaint: waitForPaint,
    });
    viewer.scene.requestRender();
    if (waitForPaint) {
      waitForTiles(generation);
      return;
    }
    markTilesReady(generation);
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
    // Soft-swap with hold so globe / TMS switches do not flash empty imagery.
    syncLayers(state.layers, { smooth: true, holdUntilReady: true });
    viewer.resize();
    // ensureViewer may have run while the host was still hidden.
    if (wasHidden) {
      showFullGlobe();
    }
    if (state.layers && state.layers.length) {
      waitForTiles(generation);
    }
    // Empty overlays (view-mode switch): ForecastMap keeps the tiles wait
    // until Python publishes the new URLs. Do not clear it here.
  }

  global.ForecastMapCesium = {
    applyState: applyState,
    applyLeadtime: applyLeadtime,
    prefetchLayers: prefetchLayers,
    hasPendingSwap: hasPendingSwap,
    setBasemap: setBasemap,
    resetView: showFullGlobe,
    flyToPlace: flyToPlace,
    clearLastPlace: clearLastPlace,
  };
})(window);
