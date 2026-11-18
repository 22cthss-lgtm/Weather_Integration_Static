// Display formatting for tropical data. Data times are UTC (design.md 1.2); the page shows
// both UTC and Taiwan time (design.md 7.5). Nothing here reads the clock.
import { parseUtcStamp } from "./status";

export const AGENCY_LABELS = {
  cwa: "CWA 中央氣象署",
  jma: "JMA 日本氣象廳",
  jtwc: "JTWC 聯合颱風警報中心",
};

export const AGENCY_SHORT = { cwa: "CWA", jma: "JMA", jtwc: "JTWC" };

const ERROR_LABELS = {
  source_error: "來源錯誤",
  timeout: "逾時",
  http_error: "HTTP 錯誤",
  parse_error: "解析失敗",
  validation_error: "資料驗證失敗",
  write_error: "寫入失敗",
  network_error: "網路錯誤",
};

const taipeiParts = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

function pad(value) {
  return String(value).padStart(2, "0");
}

/** { utc: "2026-11-11 06:00 UTC", taipei: "2026-11-11 14:00" } or null for a bad stamp. */
export function formatDualTime(stamp) {
  const time = parseUtcStamp(stamp);
  if (time === null) return null;
  const date = new Date(time);
  const utc = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} `
    + `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
  const parts = taipeiParts.formatToParts(date);
  const get = type => parts.find(part => part.type === type).value;
  const taipei = `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
  return { utc, taipei };
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

// Hemisphere letters are decided after rounding to the shown 0.1°, so 0.04 shows "0.0°"
// and ±179.96 shows "180.0°", the same as the exact values.
function rounded(value) {
  return Math.round(Math.abs(value) * 10) / 10;
}

export function formatLatitude(lat) {
  if (!finite(lat)) return null;
  const value = rounded(lat);
  if (value === 0) return "0.0°";
  return `${value.toFixed(1)}°${lat > 0 ? "N" : "S"}`;
}

/** Contract longitudes are -180..180 with west negative; show east/west, not signs. */
export function formatLongitude(lon) {
  if (!finite(lon)) return null;
  const value = rounded(lon);
  if (value === 0 || value === 180) return `${value.toFixed(1)}°`;
  return `${value.toFixed(1)}°${lon > 0 ? "E" : "W"}`;
}

export function formatPosition(lat, lon) {
  const latitude = formatLatitude(lat);
  const longitude = formatLongitude(lon);
  return latitude && longitude ? `${latitude} ${longitude}` : null;
}

/**
 * Only the units the agency gave, with the agency and averaging period attached
 * (design.md 1.2, 7.5). No unit or averaging conversion is made.
 */
export function formatWind(agency, maxWind) {
  if (!maxWind || typeof maxWind !== "object") return null;
  const values = [];
  if (finite(maxWind.kt)) values.push(`${maxWind.kt} kt`);
  if (finite(maxWind.ms)) values.push(`${maxWind.ms} m/s`);
  if (!values.length) return null;
  const period = Number.isInteger(maxWind.averaging_min) ? `${maxWind.averaging_min} 分鐘平均` : "平均期間不明";
  return `${values.join("／")}（${AGENCY_SHORT[agency]}，${period}）`;
}

export function formatPressure(value) {
  return finite(value) ? `${value} hPa` : null;
}

/** A string to show, or null for null / non-string / blank values. */
export function textOrNull(value) {
  return typeof value === "string" && value.trim() ? value : null;
}

export function formatErrorCode(code) {
  if (typeof code !== "string") return "失敗";
  return ERROR_LABELS[code] ? `${ERROR_LABELS[code]}（${code}）` : "失敗";
}

/** Agency identifiers in a fixed order, skipping unknown ones. */
export function formatIds(ids) {
  if (!ids || typeof ids !== "object") return [];
  const parts = [];
  const value = key => textOrNull(ids[key]);
  if (value("jtwc")) parts.push(`JTWC ${value("jtwc")}`);
  if (value("jma_tc")) parts.push(`JMA ${value("jma_tc")}`);
  if (value("jma_number")) parts.push(`JMA 編號 ${value("jma_number")}`);
  if (value("cwa_ty")) parts.push(`CWA 第 ${value("cwa_ty")} 號颱風`);
  if (value("cwa_td")) parts.push(`CWA 熱帶性低氣壓 TD ${value("cwa_td")}`);
  return parts;
}

const DIRECTION_WORDS = { STNR: "幾乎停滯", VAR: "方向不定" };

/** Movement in the forms the agency gave (design.md 1.4); nothing is converted. */
export function formatMovement(movement) {
  if (!movement || typeof movement !== "object") return null;
  const parts = [];
  if (Number.isInteger(movement.direction_deg)) parts.push(`${movement.direction_deg}°`);
  const text = textOrNull(movement.direction_text);
  if (text) parts.push(DIRECTION_WORDS[text] || text);
  const speeds = [];
  if (finite(movement.speed_kt)) speeds.push(`${movement.speed_kt} kt`);
  if (finite(movement.speed_kmh)) speeds.push(`${movement.speed_kmh} km/h`);
  if (speeds.length) parts.push(speeds.join("／"));
  return parts.length ? parts.join("，") : null;
}

/** Gust in the units the agency gave; no averaging period is attached because none is given. */
export function formatGust(gust) {
  if (!gust || typeof gust !== "object") return null;
  const values = [];
  if (finite(gust.kt)) values.push(`${gust.kt} kt`);
  if (finite(gust.ms)) values.push(`${gust.ms} m/s`);
  return values.length ? values.join("／") : null;
}

const SECTOR_LABELS = { NE: "東北", SE: "東南", SW: "西南", NW: "西北", N: "北", E: "東", S: "南", W: "西", ALL: "全域" };

/** "34 kt 風圈（半徑 nm）：東北 130、東南 95…"; a null radius is shown as "未提供". */
export function formatRadii(radii) {
  if (!radii || !radii.threshold || !Array.isArray(radii.sectors)) return null;
  const threshold = `${radii.threshold.value} ${radii.threshold.unit}`;
  const sectors = radii.sectors.map(sector => {
    const label = SECTOR_LABELS[sector.dir] || sector.dir;
    return `${label} ${finite(sector.radius) ? sector.radius : "未提供"}`;
  });
  return `${threshold} 風圈（半徑 ${radii.unit}）：${sectors.join("、")}`;
}

/** JMA forecast circle / CWA 70% radius: an agency probability circle, not a wind area. */
export function formatProbabilityCircle(agency, circle) {
  if (!circle || !finite(circle.radius) || typeof circle.unit !== "string") return null;
  const pct = Number.isInteger(circle.probability_pct) ? `${circle.probability_pct}%` : "";
  const name = agency === "jma" ? `預報圓（中心進入機率 ${pct}）` : `${pct} 機率半徑`;
  return `${name}：${circle.radius} ${circle.unit}`;
}

const NOTE_LABELS = {
  DISSIPATING: "減弱消散中",
  DISSIPATED: "已消散",
  EXTRATROPICAL: "變性為溫帶氣旋",
  POST_TROPICAL: "轉為後熱帶系統",
};

export function formatNote(note) {
  return NOTE_LABELS[note] ? `${NOTE_LABELS[note]}（${note}）` : null;
}

export function formatTau(tauH) {
  return Number.isInteger(tauH) ? `+${tauH} 小時` : null;
}
