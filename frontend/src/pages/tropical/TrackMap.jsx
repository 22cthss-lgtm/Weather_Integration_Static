// Leaflet map for official tracks (design.md 7.2, 7.3). Loaded lazily with the Forecast tab only.
// No tile layer and no external request: the land is a bundled Natural Earth GeoJSON, already in
// 0-360 longitudes. It draws only what tracks.js drawables() returns.
import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { MAP_BOUNDS, MAP_CENTER, gridLatLabel, gridLonLabel } from "../../tropical/tracks";

const PLACES = [
  // Placed beside, not on, the land they name so the islands stay visible.
  { name: "臺灣", lat: 23.6, lon: 124.3 },
  { name: "菲律賓", lat: 12.5, lon: 128.5 },
  { name: "日本", lat: 33, lon: 142 },
  { name: "關島", lat: 13.4, lon: 147.5 },
  { name: "夏威夷", lat: 24.2, lon: 203 },
];

function label(text, className) {
  const span = document.createElement("span");
  span.textContent = text;
  return L.divIcon({ className: `tc-map-label ${className}`, html: span.outerHTML, iconSize: [0, 0] });
}

// Leaflet 1.9.4: a synchronous redraw clears the pending-frame handle without cancelling the frame,
// so a frame queued before map.remove() can still run after the canvas context is deleted and throw.
// Skipping the redraw once the context is gone is the only change; drawing is otherwise Leaflet's own.
const SafeCanvas = L.Canvas.extend({
  _redraw() {
    if (!this._ctx) return;
    L.Canvas.prototype._redraw.call(this);
  },
});

// Leaflet 1.9.4: the zoom animation ends through an untracked 250 ms timer that remove() does not
// clear; if the tab closes mid-zoom the late callback reads the removed panes and throws.
const SafeMap = L.Map.extend({
  _onZoomTransitionEnd() {
    if (this._containerId === undefined) return; // already removed
    L.Map.prototype._onZoomTransitionEnd.call(this);
  },
});

// Land under the grid under the tracks; each pane has its own canvas.
function addPane(map, name, zIndex) {
  const pane = map.createPane(name);
  pane.style.zIndex = String(zIndex);
  pane.style.pointerEvents = "none";
  return new SafeCanvas({ pane: name });
}

function drawGrid(map) {
  const renderer = addPane(map, "tcGrid", 250);
  const grid = { color: "#9fb3c8", weight: 0.6, opacity: 0.8, interactive: false, renderer };
  for (let lon = 80; lon <= 220; lon += 10) L.polyline([[-10, lon], [65, lon]], grid).addTo(map);
  for (let lat = -10; lat <= 60; lat += 10) L.polyline([[lat, 80], [lat, 220]], grid).addTo(map);
  const quiet = { interactive: false, keyboard: false };
  // Graticule labels follow the visible south and west edges so they stay readable when zoomed in.
  const lonLabels = [];
  for (let lon = 80; lon <= 220; lon += 10) {
    lonLabels.push([lon, L.marker([-8, lon], { ...quiet, icon: label(gridLonLabel(lon), "tc-map-grid") }).addTo(map)]);
  }
  const latLabels = [];
  for (let lat = -10; lat <= 60; lat += 10) {
    latLabels.push([lat, L.marker([lat, 82], { ...quiet, icon: label(gridLatLabel(lat), "tc-map-grid") }).addTo(map)]);
  }
  const place = () => {
    const view = map.getBounds();
    const south = view.getSouth() + (view.getNorth() - view.getSouth()) * 0.04;
    const west = view.getWest() + (view.getEast() - view.getWest()) * 0.05;
    const step = map.getZoom() >= 5 ? 10 : 20; // fewer labels when zoomed out
    for (const [lon, marker] of lonLabels) {
      marker.setLatLng([south, lon]);
      marker.setOpacity(lon % step === 0 ? 1 : 0);
    }
    for (const [lat, marker] of latLabels) {
      marker.setLatLng([lat, west]);
      marker.setOpacity(lat % step === 0 ? 1 : 0);
    }
  };
  map.on("moveend zoomend", place);
  place();
  for (const place of PLACES) {
    L.marker([place.lat, place.lon], { ...quiet, icon: label(place.name, "tc-map-place") }).addTo(map);
  }
}

export default function TrackMap({ items, colors, onSelectNode, ready = true }) {
  const container = useRef(null);
  const mapRef = useRef(null);
  const tracksLayer = useRef(null);
  const fitted = useRef(false);
  const selectRef = useRef(onSelectNode);
  selectRef.current = onSelectNode;

  useEffect(() => {
    const map = new SafeMap(container.current, {
      preferCanvas: true,
      renderer: new SafeCanvas(),
      center: MAP_CENTER,
      zoom: 3,
      minZoom: 2,
      maxZoom: 9,
      maxBounds: MAP_BOUNDS,
      maxBoundsViscosity: 1,
      worldCopyJump: false,
      scrollWheelZoom: false,
      attributionControl: false,
    });
    map.zoomControl.setPosition("topright"); // keep the west-edge latitude labels uncovered
    mapRef.current = map;
    fitted.current = false; // a new map instance (StrictMode remounts) fits the tracks again
    tracksLayer.current = L.layerGroup().addTo(map);
    let active = true;
    const landRenderer = addPane(map, "tcLand", 200);
    drawGrid(map);
    import("../../tropical/basemap/ne-land-wp.json")
      .then(module => {
        if (!active) return;
        L.geoJSON(module.default, {
          interactive: false, renderer: landRenderer,
          style: { stroke: false, fill: true, fillColor: "#d8d3c4", fillOpacity: 1 },
        }).addTo(map);
      })
      .catch(() => { /* the tracks stay usable without the coastline */ });
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(() => map.invalidateSize()) : null;
    observer?.observe(container.current);
    return () => {
      active = false;
      observer?.disconnect();
      map.remove();
      mapRef.current = null;
      tracksLayer.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = tracksLayer.current;
    if (!map || !layer) return;
    layer.clearLayers();
    const bounds = [];
    // Areas first, then lines, then nodes, so nothing covers a clickable node.
    const order = { radii: 0, circle: 1, line: 2, node: 3 };
    const sorted = [...items].sort((left, right) => order[left.type] - order[right.type]);
    for (const item of sorted) {
      const color = colors[item.agency];
      if (item.type === "line") {
        L.polyline(item.latlngs, {
          color, weight: item.layer === "past" ? 2 : 2.5, dashArray: item.layer === "forecast" ? "6 6" : null,
          interactive: false,
        }).addTo(layer);
        bounds.push(...item.latlngs);
      } else if (item.type === "circle") {
        L.circle(item.center, {
          radius: item.radiusM, color, weight: item.highlighted ? 2 : 1, opacity: 0.8,
          fillColor: color, fillOpacity: item.highlighted ? 0.18 : 0.07, dashArray: "3 4", interactive: false,
        }).addTo(layer);
      } else if (item.type === "radii") {
        L.polygon(item.latlngs, { color, weight: 1, opacity: 0.6, fillColor: color, fillOpacity: 0.12, interactive: false })
          .addTo(layer);
      } else if (item.type === "node") {
        const radius = item.nodeKind === "fix" ? 7 : item.nodeKind === "forecast" ? 5 : 3;
        const emphasis = item.selected || item.highlighted;
        L.circleMarker(item.latlng, {
          radius: emphasis ? radius + 3 : radius,
          color: emphasis ? "#111" : "#fff",
          weight: emphasis ? 3 : 1.5,
          fillColor: color,
          fillOpacity: 1,
        }).on("click", () => selectRef.current(item.nodeId)).addTo(layer);
        bounds.push(item.latlng);
      }
    }
    // Fit once, after both storm files have settled, so a late forecast is not left off screen.
    if (ready && !fitted.current && bounds.length) {
      fitted.current = true;
      // No animation: a zoom transition still running when the tab closes makes Leaflet throw after remove().
      map.fitBounds(bounds, { padding: [30, 30], maxZoom: 6, animate: false });
    }
  }, [items, colors, ready]);

  return <div ref={container} className="tc-map" role="region" aria-label="官方路徑地圖（可拖曳與縮放）" />;
}
