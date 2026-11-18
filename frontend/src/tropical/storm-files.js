// Shape checks for tropical/official/storms/{id}/(analysis|forecast).json (design.md 1.4, 1.5, 7.4).
// The file-level check decides "could not read"; each agency block is then checked on its own,
// so one bad block only affects that agency. The backend validator
// (fetchers/src/tropical_contract.py validate_storm_file) is stricter; this is the minimum the
// page relies on. Nothing here reads the clock.
import { AGENCIES, parseUtcStamp } from "./status";

const HOUR_MS = 3600 * 1000;
const MAX_TAU_H = 240;

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

/** Contract coordinates: lat -90..90, lon -180 (inclusive) .. 180 (exclusive). */
export function isValidPosition(point) {
  return isPlainObject(point) && finite(point.lat) && point.lat >= -90 && point.lat <= 90
    && finite(point.lon) && point.lon >= -180 && point.lon < 180;
}

function validRadii(radii) {
  if (!Array.isArray(radii)) return false;
  return radii.every(item => isPlainObject(item) && isPlainObject(item.threshold) && finite(item.threshold.value)
    && typeof item.threshold.unit === "string" && typeof item.unit === "string" && Array.isArray(item.sectors)
    && item.sectors.every(sector => isPlainObject(sector) && typeof sector.dir === "string"
      && (sector.radius === null || finite(sector.radius))));
}

function validCircle(circle) {
  return circle === undefined || circle === null
    || (isPlainObject(circle) && finite(circle.radius) && typeof circle.unit === "string");
}

function optionalStamp(value) {
  return value === null || parseUtcStamp(value) !== null;
}

function validAnalysisBlock(block) {
  if (!isPlainObject(block) || typeof block.final !== "boolean" || !optionalStamp(block.issued_at)) return false;
  const fix = block.fix;
  if (!isValidPosition(fix)) return false;
  const fixTime = parseUtcStamp(fix.analysis_time);
  if (fixTime === null || !validRadii(fix.radii)) return false;
  if (!Array.isArray(block.past_track)) return false;
  let previous = -Infinity;
  for (const point of block.past_track) {
    const time = isValidPosition(point) ? parseUtcStamp(point.analysis_time) : null;
    if (time === null || time <= previous || time >= fixTime) return false;
    previous = time;
  }
  return true;
}

function validForecastBlock(block) {
  if (!isPlainObject(block) || !optionalStamp(block.issued_at)) return false;
  const init = parseUtcStamp(block.init_time);
  if (init === null || !Array.isArray(block.points)) return false;
  let previous = 0;
  for (const point of block.points) {
    if (!isValidPosition(point)) return false;
    const tau = point.tau_h;
    if (!Number.isInteger(tau) || tau < 1 || tau > MAX_TAU_H || tau <= previous) return false;
    // The timeline uses valid_time only; it must agree with init_time + tau_h (design.md 1.5).
    if (parseUtcStamp(point.valid_time) !== init + tau * HOUR_MS) return false;
    if (point.radii !== undefined && point.radii !== null && !validRadii(point.radii)) return false;
    if (!validCircle(point.probability_circle)) return false;
    previous = tau;
  }
  return true;
}

/**
 * @returns null when the file cannot be used at all (treated as a read failure), otherwise
 *   { fetchedAt, agencies: { jtwc|jma|cwa: { status: "ok", block } | { status: "missing" } | { status: "invalid" } } }
 *   "missing" is a null block (no data from that agency); "invalid" is a block that fails the check.
 */
export function checkStormFile(data, kind, cycloneId) {
  if (!isPlainObject(data) || data.schema_version !== 1 || data.cyclone_id !== cycloneId) return null;
  if (!isPlainObject(data.agencies) || !AGENCIES.every(agency => agency in data.agencies)) return null;
  const valid = kind === "analysis" ? validAnalysisBlock : validForecastBlock;
  const agencies = {};
  for (const agency of AGENCIES) {
    const block = data.agencies[agency];
    if (block === null) agencies[agency] = { status: "missing" };
    else agencies[agency] = valid(block) ? { status: "ok", block } : { status: "invalid" };
  }
  return { fetchedAt: parseUtcStamp(data.fetched_at) === null ? null : data.fetched_at, agencies };
}
