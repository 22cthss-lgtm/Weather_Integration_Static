// Map and timeline model for the Forecast tab (design.md 7.2, 7.3, 7.5).
// Pure functions: no Leaflet, no clock. The map component only draws what drawables() returns,
// so layer toggles, the 180-degree unwrap and the "no interpolation" rule are testable here.
import { AGENCIES, parseUtcStamp } from "./status";

const EARTH_RADIUS_M = 6371008.8;
const NM_M = 1852; // unit conversion for drawing only
const KM_M = 1000;

/**
 * The only place longitudes are unwrapped (design.md 7.3): data files use -180 (inclusive)
 * to 180 (exclusive); the map plots 0-360 so tracks crossing 180 stay continuous.
 * Values shown to people are the original contract longitudes, never this one.
 */
export function unwrapLon(lon) {
  return lon < 0 ? lon + 360 : lon;
}

export const LAYERS = ["past", "forecast", "circles", "radii"];

export function defaultToggles() {
  return {
    agencies: Object.fromEntries(AGENCIES.map(agency => [agency, true])),
    // Wind radii are off by default (user decision D3, 2026-11-18).
    layers: { past: true, forecast: true, circles: true, radii: false },
  };
}

function node(agency, kind, index, point, time, extra = {}) {
  return {
    id: `${agency}:${kind}:${index}`,
    agency, kind, time,
    tauH: null,
    lat: point.lat,
    lon: point.lon,
    plotLon: unwrapLon(point.lon),
    category: point.category ?? null,
    maxWind: point.max_wind ?? null,
    gust: point.gust ?? null,
    pressure: point.pressure_hpa ?? null,
    movement: null,
    radii: Array.isArray(point.radii) ? point.radii : [],
    probabilityCircle: null,
    note: null,
    ...extra,
  };
}

function fileStatus(file, agency) {
  if (file === undefined) return "loading";
  if (file === null) return "unavailable";
  return file.agencies[agency].status;
}

/**
 * @param analysis checkStormFile() result, null when the file could not be read, undefined while loading
 * @param forecast same for forecast.json
 */
export function buildTracks(analysis, forecast) {
  return AGENCIES.map(agency => {
    const analysisStatus = fileStatus(analysis, agency);
    const forecastStatus = fileStatus(forecast, agency);
    const a = analysisStatus === "ok" ? analysis.agencies[agency].block : null;
    const f = forecastStatus === "ok" ? forecast.agencies[agency].block : null;
    const fix = a ? node(agency, "fix", 0, a.fix, a.fix.analysis_time, { movement: a.fix.movement ?? null }) : null;
    const past = a ? a.past_track.map((point, index) => node(agency, "past", index, point, point.analysis_time)) : [];
    const points = f ? f.points.map((point, index) => node(agency, "forecast", index, point, point.valid_time, {
      tauH: point.tau_h,
      probabilityCircle: point.probability_circle ?? null,
      note: point.note ?? null,
    })) : [];
    return {
      agency, analysisStatus, forecastStatus,
      issuedAt: a ? a.issued_at : null,
      bulletin: a ? a.bulletin ?? null : null,
      final: a ? a.final : false,
      pastOrigin: a ? a.past_track_origin ?? null : null,
      initTime: f ? f.init_time : null,
      forecastIssuedAt: f ? f.issued_at : null,
      forecastBulletin: f ? f.bulletin ?? null : null,
      fix, past, points,
      // The forecast line starts at the fix only when the forecast is based on that same fix.
      fixMatchesInit: Boolean(fix && f && fix.time === f.init_time),
    };
  });
}

export function findNode(tracks, nodeId) {
  for (const track of tracks) {
    for (const item of [track.fix, ...track.past, ...track.points]) {
      if (item && item.id === nodeId) return item;
    }
  }
  return null;
}

export const ANALYSIS_KEY = "analysis";

/**
 * Timeline (design.md 7.5, 9.4 S7): one tick per distinct valid_time that some agency really
 * forecast, plus a first "latest analysis" step whose entries keep each agency's own fix time.
 * No tick is interpolated and no node is moved to a tick it does not have.
 */
export function buildTimeline(tracks) {
  const analysis = tracks.filter(track => track.fix).map(track => ({
    agency: track.agency, nodeId: track.fix.id, time: track.fix.time, tauH: null, initTime: null,
  }));
  const byTime = new Map();
  for (const track of tracks) {
    for (const point of track.points) {
      if (!byTime.has(point.time)) byTime.set(point.time, []);
      byTime.get(point.time).push({
        agency: track.agency, nodeId: point.id, time: point.time, tauH: point.tauH, initTime: track.initTime,
      });
    }
  }
  const ticks = [...byTime.entries()]
    .map(([time, entries]) => ({ key: time, time, entries }))
    .sort((left, right) => parseUtcStamp(left.time) - parseUtcStamp(right.time));
  return { analysis: { key: ANALYSIS_KEY, time: null, entries: analysis }, ticks };
}

export function entriesAt(timeline, key) {
  if (key === ANALYSIS_KEY) return timeline.analysis.entries;
  const tick = timeline.ticks.find(item => item.key === key);
  return tick ? tick.entries : [];
}

/** Distinct forecast init times among agencies that have forecast points. */
export function initTimes(tracks) {
  return [...new Set(tracks.filter(track => track.points.length && track.initTime).map(track => track.initTime))];
}

function destination(lat, lon, bearingDeg, distanceM) {
  const angular = distanceM / EARTH_RADIUS_M;
  const bearing = (bearingDeg * Math.PI) / 180;
  const phi1 = (lat * Math.PI) / 180;
  const lambda1 = (lon * Math.PI) / 180;
  const phi2 = Math.asin(Math.sin(phi1) * Math.cos(angular) + Math.cos(phi1) * Math.sin(angular) * Math.cos(bearing));
  const lambda2 = lambda1 + Math.atan2(Math.sin(bearing) * Math.sin(angular) * Math.cos(phi1),
    Math.cos(angular) - Math.sin(phi1) * Math.sin(phi2));
  return [(phi2 * 180) / Math.PI, (lambda2 * 180) / Math.PI];
}

export function lengthToMeters(value, unit) {
  if (unit === "nm") return value * NM_M;
  if (unit === "km") return value * KM_M;
  return null;
}

const QUADRANTS = { NE: [0, 90], SE: [90, 180], SW: [180, 270], NW: [270, 360] };

/**
 * Wedges for one wind-radii threshold. Only the two forms whose geometry is unambiguous are
 * drawn: four quadrants (NE/SE/SW/NW) and a single ALL radius. Other direction sets are left to
 * the text in the node details, so the map never guesses a shape the agency did not give.
 * A null radius is "not given" and draws nothing for that quadrant.
 */
export function radiiShapes(center, radii) {
  const meters = lengthToMeters(1, radii.unit);
  const dirs = radii.sectors.map(sector => sector.dir).sort().join(",");
  if (meters === null) return null;
  const shapes = [];
  const arc = (radius, from, to) => {
    const points = [];
    for (let angle = from; angle <= to; angle += 5) {
      const [lat, lon] = destination(center.lat, center.plotLon, angle, radius * meters);
      points.push([lat, lon]);
    }
    return points;
  };
  if (dirs === "ALL") {
    const radius = radii.sectors[0].radius;
    if (typeof radius === "number" && radius > 0) shapes.push(arc(radius, 0, 355));
    return shapes;
  }
  if (dirs !== "NE,NW,SE,SW") return null;
  for (const sector of radii.sectors) {
    if (typeof sector.radius !== "number" || sector.radius <= 0) continue;
    const [from, to] = QUADRANTS[sector.dir];
    shapes.push([[center.lat, center.plotLon], ...arc(sector.radius, from, to)]);
  }
  return shapes;
}

/**
 * What the map draws for the current toggles and timeline selection.
 * Each item carries plotted [lat, lon] pairs (lon already unwrapped).
 */
export function drawables(tracks, toggles, selectedKey = null, selectedNodeId = null) {
  const timeline = buildTimeline(tracks);
  const highlighted = new Set(selectedKey === null ? [] : entriesAt(timeline, selectedKey).map(entry => entry.nodeId));
  const items = [];
  const at = item => [item.lat, item.plotLon];
  const nodeItem = (item, layer) => ({
    type: "node", layer, agency: item.agency, nodeId: item.id, nodeKind: item.kind, latlng: at(item),
    highlighted: highlighted.has(item.id), selected: item.id === selectedNodeId,
  });
  for (const track of tracks) {
    if (!toggles.agencies[track.agency]) continue;
    const { layers } = toggles;
    if (layers.past && track.past.length) {
      const line = [...track.past, ...(track.fix ? [track.fix] : [])];
      if (line.length > 1) items.push({ type: "line", layer: "past", agency: track.agency, latlngs: line.map(at) });
      for (const item of track.past) items.push(nodeItem(item, "past"));
    }
    if (layers.forecast && track.points.length) {
      const line = [...(track.fixMatchesInit ? [track.fix] : []), ...track.points];
      if (line.length > 1) items.push({ type: "line", layer: "forecast", agency: track.agency, latlngs: line.map(at) });
      for (const item of track.points) items.push(nodeItem(item, "forecast"));
    }
    if (track.fix && (layers.past || layers.forecast)) items.push(nodeItem(track.fix, "fix"));
    if (layers.circles) {
      for (const item of track.points) {
        const circle = item.probabilityCircle;
        const radius = circle ? lengthToMeters(circle.radius, circle.unit) : null;
        if (radius !== null && radius > 0) {
          items.push({ type: "circle", layer: "circles", agency: track.agency, nodeId: item.id, center: at(item),
            radiusM: radius, highlighted: highlighted.has(item.id) });
        }
      }
    }
    if (layers.radii && track.fix) {
      for (const radii of track.fix.radii) {
        const shapes = radiiShapes(track.fix, radii);
        if (!shapes) continue;
        for (const shape of shapes) {
          items.push({ type: "radii", layer: "radii", agency: track.agency, threshold: radii.threshold, latlngs: shape });
        }
      }
    }
  }
  return items;
}

/** Graticule label for a plotted (0-360) longitude, shown as east/west like the data. */
export function gridLonLabel(plotLon) {
  const lon = ((plotLon + 180) % 360 + 360) % 360 - 180; // back to -180..180
  if (lon === 0 || lon === -180) return `${Math.abs(lon)}°`;
  return `${Math.abs(lon)}°${lon > 0 ? "E" : "W"}`;
}

export function gridLatLabel(lat) {
  if (lat === 0) return "0°";
  return `${Math.abs(lat)}°${lat > 0 ? "N" : "S"}`;
}

// Map extent (design.md 7.3): centred near 140E, dragging limited to about 80E-220 (140W).
export const MAP_CENTER = [22, 140];
export const MAP_BOUNDS = [[-15, 80], [70, 220]];
