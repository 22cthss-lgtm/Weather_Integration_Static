import { expect, test } from "vitest";
import { checkStormFile, isValidPosition } from "./tropical/storm-files";
import { cempakaAnalysis, cempakaForecast, penaForecast } from "./tropical/storm-test-fixtures";

const ID = "2026-jma-tc2638";

test("real CEMPAKA files pass with every agency usable", () => {
  const analysis = checkStormFile(cempakaAnalysis(), "analysis", ID);
  const forecast = checkStormFile(cempakaForecast(), "forecast", ID);
  for (const file of [analysis, forecast]) {
    expect(Object.values(file.agencies).map(item => item.status)).toEqual(["ok", "ok", "ok"]);
  }
  expect(analysis.fetchedAt).toBe("2026-11-11T10:30:00Z");
  expect(checkStormFile(penaForecast(), "forecast", "2026-jtwc-04c").agencies.jtwc.status).toBe("ok");
});

test.each([
  ["not an object", () => "x"],
  ["array", () => []],
  ["schema_version 2", data => ({ ...data, schema_version: 2 })],
  ["schema_version as string", data => ({ ...data, schema_version: "1" })],
  ["cyclone_id of another storm", data => ({ ...data, cyclone_id: "2026-jma-tc2637" })],
  ["agencies missing", data => ({ ...data, agencies: null })],
  ["an agency key missing", data => { delete data.agencies.cwa; return data; }],
])("a file with %s is a read failure", (_, mutate) => {
  expect(checkStormFile(mutate(cempakaAnalysis()), "analysis", ID)).toBeNull();
  expect(checkStormFile(mutate(cempakaForecast()), "forecast", ID)).toBeNull();
});

test("a null agency block is missing data, not a failure", () => {
  const data = cempakaAnalysis();
  data.agencies.jma = null;
  const result = checkStormFile(data, "analysis", ID);
  expect(result.agencies.jma).toEqual({ status: "missing" });
  expect(result.agencies.jtwc.status).toBe("ok");
});

test.each([
  ["fix longitude 180.0", data => { data.agencies.jtwc.fix.lon = 180.0; }],
  ["fix latitude out of range", data => { data.agencies.jtwc.fix.lat = 91; }],
  ["fix without analysis_time", data => { data.agencies.jtwc.fix.analysis_time = "2026-11-11 06:00"; }],
  ["past point after the fix", data => {
    data.agencies.cwa.past_track.push({ ...data.agencies.cwa.past_track[0], analysis_time: "2026-11-11T07:00:00Z" });
  }],
  ["past track not increasing", data => { data.agencies.cwa.past_track.reverse(); }],
  ["past track not a list", data => { data.agencies.cwa.past_track = null; }],
  ["final not a boolean", data => { data.agencies.jtwc.final = "no"; }],
  ["radii not a list", data => { data.agencies.jtwc.fix.radii = null; }],
  ["a null radii sector", data => { data.agencies.jtwc.fix.radii[0].sectors = [null]; }],
  ["radii without sectors", data => { delete data.agencies.jtwc.fix.radii[0].sectors; }],
  ["radii without a threshold", data => { data.agencies.jtwc.fix.radii[0].threshold = null; }],
  ["a sector radius as text", data => { data.agencies.jtwc.fix.radii[0].sectors[0].radius = "20"; }],
])("analysis block with %s only fails that agency", (_, mutate) => {
  const data = cempakaAnalysis();
  mutate(data);
  const result = checkStormFile(data, "analysis", ID);
  const statuses = Object.fromEntries(Object.entries(result.agencies).map(([key, value]) => [key, value.status]));
  expect(Object.values(statuses).filter(status => status === "invalid")).toHaveLength(1);
  expect(Object.values(statuses).filter(status => status === "ok")).toHaveLength(2);
});

test.each([
  ["valid_time not equal to init_time + tau_h", data => { data.agencies.jma.points[0].valid_time = "2026-11-11T22:00:00Z"; }],
  ["tau_h repeated", data => { data.agencies.jma.points[1].tau_h = 12; }],
  ["tau_h zero", data => { data.agencies.jma.points[0].tau_h = 0; }],
  ["points not a list", data => { data.agencies.jma.points = {}; }],
  ["bad init_time", data => { data.agencies.jma.init_time = null; }],
  ["point longitude 180", data => { data.agencies.jma.points[0].lon = 180; }],
  ["point latitude missing", data => { delete data.agencies.jma.points[1].lat; }],
  ["a malformed probability circle", data => { data.agencies.jma.points[0].probability_circle = { radius: "85" }; }],
  ["a null item in point radii", data => { data.agencies.jma.points[0].radii = [null]; }],
])("forecast block with %s only fails that agency", (_, mutate) => {
  const data = cempakaForecast();
  mutate(data);
  const result = checkStormFile(data, "forecast", ID);
  expect(result.agencies.jma).toEqual({ status: "invalid" });
  expect(result.agencies.jtwc.status).toBe("ok");
  expect(result.agencies.cwa.status).toBe("ok");
});

test("an empty forecast (JMA final report) and a -180.0 point are valid", () => {
  const data = cempakaForecast();
  data.agencies.jma.points = [];
  expect(checkStormFile(data, "forecast", ID).agencies.jma.status).toBe("ok");
  expect(isValidPosition({ lat: 10.2, lon: -180.0 })).toBe(true);
  expect(isValidPosition({ lat: 10.2, lon: 180.0 })).toBe(false);
  expect(isValidPosition({ lat: 10.2, lon: Number.NaN })).toBe(false);
});
