// Test-only index builders, shaped after fetchers/tests/tropical_testing.py valid_index()
// and no_storm_index(). Not imported by application code.

export const NOW = Date.parse("2026-11-11T10:40:00Z");

export function source(state = "ok", lastOk = "2026-11-11T10:33:00Z", extra = {}) {
  return {
    required: true, state, error_code: state === "ok" ? null : "http_error",
    last_ok_at: lastOk, active_count: state === "ok" ? 1 : null, ...extra,
  };
}

export function cempaka(overrides = {}) {
  return {
    cyclone_id: "2026-jma-tc2638", status: "active", season: 2026, name: "CEMPAKA",
    name_zh: "查帕卡", origin_basin: "WP",
    ids: { jtwc: "31W", jma_tc: "TC2638", jma_number: "2632", cwa_ty: "31", cwa_td: "35" },
    match: { jtwc: "name", jma: "origin", cwa: "name" },
    last_fix_time: "2026-11-11T09:00:00Z", ended_at: null,
    summary: {
      jtwc: { analysis_time: "2026-11-11T06:00:00Z", active: true, lat: 29.1, lon: 150.2,
        category: "TYPHOON", max_wind: { kt: 65, ms: null, averaging_min: 1 }, pressure_hpa: 983 },
      jma: { analysis_time: "2026-11-11T09:00:00Z", active: true, lat: 29.2, lon: 151.0,
        category: "STS", max_wind: { kt: 60, ms: 30, averaging_min: 10 }, pressure_hpa: 985 },
      cwa: { analysis_time: "2026-11-11T06:00:00Z", active: true, lat: 28.9, lon: 149.9,
        category: null, max_wind: { kt: null, ms: 30, averaging_min: 10 }, pressure_hpa: 975 },
    },
    ...overrides,
  };
}

export function endedStorm(overrides = {}) {
  return cempaka({
    cyclone_id: "2026-jma-tc2637", name: "PENA", name_zh: "白娜", status: "ended",
    ids: { jtwc: "30W", jma_tc: "TC2637", jma_number: "2631", cwa_ty: null, cwa_td: null },
    match: { jtwc: null, jma: "origin", cwa: null }, ended_at: "2026-11-10T12:00:00Z",
    last_fix_time: "2026-11-10T06:00:00Z",
    summary: {
      jtwc: null, cwa: null,
      jma: { analysis_time: "2026-11-10T06:00:00Z", active: false, lat: 35.0, lon: 160.0,
        category: "LOW", max_wind: { kt: 35, ms: 18, averaging_min: 10 }, pressure_hpa: 996 },
    },
    ...overrides,
  });
}

export function makeIndex({ status = "OK_WITH_STORMS", storms = [cempaka()], cwa, jma, jtwc } = {}) {
  return {
    schema_version: 1, basin: "WP", status, fetched_at: "2026-11-11T10:33:07Z",
    sources: {
      cwa: cwa || source(),
      jma: jma || source(),
      jtwc: jtwc || { ...source(), required: false },
    },
    storms,
  };
}
