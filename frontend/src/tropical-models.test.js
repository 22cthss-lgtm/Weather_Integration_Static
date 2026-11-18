import { afterEach, expect, test, vi } from "vitest";
import {
  MODELS, MODEL_STALE_THRESHOLD_MS, buildModelTracks, checkModelFile, checkModelsIndex, cycleTime,
  enabledModelTracks, fetchTropicalModelsFile, fetchTropicalModelsIndex, findModelNode, formatModelWind,
  isModelDataStale, modelEntry, stampOf,
} from "./tropical/models";
import { buildTimeline, buildTracks, defaultToggles, drawables, entriesAt } from "./tropical/tracks";
import { checkStormFile } from "./tropical/storm-files";
import { cempakaAnalysis, cempakaForecast } from "./tropical/storm-test-fixtures";
import { cempakaModels06, cempakaModels12, modelsIndex, penaModels06 } from "./tropical/model-test-fixtures";

const ID = "2026-jma-tc2638";
const PENA = "2026-jtwc-04c";
const HOUR = 3600 * 1000;

afterEach(() => { vi.unstubAllGlobals(); });

function okState(file, cycloneId = ID) {
  return { status: "ok", cycle: file.cycle, file: checkModelFile(file, cycloneId, file.cycle) };
}

test("cycleTime accepts only real YYYYMMDDHH cycles at 00/06/12/18", () => {
  expect(cycleTime("2026111106")).toBe(Date.parse("2026-11-11T06:00:00Z"));
  expect(cycleTime("2026123118")).toBe(Date.parse("2026-12-31T18:00:00Z"));
  for (const bad of ["2026111103", "2026023100", "2026111306x", "202611110", 2026111106, null, "2026-11-11"]) {
    expect(cycleTime(bad)).toBeNull();
  }
  expect(stampOf(Date.parse("2026-11-11T06:00:00Z") + 30 * HOUR)).toBe("2026-11-12T12:00:00Z");
});

test("the models index: only the file level decides 'could not read'", () => {
  expect(checkModelsIndex(modelsIndex())).not.toBeNull();
  for (const bad of [null, [], "x", { ...modelsIndex(), schema_version: 2 }, { ...modelsIndex(), storms: [] }]) {
    expect(checkModelsIndex(bad)).toBeNull();
  }
});

test("modelEntry: not listed and empty cycles (11e E16) are 'no model data'; the newest cycle is used", () => {
  expect(modelEntry(modelsIndex(), ID)).toEqual({ status: "none" });
  const bridged = modelsIndex({ [ID]: [] });
  bridged.storms[ID].bridge.jtwc = "31W";
  expect(modelEntry(bridged, ID)).toEqual({ status: "none" });
  const index = modelsIndex({ [ID]: [
    { cycle: "2026111100", models: ["gfs"] },
    { cycle: "2026111106", models: ["aigfs", "gfs", "zzz"] },
  ] });
  expect(modelEntry(index, ID)).toEqual({ status: "ok", cycle: "2026111106", models: ["aigfs", "gfs"] });
  expect(modelEntry(modelsIndex({ [ID]: [{ cycle: "2026111103", models: ["gfs"] }] }), ID)).toEqual({ status: "unavailable" });
  const broken = modelsIndex();
  broken.storms[ID] = { bridge: { jtwc: null }, cycles: "2026111106" };
  expect(modelEntry(broken, ID)).toEqual({ status: "unavailable" });
  // Inherited keys are not entries.
  expect(modelEntry(modelsIndex(), "constructor")).toEqual({ status: "none" });
});

test("checkModelFile: file-level mismatches are read failures", () => {
  const good = cempakaModels06();
  expect(checkModelFile(good, ID, "2026111106")).not.toBeNull();
  expect(checkModelFile(good, "2026-jma-tc9999", "2026111106")).toBeNull();
  expect(checkModelFile(good, ID, "2026111100")).toBeNull();
  expect(checkModelFile({ ...good, schema_version: 2 }, ID, "2026111106")).toBeNull();
  expect(checkModelFile({ ...good, init_time: "2026-11-11T00:00:00Z" }, ID, "2026111106")).toBeNull();
  expect(checkModelFile({ ...good, models: [] }, ID, "2026111106")).toBeNull();
  expect(checkModelFile(null, ID, "2026111106")).toBeNull();
});

test("checkModelFile: one bad model block affects that model only; absent models are 'missing'", () => {
  const file = cempakaModels06();
  file.models.gfs.track[2][0] = 7; // not a multiple of 6
  file.models.zzz = { provider: "X" }; // unknown keys are ignored
  const checked = checkModelFile(file, ID, "2026111106");
  expect(checked.models.gfs).toEqual({ status: "invalid" });
  expect(checked.models.aigfs.status).toBe("ok");
  expect(checked.models.ifs).toEqual({ status: "missing" });
  expect(checked.models.aifs).toEqual({ status: "missing" });
  expect(Object.keys(checked.models)).toEqual(MODELS);

  const cases = [
    block => { block.provider = "ECMWF"; },
    block => { block.wind_unit = "m/s"; },
    block => { block.track = []; },
    block => { block.track = Array.from({ length: 82 }, (_, i) => [i * 6, 20, 140, null, null]); },
    block => { block.track[0] = [0, 20, 140, null]; },
    block => { block.track[1][0] = block.track[0][0]; },
    block => { block.track[0][0] = -6; },
    block => { block.track[block.track.length - 1][0] = 486; },
    block => { block.track[0][1] = null; },
    block => { block.track[0][2] = 180; },
    block => { block.track[0][3] = "990"; },
    block => { block.track[0][4] = Number.NaN; },
    block => { block.track = null; },
  ];
  for (const change of cases) {
    const bad = cempakaModels06();
    change(bad.models.aigfs);
    expect(checkModelFile(bad, ID, "2026111106").models.aigfs).toEqual({ status: "invalid" });
  }
  const nulls = cempakaModels06();
  nulls.models.aigfs.track[0][3] = null;
  nulls.models.aigfs.track[0][4] = null;
  expect(checkModelFile(nulls, ID, "2026111106").models.aigfs.status).toBe("ok");
});

test("valid time is init_time + tau_h; the 180-degree crossing is unwrapped for plotting only", () => {
  const tracks = buildModelTracks(okState(penaModels06(), PENA));
  const gfs = tracks.find(track => track.model === "gfs");
  expect(gfs.points[0]).toMatchObject({ tauH: 0, time: "2026-11-11T06:00:00Z", initTime: "2026-11-11T06:00:00Z" });
  for (const point of gfs.points) {
    expect(Date.parse(point.time)).toBe(Date.parse("2026-11-11T06:00:00Z") + point.tauH * HOUR);
    expect(point.plotLon).toBe(point.lon < 0 ? point.lon + 360 : point.lon);
  }
  const plot = gfs.points.map(point => point.plotLon);
  expect(gfs.points.some(point => point.lon < 0) && gfs.points.some(point => point.lon > 0)).toBe(true);
  // Continuous on the map: no jump of more than a few degrees between consecutive points.
  for (let i = 1; i < plot.length; i += 1) expect(Math.abs(plot[i] - plot[i - 1])).toBeLessThan(10);
  expect(tracks.find(track => track.model === "ifs")).toMatchObject({ status: "missing", points: [] });
  expect(buildModelTracks({ status: "loading" })).toEqual([]);
  expect(buildModelTracks(null)).toEqual([]);
});

test("model wind keeps its unit and has no averaging period", () => {
  const ifs = buildModelTracks(okState(cempakaModels12())).find(track => track.model === "ifs");
  expect(ifs.points[0]).toMatchObject({ windUnit: "m/s", provider: "ECMWF" });
  expect(formatModelWind(29.8, "m/s")).toBe("模式 10 m 最大風 29.8 m/s（模式輸出，沒有平均期間）");
  expect(formatModelWind(null, "kt")).toBeNull();
});

test("freshness: only active storms, strictly more than 18 hours", () => {
  const init = "2026-11-11T06:00:00Z";
  const at = Date.parse(init) + MODEL_STALE_THRESHOLD_MS;
  expect(isModelDataStale({ status: "active" }, init, at)).toBe(false);
  expect(isModelDataStale({ status: "active" }, init, at + 1)).toBe(true);
  expect(isModelDataStale({ status: "ended" }, init, at + 1)).toBe(false);
  expect(isModelDataStale({ status: "active" }, init, null)).toBe(false);
  expect(isModelDataStale(null, init, at + 1)).toBe(false);
  // A clock behind the data is not stale.
  expect(isModelDataStale({ status: "active" }, init, Date.parse(init) - HOUR)).toBe(false);
});

test("timeline: only switched-on models add ticks (11e E3); the analysis step stays official", () => {
  const official = buildTracks(checkStorm(cempakaAnalysis(), "analysis"), checkStorm(cempakaForecast(), "forecast"));
  const models = buildModelTracks(okState(cempakaModels06()));
  const before = buildTimeline(official);
  const none = buildTimeline(official, enabledModelTracks(models, { gfs: false, aigfs: false, ifs: false, aifs: false }));
  expect(none).toEqual(before);
  const shown = enabledModelTracks(models, { gfs: true, aigfs: false, ifs: true, aifs: false });
  expect(shown.map(track => track.model)).toEqual(["gfs"]); // IFS has no points in this cycle
  const timeline = buildTimeline(official, shown);
  expect(timeline.analysis).toEqual(before.analysis);
  const gfsTimes = shown[0].points.map(point => point.time);
  const keys = timeline.ticks.map(tick => tick.key);
  for (const time of gfsTimes) expect(keys).toContain(time);
  expect(keys).toEqual([...keys].sort());
  const at = entriesAt(timeline, gfsTimes[1]);
  expect(at.find(entry => entry.model === "gfs")).toMatchObject({ agency: null, tauH: 6, initTime: "2026-11-11T06:00:00Z" });
  // No tick that only a switched-off model has.
  const aigfsOnly = models.find(track => track.model === "aigfs").points.map(point => point.time)
    .filter(time => !gfsTimes.includes(time) && !before.ticks.some(tick => tick.key === time));
  for (const time of aigfsOnly) expect(keys).not.toContain(time);
});

test("drawables: model items only for switched-on models, never mixed into the official items", () => {
  const official = buildTracks(checkStorm(cempakaAnalysis(), "analysis"), checkStorm(cempakaForecast(), "forecast"));
  const models = buildModelTracks(okState(cempakaModels06()));
  const base = drawables(official, defaultToggles());
  expect(drawables(official, defaultToggles(), null, null, [])).toEqual(base);
  const shown = enabledModelTracks(models, { gfs: true, aigfs: false, ifs: false, aifs: false });
  const nodeId = shown[0].points[1].id;
  const items = drawables(official, defaultToggles(), shown[0].points[1].time, nodeId, shown);
  expect(items.slice(0, base.length).map(item => item.type)).toEqual(base.map(item => item.type));
  const modelItems = items.filter(item => item.layer === "model");
  expect(modelItems.filter(item => item.type === "modelLine")).toHaveLength(1);
  expect(modelItems.filter(item => item.type === "modelNode")).toHaveLength(shown[0].points.length);
  expect(modelItems.every(item => item.model === "gfs" && item.agency === undefined)).toBe(true);
  expect(modelItems.find(item => item.nodeId === nodeId)).toMatchObject({ selected: true, highlighted: true });
  // The model line starts at its own tau 0, not at an official fix.
  expect(modelItems[0].latlngs[0]).toEqual([shown[0].points[0].lat, shown[0].points[0].plotLon]);
  // Official toggles do not hide models, and switching all agencies off leaves only model items.
  const off = defaultToggles();
  for (const agency of Object.keys(off.agencies)) off.agencies[agency] = false;
  expect(drawables(official, off, null, null, shown).every(item => item.layer === "model")).toBe(true);
  expect(findModelNode(shown, nodeId)).toBe(shown[0].points[1]);
  expect(findModelNode(shown, "jtwc:fix:0")).toBeNull();
});

test("model reads check the id and cycle before building a path", async () => {
  const request = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
  vi.stubGlobal("fetch", request);
  await expect(fetchTropicalModelsFile("../x", "2026111106")).rejects.toThrow();
  await expect(fetchTropicalModelsFile(ID, "2026111103")).rejects.toThrow();
  await expect(fetchTropicalModelsFile(ID, "../../index")).rejects.toThrow();
  expect(request).not.toHaveBeenCalled();
  await fetchTropicalModelsFile(ID, "2026111106");
  await fetchTropicalModelsIndex();
  expect(request.mock.calls.map(([url]) => url)).toEqual([
    `/data/tropical/models/storms/${ID}/2026111106.json`, "/data/tropical/models/index.json",
  ]);
  expect(request.mock.calls[0][1]).toMatchObject({ cache: "no-cache" });
});

// The official files go through the S7 check, as on the page.
function checkStorm(data, kind) {
  return checkStormFile(data, kind, ID);
}
