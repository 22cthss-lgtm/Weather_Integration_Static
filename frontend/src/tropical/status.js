// Display-state rules for the tropical overview (design.md 3.3, 3.4, 7.1).
// Every function is pure: "now" is always passed in, never read from the clock here.

// [初值] design.md 3.4: a required source not confirmed for longer than this is STALE.
export const STALE_THRESHOLD_MS = 3 * 60 * 60 * 1000;

export const AGENCIES = ["cwa", "jma", "jtwc"];
export const REQUIRED_AGENCIES = ["cwa", "jma"];
export const INDEX_STATUSES = ["OK_WITH_STORMS", "OK_NO_STORMS", "PARTIAL"];

// Mirrors fetchers/src/tropical_contract.py CYCLONE_ID; tab values from design.md 7.1.
export const CYCLONE_ID_PATTERN = /^[0-9]{4}-(?:jma|jtwc|cwa)-[a-z0-9]{1,8}$/;
export const TAB_PATTERN = /^(?:overview|forecast|analysis|imagery)$/;

const UTC_STAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Milliseconds for a contract timestamp (YYYY-MM-DDTHH:MM:SSZ), or null for anything else. */
export function parseUtcStamp(value) {
  if (typeof value !== "string" || !UTC_STAMP.test(value)) return null;
  const time = Date.parse(value);
  // Date.parse rolls invalid days over (e.g. 02-31); require an exact round trip.
  if (Number.isNaN(time) || new Date(time).toISOString().slice(0, 19) !== value.slice(0, 19)) return null;
  return time;
}

/**
 * Minimal shape check (design.md 7.4). Anything that fails is treated as "could not read"
 * (UNAVAILABLE), never as "no storms". Field-level nulls inside storms are tolerated and
 * handled by the renderer.
 */
export function isValidTropicalIndex(data) {
  if (!isPlainObject(data) || data.schema_version !== 1 || data.basin !== "WP") return false;
  if (!INDEX_STATUSES.includes(data.status) || parseUtcStamp(data.fetched_at) === null) return false;
  if (!isPlainObject(data.sources)) return false;
  for (const agency of AGENCIES) {
    const source = data.sources[agency];
    if (!isPlainObject(source) || !["ok", "failed"].includes(source.state)) return false;
    if (source.last_ok_at !== null && parseUtcStamp(source.last_ok_at) === null) return false;
  }
  if (!Array.isArray(data.storms)) return false;
  let anyActive = false;
  const seen = new Set();
  for (const storm of data.storms) {
    if (!isPlainObject(storm) || typeof storm.cyclone_id !== "string" || !storm.cyclone_id) return false;
    if (seen.has(storm.cyclone_id)) return false;
    seen.add(storm.cyclone_id);
    if (!["active", "ended"].includes(storm.status)) return false;
    if (storm.summary !== undefined && storm.summary !== null && !isPlainObject(storm.summary)) return false;
    if (storm.ids !== undefined && storm.ids !== null && !isPlainObject(storm.ids)) return false;
    anyActive = anyActive || storm.status === "active";
  }
  // A status that contradicts its own sources or storm list cannot be trusted either way;
  // in particular a failed required source must never be shown as "no storms".
  const states = Object.fromEntries(AGENCIES.map(agency => [agency, data.sources[agency].state]));
  return data.status === expectedIndexStatus(states, anyActive);
}

/** design.md 3.3 overall status, mirroring fetchers/src/tropical_contract.py expected_status. */
export function expectedIndexStatus(states, anyActive) {
  if (AGENCIES.every(agency => states[agency] === "failed")) return null; // backend never writes this
  if (REQUIRED_AGENCIES.some(agency => states[agency] === "failed")) return "PARTIAL";
  if (!anyActive) return "OK_NO_STORMS";
  return states.jtwc === "failed" ? "PARTIAL" : "OK_WITH_STORMS";
}

/** Required sources whose last confirmation is missing or older than the threshold. */
export function staleRequiredSources(index, nowMs, thresholdMs = STALE_THRESHOLD_MS) {
  return REQUIRED_AGENCIES.filter(agency => {
    const lastOk = parseUtcStamp(index.sources[agency].last_ok_at);
    if (lastOk === null) return true; // never confirmed: freshness cannot be shown
    return nowMs - lastOk > thresholdMs; // strictly greater; a future stamp is not stale
  });
}

/**
 * The state the overview shows (design.md 3.4).
 * @param index parsed index, or null when it could not be read or failed the shape check
 * @param nowMs the current time in milliseconds, injected by the caller
 */
export function deriveDisplayState(index, nowMs, thresholdMs = STALE_THRESHOLD_MS) {
  if (!index || !isValidTropicalIndex(index)) {
    return { state: "UNAVAILABLE", indexStatus: null, staleSources: [], hasActive: false };
  }
  const staleSources = staleRequiredSources(index, nowMs, thresholdMs);
  const hasActive = index.storms.some(storm => storm.status === "active");
  return {
    state: staleSources.length ? "STALE" : index.status,
    indexStatus: index.status,
    staleSources,
    hasActive,
  };
}

/** Validated query parameters; malformed values are ignored (design.md 7.1). */
export function parseTropicalQuery(searchParams) {
  const storm = searchParams.get("storm");
  const tab = searchParams.get("tab");
  return {
    storm: storm !== null && CYCLONE_ID_PATTERN.test(storm) ? storm : null,
    tab: tab !== null && TAB_PATTERN.test(tab) ? tab : "overview",
  };
}

function nameKey(name) {
  return typeof name === "string" ? name.toUpperCase().replace(/[^A-Z]/g, "") : "";
}

/**
 * cyclone_ids that share an international name and season with another listed storm.
 * Such storms are never merged automatically (design.md 2.3); the page shows a hint.
 */
export function sameNameStormIds(storms) {
  const groups = new Map();
  for (const storm of storms) {
    const key = nameKey(storm.name);
    if (!key) continue;
    const groupKey = `${storm.season}:${key}`;
    groups.set(groupKey, [...(groups.get(groupKey) || []), storm.cyclone_id]);
  }
  return new Set([...groups.values()].filter(ids => ids.length > 1).flat());
}
