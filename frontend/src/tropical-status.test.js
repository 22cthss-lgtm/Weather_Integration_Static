// @vitest-environment node
import { expect, test } from "vitest";
import {
  STALE_THRESHOLD_MS, deriveDisplayState, isValidTropicalIndex, parseTropicalQuery, parseUtcStamp,
  sameNameStormIds,
} from "./tropical/status";
import {
  formatDualTime, formatErrorCode, formatIds, formatLatitude, formatLongitude, formatPosition,
  formatPressure, formatWind, textOrNull,
} from "./tropical/format";
import { NOW, cempaka, endedStorm, makeIndex, source } from "./tropical/test-fixtures";

const HOUR = 60 * 60 * 1000;

test("threshold is a named three-hour constant", () => {
  expect(STALE_THRESHOLD_MS).toBe(3 * HOUR);
});

test.each([
  ["OK_WITH_STORMS", makeIndex()],
  ["OK_NO_STORMS", makeIndex({ status: "OK_NO_STORMS", storms: [] })],
  ["PARTIAL", makeIndex({ status: "PARTIAL", storms: [], jma: source("failed") })],
])("fresh index keeps its own status %s", (expected, index) => {
  expect(deriveDisplayState(index, NOW).state).toBe(expected);
});

test.each([null, undefined, "text", [], {}, { ...makeIndex(), schema_version: 2 },
  { ...makeIndex(), status: "UNAVAILABLE" }, { ...makeIndex(), status: "STALE" },
  { ...makeIndex(), basin: "EP" }, { ...makeIndex(), storms: null },
  { ...makeIndex(), storms: [null] }, { ...makeIndex(), storms: [{ status: "active" }] },
  { ...makeIndex(), sources: { cwa: source(), jma: source() } },
  { ...makeIndex(), fetched_at: "2026-11-11T10:33:07+00:00" },
  makeIndex({ cwa: source("ok", "2026-11-11 10:33") }),
  makeIndex({ cwa: source("unknown") }),
  makeIndex({ storms: [cempaka({ status: "dissipated" })] }),
  makeIndex({ status: "OK_NO_STORMS" }), // claims no storms while listing an active one
  makeIndex({ status: "OK_WITH_STORMS", storms: [endedStorm()] }),
  // Status contradicting the source states (design 3.3): never trusted as "no storms".
  makeIndex({ status: "OK_NO_STORMS", storms: [], cwa: source("failed") }),
  makeIndex({ status: "OK_NO_STORMS", storms: [endedStorm()], jma: source("failed") }),
  makeIndex({ status: "OK_WITH_STORMS", jtwc: { ...source("failed"), required: false } }),
  makeIndex({ status: "PARTIAL" }), // all sources ok
  makeIndex({ status: "PARTIAL", storms: [], cwa: source("failed"), jma: source("failed"),
    jtwc: { ...source("failed"), required: false } }), // backend never writes all-failed
  makeIndex({ storms: [cempaka(), cempaka()] }), // duplicate cyclone_id
])("unreadable or unexpected index is UNAVAILABLE, never a no-storm state (%#)", index => {
  const display = deriveDisplayState(index, NOW);
  expect(display.state).toBe("UNAVAILABLE");
  expect(isValidTropicalIndex(index)).toBe(false);
});

test("STALE threshold: exactly three hours is fresh, one second more is stale", () => {
  const last = Date.parse("2026-11-11T10:33:00Z");
  const index = makeIndex({ status: "OK_NO_STORMS", storms: [] });
  expect(deriveDisplayState(index, last + 3 * HOUR).state).toBe("OK_NO_STORMS");
  expect(deriveDisplayState(index, last + 3 * HOUR + 1000).state).toBe("STALE");
  expect(deriveDisplayState(index, last + 3 * HOUR + 1000).indexStatus).toBe("OK_NO_STORMS");
});

test("STALE looks only at required sources and takes priority over PARTIAL", () => {
  const oldJtwc = makeIndex({ status: "PARTIAL",
    jtwc: { ...source("failed", "2026-11-01T00:00:00Z"), required: false } });
  expect(deriveDisplayState(oldJtwc, NOW).state).toBe("PARTIAL");
  const partial = makeIndex({ status: "PARTIAL", storms: [], jma: source("failed", "2026-11-11T06:00:00Z") });
  const display = deriveDisplayState(partial, NOW);
  expect(display).toMatchObject({ state: "STALE", indexStatus: "PARTIAL", staleSources: ["jma"] });
});

test("a required source that never succeeded is STALE; a future stamp is not", () => {
  const never = makeIndex({ status: "PARTIAL", storms: [], cwa: source("failed", null) });
  expect(deriveDisplayState(never, NOW).staleSources).toEqual(["cwa"]);
  const future = makeIndex({ cwa: source("ok", "2026-11-11T12:00:00Z") });
  expect(deriveDisplayState(future, NOW).state).toBe("OK_WITH_STORMS");
});

test("status derivation does not depend on the machine clock", () => {
  const index = makeIndex();
  expect(deriveDisplayState(index, Date.parse("2030-01-01T00:00:00Z")).state).toBe("STALE");
  expect(deriveDisplayState(index, NOW).state).toBe("OK_WITH_STORMS");
});

test("timestamps only accept the contract form", () => {
  expect(parseUtcStamp("2026-11-11T10:33:00Z")).toBe(Date.parse("2026-11-11T10:33:00Z"));
  for (const bad of ["2026-02-31T00:00:00Z", "2026-11-11T10:33Z", "2026-11-11T10:33:00.000Z", null, 0]) {
    expect(parseUtcStamp(bad)).toBeNull();
  }
});

test("query parameters are checked with regular expressions before use", () => {
  const parse = text => parseTropicalQuery(new URLSearchParams(text));
  expect(parse("storm=2026-jma-tc2638&tab=forecast")).toEqual({ storm: "2026-jma-tc2638", tab: "forecast" });
  expect(parse("")).toEqual({ storm: null, tab: "overview" });
  for (const bad of ["2026-JMA-TC2638", "2026-ecmwf-x", "../x", "2026-jma-tc2638%0A", "2026-jma-",
    "2026-jma-abcdefghi", "<script>", " 2026-jma-tc2638"]) {
    expect(parse(`storm=${encodeURIComponent(bad)}`).storm).toBeNull();
  }
  expect(parse("tab=Forecast").tab).toBe("overview");
  expect(parse("tab=map").tab).toBe("overview");
});

test("same-name storms in the same season are flagged; unnamed ones are not", () => {
  const storms = [
    cempaka(), cempaka({ cyclone_id: "2026-jtwc-31w", name: "Cempaka" }),
    cempaka({ cyclone_id: "2025-jma-tc2501", season: 2025 }),
    cempaka({ cyclone_id: "2026-cwa-35", name: null }), cempaka({ cyclone_id: "2026-jtwc-32w", name: null }),
  ];
  expect([...sameNameStormIds(storms)].sort()).toEqual(["2026-jma-tc2638", "2026-jtwc-31w"]);
});

test("times show UTC and Taiwan time across midnight and the new year", () => {
  expect(formatDualTime("2026-11-11T15:59:00Z")).toEqual({ utc: "2026-11-11 15:59 UTC", taipei: "2026-11-11 23:59" });
  expect(formatDualTime("2026-11-11T16:00:00Z")).toEqual({ utc: "2026-11-11 16:00 UTC", taipei: "2026-11-12 00:00" });
  expect(formatDualTime("2026-12-31T15:30:00Z")).toEqual({ utc: "2026-12-31 15:30 UTC", taipei: "2026-12-31 23:30" });
  expect(formatDualTime("2026-12-31T18:00:00Z")).toEqual({ utc: "2026-12-31 18:00 UTC", taipei: "2027-01-01 02:00" });
  expect(formatDualTime(null)).toBeNull();
  expect(formatDualTime("bad")).toBeNull();
});

test("positions use N/S and E/W, never signed numbers", () => {
  expect(formatPosition(29.1, 150.2)).toBe("29.1°N 150.2°E");
  expect(formatPosition(-12.5, -171.3)).toBe("12.5°S 171.3°W");
  expect(formatLongitude(-180)).toBe("180.0°");
  expect(formatLongitude(179.5)).toBe("179.5°E");
  expect(formatLongitude(-179.5)).toBe("179.5°W");
  expect(formatLatitude(0)).toBe("0.0°");
  // Hemisphere decided after rounding to the shown precision.
  expect(formatLongitude(179.96)).toBe("180.0°");
  expect(formatLongitude(-179.96)).toBe("180.0°");
  expect(formatLongitude(0.04)).toBe("0.0°");
  expect(formatLatitude(-0.04)).toBe("0.0°");
  expect(formatLongitude(-0.06)).toBe("0.1°W");
  expect(formatPosition(null, 150)).toBeNull();
  expect(formatPosition(20, Number.NaN)).toBeNull();
});

test("wind shows only the agency's own units with agency and averaging period", () => {
  expect(formatWind("jtwc", { kt: 65, ms: null, averaging_min: 1 })).toBe("65 kt（JTWC，1 分鐘平均）");
  expect(formatWind("jma", { kt: 60, ms: 30, averaging_min: 10 })).toBe("60 kt／30 m/s（JMA，10 分鐘平均）");
  expect(formatWind("cwa", { kt: null, ms: 30, averaging_min: 10 })).toBe("30 m/s（CWA，10 分鐘平均）");
  expect(formatWind("cwa", null)).toBeNull();
  expect(formatWind("cwa", { kt: null, ms: null, averaging_min: 10 })).toBeNull();
  expect(formatWind("jtwc", { kt: 65, ms: null, averaging_min: null })).toBe("65 kt（JTWC，平均期間不明）");
});

test("null-safe helpers never produce the text null", () => {
  expect(formatPressure(null)).toBeNull();
  expect(textOrNull(null)).toBeNull();
  expect(textOrNull("  ")).toBeNull();
  expect(formatIds(null)).toEqual([]);
  expect(formatIds({ jtwc: null, jma_tc: "TC2638", jma_number: null, cwa_ty: null, cwa_td: "35" }))
    .toEqual(["JMA TC2638", "CWA 熱帶性低氣壓 TD 35"]);
  expect(formatErrorCode("http_error")).toBe("HTTP 錯誤（http_error）");
  expect(formatErrorCode("<b>")).toBe("失敗");
  expect(formatErrorCode(null)).toBe("失敗");
});

test("OK_NO_STORMS with only ended storms and PARTIAL with JTWC failed are consistent indexes", () => {
  expect(isValidTropicalIndex(makeIndex({ status: "OK_NO_STORMS", storms: [endedStorm()],
    jtwc: { ...source("failed"), required: false } }))).toBe(true);
  expect(isValidTropicalIndex(makeIndex({ status: "PARTIAL",
    jtwc: { ...source("failed"), required: false } }))).toBe(true);
});
