import { expect, test } from "vitest";
import { checkStormFile } from "./tropical/storm-files";
import {
  ANALYSIS_KEY, buildTimeline, buildTracks, defaultToggles, drawables, entriesAt, findNode, gridLatLabel,
  gridLonLabel, initTimes, lengthToMeters, radiiShapes, unwrapLon,
} from "./tropical/tracks";
import { formatLongitude } from "./tropical/format";
import { cempakaAnalysis, cempakaForecast, penaAnalysis, penaForecast } from "./tropical/storm-test-fixtures";

const ID = "2026-jma-tc2638";

function cempakaTracks(mutate = () => {}) {
  const analysis = cempakaAnalysis();
  const forecast = cempakaForecast();
  mutate(analysis, forecast);
  return buildTracks(checkStormFile(analysis, "analysis", ID), checkStormFile(forecast, "forecast", ID));
}

function penaTracks() {
  return buildTracks(checkStormFile(penaAnalysis(), "analysis", "2026-jtwc-04c"),
    checkStormFile(penaForecast(), "forecast", "2026-jtwc-04c"));
}

test.each([
  [179.5, 179.5], [-179.5, 180.5], [-171.3, 188.7], [-180.0, 180], [0, 0], [120.4, 120.4], [-0.1, 359.9],
])("unwrapLon(%s) is %s", (input, expected) => {
  expect(unwrapLon(input)).toBeCloseTo(expected, 10);
});

test("PENA across 180 stays continuous on the map but is shown as east/west", () => {
  const [jtwc] = penaTracks().filter(track => track.agency === "jtwc");
  const plotted = [jtwc.fix, ...jtwc.points].map(item => item.plotLon);
  expect(plotted.map(value => Math.round(value * 10) / 10)).toEqual([188.7, 185.7, 182.6, 180]);
  for (let i = 1; i < plotted.length; i += 1) expect(Math.abs(plotted[i] - plotted[i - 1])).toBeLessThan(10);
  // Displayed values come from the contract longitude, never the unwrapped one.
  expect(formatLongitude(jtwc.fix.lon)).toBe("171.3°W");
  expect(formatLongitude(jtwc.points[2].lon)).toBe("180.0°");
  const line = drawables(penaTracks(), defaultToggles()).find(item => item.type === "line" && item.layer === "forecast");
  expect(line.latlngs.every(([, lon]) => lon >= 180 && lon <= 189)).toBe(true);
});

test("grid labels convert plotted longitudes back to east/west", () => {
  expect([100, 180, 200, 220].map(gridLonLabel)).toEqual(["100°E", "180°", "160°W", "140°W"]);
  expect([-10, 0, 40].map(gridLatLabel)).toEqual(["10°S", "0°", "40°N"]);
});

test("tracks keep each agency's own fix, past track, forecast and init time", () => {
  const tracks = cempakaTracks();
  const byAgency = Object.fromEntries(tracks.map(track => [track.agency, track]));
  expect(byAgency.jtwc.initTime).toBe("2026-11-11T06:00:00Z");
  expect(byAgency.jma.initTime).toBe("2026-11-11T09:00:00Z");
  expect(byAgency.cwa.past).toHaveLength(2);
  expect(byAgency.cwa.pastOrigin).toBe("source");
  expect(byAgency.jtwc.pastOrigin).toBe("accumulated");
  expect(byAgency.jma.points.map(point => point.tauH)).toEqual([12, 24]);
  expect(byAgency.jma.fixMatchesInit).toBe(true);
  expect(findNode(tracks, "jma:forecast:1").time).toBe("2026-11-12T09:00:00Z");
  expect(initTimes(tracks).sort()).toEqual(["2026-11-11T06:00:00Z", "2026-11-11T09:00:00Z"]);
});

test("the timeline uses only real valid times and never interpolates", () => {
  const timeline = buildTimeline(cempakaTracks());
  expect(timeline.ticks.map(tick => tick.key)).toEqual([
    "2026-11-11T12:00:00Z", // CWA +6
    "2026-11-11T18:00:00Z", // JTWC +12, CWA +12
    "2026-11-11T21:00:00Z", // JMA +12
    "2026-11-12T06:00:00Z", // JTWC +24
    "2026-11-12T09:00:00Z", // JMA +24
  ]);
  const at18 = entriesAt(timeline, "2026-11-11T18:00:00Z");
  expect(at18.map(entry => [entry.agency, entry.tauH, entry.initTime])).toEqual([
    ["cwa", 12, "2026-11-11T06:00:00Z"], ["jtwc", 12, "2026-11-11T06:00:00Z"],
  ]);
  // JMA has no node at 18Z (it has 21Z): nothing is produced for it at that tick.
  expect(at18.some(entry => entry.agency === "jma")).toBe(false);
  expect(entriesAt(timeline, "2026-11-11T19:00:00Z")).toEqual([]);
  // The analysis step keeps each agency's own analysis time.
  expect(entriesAt(timeline, ANALYSIS_KEY).map(entry => [entry.agency, entry.time])).toEqual([
    ["cwa", "2026-11-11T06:00:00Z"], ["jma", "2026-11-11T09:00:00Z"], ["jtwc", "2026-11-11T06:00:00Z"],
  ]);
});

test("highlighting a tick only marks nodes with exactly that valid time", () => {
  const items = drawables(cempakaTracks(), defaultToggles(), "2026-11-11T18:00:00Z");
  const marked = items.filter(item => item.type === "node" && item.highlighted).map(item => item.nodeId).sort();
  expect(marked).toEqual(["cwa:forecast:1", "jtwc:forecast:0"]);
});

test("layer toggles decide what is drawn", () => {
  const tracks = cempakaTracks();
  const kinds = toggles => drawables(tracks, toggles).map(item => `${item.agency}:${item.type}:${item.layer}`);
  const all = kinds(defaultToggles());
  expect(all).toContain("jma:circle:circles");
  expect(all).toContain("cwa:line:past");
  expect(all.some(kind => kind.includes(":radii"))).toBe(false); // radii off by default

  const noJma = defaultToggles();
  noJma.agencies.jma = false;
  expect(kinds(noJma).some(kind => kind.startsWith("jma:"))).toBe(false);
  expect(kinds(noJma).some(kind => kind.startsWith("jtwc:"))).toBe(true);

  const noPast = defaultToggles();
  noPast.layers.past = false;
  expect(kinds(noPast).some(kind => kind.endsWith(":past"))).toBe(false);
  expect(kinds(noPast)).toContain("cwa:node:fix");

  const noCircles = defaultToggles();
  noCircles.layers.circles = false;
  expect(kinds(noCircles).some(kind => kind.includes(":circle:"))).toBe(false);

  const nothing = defaultToggles();
  nothing.layers.past = false;
  nothing.layers.forecast = false;
  expect(kinds(nothing).some(kind => kind.includes(":node:"))).toBe(false);
});

test("JTWC never gets a probability circle; JMA and CWA circles use the agency radius", () => {
  const circles = drawables(cempakaTracks(), defaultToggles()).filter(item => item.type === "circle");
  expect(circles.some(item => item.agency === "jtwc")).toBe(false);
  expect(circles.find(item => item.nodeId === "jma:forecast:0").radiusM).toBe(85000);
  expect(circles.find(item => item.nodeId === "cwa:forecast:0").radiusM).toBe(40000);
  expect(lengthToMeters(1, "nm")).toBe(1852);
  expect(lengthToMeters(1, "mi")).toBeNull();
});

test("wind radii draw quadrants and ALL only, skipping missing quadrants", () => {
  const toggles = defaultToggles();
  toggles.layers.radii = true;
  const radii = drawables(cempakaTracks(), toggles).filter(item => item.type === "radii");
  expect(radii.filter(item => item.agency === "jtwc")).toHaveLength(12); // 3 thresholds x 4 quadrants
  expect(radii.filter(item => item.agency === "jma")).toHaveLength(2); // two ALL circles
  const center = { lat: 10, plotLon: 188.7 };
  const partial = { threshold: { value: 34, unit: "kt" }, unit: "nm",
    sectors: [{ dir: "NE", radius: 100 }, { dir: "SE", radius: null }, { dir: "SW", radius: null }, { dir: "NW", radius: null }] };
  expect(radiiShapes(center, partial)).toHaveLength(1);
  const directional = { threshold: { value: 50, unit: "kt" }, unit: "nm", sectors: [{ dir: "NE", radius: 60 }, { dir: "SW", radius: 40 }] };
  expect(radiiShapes(center, directional)).toBeNull();
  // The NE wedge stays east of the centre on the unwrapped axis.
  const [wedge] = radiiShapes(center, partial);
  expect(wedge.every(([, lon]) => lon >= 188.7 - 1e-9 && lon < 191)).toBe(true);
});

test("a forecast not based on the shown fix is not joined to it", () => {
  const tracks = cempakaTracks((analysis, forecast) => {
    forecast.agencies.jma.init_time = "2026-11-11T03:00:00Z";
    forecast.agencies.jma.points.forEach(point => {
      point.valid_time = new Date(Date.parse("2026-11-11T03:00:00Z") + point.tau_h * 3600e3).toISOString().slice(0, 19) + "Z";
    });
  });
  const jma = tracks.find(track => track.agency === "jma");
  expect(jma.fixMatchesInit).toBe(false);
  const line = drawables(tracks, defaultToggles()).find(item => item.type === "line" && item.agency === "jma");
  expect(line.latlngs).toHaveLength(2);
  expect(line.latlngs[0]).toEqual([32.1, 158.6]);
});

test("missing files, null blocks and empty points leave the other agencies usable", () => {
  const unavailable = buildTracks(null, null);
  expect(unavailable.every(track => track.analysisStatus === "unavailable" && !track.fix && !track.points.length)).toBe(true);
  expect(buildTimeline(unavailable).ticks).toEqual([]);
  expect(drawables(unavailable, defaultToggles())).toEqual([]);

  const loading = buildTracks(undefined, undefined);
  expect(loading.every(track => track.analysisStatus === "loading")).toBe(true);

  const tracks = cempakaTracks((analysis, forecast) => {
    analysis.agencies.jma = null;
    forecast.agencies.jtwc = null;
    forecast.agencies.cwa.points = [];
  });
  const by = Object.fromEntries(tracks.map(track => [track.agency, track]));
  expect([by.jma.analysisStatus, by.jma.forecastStatus, by.jma.fix]).toEqual(["missing", "ok", null]);
  expect(by.jma.points).toHaveLength(2);
  expect(by.jtwc.forecastStatus).toBe("missing");
  expect(by.jtwc.fix).not.toBeNull();
  expect(by.cwa.points).toEqual([]);
  expect(buildTimeline(tracks).ticks.map(tick => tick.key)).toEqual(["2026-11-11T21:00:00Z", "2026-11-12T09:00:00Z"]);
});
