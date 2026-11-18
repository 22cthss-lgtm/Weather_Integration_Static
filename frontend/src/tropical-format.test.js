import { expect, test } from "vitest";
import {
  formatDualTime, formatGust, formatMovement, formatNote, formatProbabilityCircle, formatRadii, formatTau,
} from "./tropical/format";
import { buildTimeline, buildTracks } from "./tropical/tracks";
import { checkStormFile } from "./tropical/storm-files";
import { cempakaAnalysis, cempakaForecast } from "./tropical/storm-test-fixtures";

test("movement keeps each agency's own form and units", () => {
  expect(formatMovement({ direction_deg: 70, direction_text: null, speed_kt: 33, speed_kmh: null })).toBe("70°，33 kt");
  expect(formatMovement({ direction_deg: null, direction_text: "ENE", speed_kt: 27, speed_kmh: 50 })).toBe("ENE，27 kt／50 km/h");
  expect(formatMovement({ direction_deg: null, direction_text: "STNR", speed_kt: null, speed_kmh: null })).toBe("幾乎停滯");
  expect(formatMovement({ direction_deg: null, direction_text: "VAR", speed_kt: null, speed_kmh: 10 })).toBe("方向不定，10 km/h");
  expect(formatMovement(null)).toBeNull();
  expect(formatMovement({ direction_deg: null, direction_text: null, speed_kt: null, speed_kmh: null })).toBeNull();
});

test("gust, radii, circles, notes and lead times are labelled without conversion", () => {
  expect(formatGust({ kt: 85, ms: 45 })).toBe("85 kt／45 m/s");
  expect(formatGust({ kt: null, ms: 38 })).toBe("38 m/s");
  expect(formatGust(null)).toBeNull();
  expect(formatRadii({ threshold: { value: 30, unit: "kt" }, unit: "nm", sectors: [{ dir: "ALL", radius: 150 }] }))
    .toBe("30 kt 風圈（半徑 nm）：全域 150");
  expect(formatRadii({ threshold: { value: 34, unit: "kt" }, unit: "nm", sectors: [{ dir: "NE", radius: null }] }))
    .toBe("34 kt 風圈（半徑 nm）：東北 未提供");
  expect(formatProbabilityCircle("jma", { radius: 85, unit: "km", probability_pct: 70 })).toBe("預報圓（中心進入機率 70%）：85 km");
  expect(formatProbabilityCircle("cwa", { radius: 40, unit: "km", probability_pct: 70 })).toBe("70% 機率半徑：40 km");
  expect(formatProbabilityCircle("cwa", null)).toBeNull();
  expect(formatNote("POST_TROPICAL")).toBe("轉為後熱帶系統（POST_TROPICAL）");
  expect(formatNote("SOMETHING")).toBeNull();
  expect(formatNote(null)).toBeNull();
  expect(formatTau(120)).toBe("+120 小時");
  expect(formatTau(null)).toBeNull();
});

test("dual times across month end, year end and Taiwan midnight", () => {
  expect(formatDualTime("2026-11-30T18:00:00Z")).toEqual({ utc: "2026-11-30 18:00 UTC", taipei: "2026-12-01 02:00" });
  expect(formatDualTime("2026-12-31T15:00:00Z")).toEqual({ utc: "2026-12-31 15:00 UTC", taipei: "2026-12-31 23:00" });
  expect(formatDualTime("2026-12-31T16:00:00Z")).toEqual({ utc: "2026-12-31 16:00 UTC", taipei: "2027-01-01 00:00" });
  expect(formatDualTime("2027-01-01T00:00:00Z")).toEqual({ utc: "2027-01-01 00:00 UTC", taipei: "2027-01-01 08:00" });
});

test("a forecast running into the new year keeps its real valid times in order", () => {
  const forecast = cempakaForecast();
  const init = Date.parse("2026-12-31T12:00:00Z");
  const stamp = ms => new Date(ms).toISOString().slice(0, 19) + "Z";
  forecast.agencies.jtwc = null;
  forecast.agencies.cwa = null;
  forecast.agencies.jma.init_time = stamp(init);
  forecast.agencies.jma.points = [3, 4, 12, 36].map(tau => ({ ...cempakaForecast().agencies.jma.points[0],
    tau_h: tau, valid_time: stamp(init + tau * 3600e3) }));
  const tracks = buildTracks(checkStormFile(cempakaAnalysis(), "analysis", "2026-jma-tc2638"),
    checkStormFile(forecast, "forecast", "2026-jma-tc2638"));
  expect(buildTimeline(tracks).ticks.map(tick => [tick.key, formatDualTime(tick.key).taipei])).toEqual([
    ["2026-12-31T15:00:00Z", "2026-12-31 23:00"],
    ["2026-12-31T16:00:00Z", "2027-01-01 00:00"],
    ["2027-01-01T00:00:00Z", "2027-01-01 08:00"],
    ["2027-01-02T00:00:00Z", "2027-01-02 08:00"],
  ]);
});
