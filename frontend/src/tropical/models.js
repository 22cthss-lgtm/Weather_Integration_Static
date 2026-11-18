// Deterministic model tracks for the Forecast tab (design.md 1.6, 1.7, 7.4, 7.5, 7.7, 11e E3/E4/E16, 11f).
// Reading, the minimum shape checks the page relies on, freshness and the node model.
// The backend validator (fetchers/src/tropical_contract.py validate_models_index /
// validate_models_file) is stricter. Nothing here reads the clock.
import { readStatic } from "../api";
import { CYCLONE_ID_PATTERN } from "./status";
import { isValidPosition } from "./storm-files";
import { unwrapLon } from "./tracks";

const HOUR_MS = 3600 * 1000;
const MAX_TAU_H = 480;
const MAX_TRACK_POINTS = 81;

// [初值] design.md 1.6: an active storm whose newest cycle is older than this may be out of date.
export const MODEL_STALE_THRESHOLD_MS = 18 * HOUR_MS;

/** Display order; the data lists models alphabetically. */
export const MODELS = ["gfs", "aigfs", "ifs", "aifs"];

export const MODEL_INFO = {
  gfs: { short: "GFS", label: "GFS（NOAA）", provider: "NOAA", windUnit: "kt", color: "#6741d9" },
  aigfs: { short: "AIGFS", label: "AIGFS（NOAA，AI 模式）", provider: "NOAA", windUnit: "kt", color: "#c2255c" },
  ifs: { short: "IFS", label: "IFS（ECMWF）", provider: "ECMWF", windUnit: "m/s", color: "#0c8599" },
  aifs: { short: "AIFS", label: "AIFS（ECMWF，AI 模式）", provider: "ECMWF", windUnit: "m/s", color: "#495057" },
};

export const MODEL_COLORS = Object.fromEntries(MODELS.map(model => [model, MODEL_INFO[model].color]));

export const MODEL_LEGEND = "數值模式原始輸出，非官方預報，亦非本站預報。";

const CYCLE = /^[0-9]{8}(?:00|06|12|18)$/;

export const MODELS_INDEX_PATH = "data/tropical/models/index.json";
export const MODELS_INDEX_KEY = "models/index";

export function modelFileKey(cycloneId, cycle) {
  return `models/${cycloneId}/${cycle}`;
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

/** Milliseconds for a YYYYMMDDHH cycle (HH 00/06/12/18), or null. */
export function cycleTime(cycle) {
  if (typeof cycle !== "string" || !CYCLE.test(cycle)) return null;
  const year = Number(cycle.slice(0, 4));
  const month = Number(cycle.slice(4, 6));
  const day = Number(cycle.slice(6, 8));
  const hour = Number(cycle.slice(8, 10));
  const time = Date.UTC(year, month - 1, day, hour);
  const date = new Date(time);
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return time;
}

/** Contract stamp (YYYY-MM-DDTHH:MM:SSZ) for milliseconds. */
export function stampOf(time) {
  return `${new Date(time).toISOString().slice(0, 19)}Z`;
}

export function fetchTropicalModelsIndex({ signal } = {}) {
  return readStatic(MODELS_INDEX_PATH, { signal });
}

// The id and cycle are checked again here so a path can never be built from an unchecked value.
export function fetchTropicalModelsFile(cycloneId, cycle, { signal } = {}) {
  if (typeof cycloneId !== "string" || !CYCLONE_ID_PATTERN.test(cycloneId) || cycleTime(cycle) === null) {
    return Promise.reject(new Error("Invalid tropical models file request"));
  }
  return readStatic(`data/tropical/models/storms/${cycloneId}/${cycle}.json`, { signal });
}

/** File-level check of tropical/models/index.json; null means "could not read". */
export function checkModelsIndex(data) {
  if (!isPlainObject(data) || data.schema_version !== 1 || !isPlainObject(data.storms)) return null;
  return data;
}

/**
 * This storm's entry in a checked index (design.md 1.6, 11e E4/E16).
 * @returns {status: "none"} when there is no model data (not listed, or `cycles: []`),
 *   {status: "unavailable"} when the entry cannot be used, else {status: "ok", cycle, models}
 *   for the newest cycle.
 */
export function modelEntry(index, cycloneId) {
  if (!Object.prototype.hasOwnProperty.call(index.storms, cycloneId)) return { status: "none" };
  const entry = index.storms[cycloneId];
  if (!isPlainObject(entry) || !Array.isArray(entry.cycles)) return { status: "unavailable" };
  if (!entry.cycles.length) return { status: "none" };
  const latest = entry.cycles[entry.cycles.length - 1];
  if (!isPlainObject(latest) || cycleTime(latest.cycle) === null) return { status: "unavailable" };
  const models = Array.isArray(latest.models) ? latest.models.filter(model => MODELS.includes(model)) : [];
  return { status: "ok", cycle: latest.cycle, models };
}

function validTrack(track) {
  if (!Array.isArray(track) || track.length < 1 || track.length > MAX_TRACK_POINTS) return false;
  let previous = -1;
  for (const point of track) {
    if (!Array.isArray(point) || point.length !== 5) return false;
    const [tau, lat, lon, pressure, wind] = point;
    if (!Number.isInteger(tau) || tau < 0 || tau > MAX_TAU_H || tau % 6 !== 0 || tau <= previous) return false;
    if (!isValidPosition({ lat, lon })) return false;
    if (pressure !== null && !finite(pressure)) return false;
    if (wind !== null && !finite(wind)) return false;
    previous = tau;
  }
  return true;
}

function validModelBlock(model, block) {
  const info = MODEL_INFO[model];
  return isPlainObject(block) && block.provider === info.provider && block.wind_unit === info.windUnit
    && validTrack(block.track);
}

/**
 * Check of tropical/models/storms/{id}/{cycle}.json.
 * @returns null when the file cannot be used at all (a read failure), otherwise
 *   { cycle, initTime, models: { gfs|aigfs|ifs|aifs: {status: "ok", block} | {status: "missing"} | {status: "invalid"} } }
 *   "missing" is a model this cycle does not have; unknown model keys are ignored.
 */
export function checkModelFile(data, cycloneId, cycle) {
  if (!isPlainObject(data) || data.schema_version !== 1 || data.cyclone_id !== cycloneId || data.cycle !== cycle) {
    return null;
  }
  const init = cycleTime(cycle);
  if (init === null || data.init_time !== stampOf(init) || !isPlainObject(data.models)) return null;
  const models = {};
  for (const model of MODELS) {
    if (!Object.prototype.hasOwnProperty.call(data.models, model)) models[model] = { status: "missing" };
    else if (validModelBlock(model, data.models[model])) models[model] = { status: "ok", block: data.models[model] };
    else models[model] = { status: "invalid" };
  }
  return { cycle, initTime: data.init_time, models };
}

/** design.md 1.6, 11f F8: only active storms, strictly older than the threshold. */
export function isModelDataStale(storm, initTime, now) {
  if (!storm || storm.status !== "active") return false;
  const init = typeof initTime === "string" ? Date.parse(initTime) : NaN;
  if (!Number.isFinite(init) || !Number.isFinite(now)) return false;
  return now - init > MODEL_STALE_THRESHOLD_MS;
}

/**
 * One track per model for a usable state ({status: "ok", file}); empty otherwise.
 * Valid time = init_time + tau_h (computed here, never stored; design.md 1.7). No interpolation.
 */
export function buildModelTracks(state) {
  if (!state || state.status !== "ok") return [];
  const { file } = state;
  const init = Date.parse(file.initTime);
  return MODELS.map(model => {
    const entry = file.models[model];
    const info = MODEL_INFO[model];
    const points = entry.status === "ok" ? entry.block.track.map(([tau, lat, lon, pressure, wind], index) => ({
      id: `model:${model}:${index}`,
      model, kind: "model",
      time: stampOf(init + tau * HOUR_MS),
      tauH: tau,
      lat, lon, plotLon: unwrapLon(lon),
      pressure, wind,
      windUnit: info.windUnit,
      provider: info.provider,
      initTime: file.initTime,
    })) : [];
    return { model, status: entry.status, initTime: file.initTime, points };
  });
}

export function defaultModelToggles() {
  // Every model layer starts off; the official tracks are what the page shows first (design.md 7.7).
  return Object.fromEntries(MODELS.map(model => [model, false]));
}

/** Model tracks the viewer switched on and that have points. */
export function enabledModelTracks(modelTracks, toggles) {
  return modelTracks.filter(track => toggles[track.model] && track.points.length);
}

export function findModelNode(modelTracks, nodeId) {
  for (const track of modelTracks) {
    for (const point of track.points) if (point.id === nodeId) return point;
  }
  return null;
}

/** "模式 10 m 最大風 55 kt（模式輸出，沒有平均期間）"; null when the value is missing. */
export function formatModelWind(value, unit) {
  if (!finite(value)) return null;
  return `模式 10 m 最大風 ${value} ${unit}（模式輸出，沒有平均期間）`;
}
