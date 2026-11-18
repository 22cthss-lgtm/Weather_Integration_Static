// @vitest-environment node
import { afterEach, expect, test, vi } from "vitest";
import {
  fetchDailyImages, fetchImageHistory, fetchLatestImage, fetchRainfallTop, fetchTropicalOfficialIndex, fetchTropicalStormFile,
} from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

test.each(["/", "/weather-static/"])("current-day history, daily rain and ranking respect base %s", async base => {
  vi.stubEnv("BASE_URL", base);
  const item = { image_type: "radar", image_time: "2026-10-22T00:00:00+08:00" };
  const request = vi.fn(async url => {
    if (url === `${base}data/images/radar/history/2026-10-22.json`) {
      return new Response(JSON.stringify({ image_type: "radar", date: "2026-10-22", items: [item] }));
    }
    if (url === `${base}data/images/rainfall/daily/latest.json`) {
      return new Response(JSON.stringify({ items: ["今日", "昨日", "前日"].map(label => ({ label })) }));
    }
    if (url === `${base}data/rainfall/rankings/latest.json`) {
      return new Response(JSON.stringify({ rankings: { "10min": { metric: "10min", items: [] } } }));
    }
    throw new Error("Unexpected URL");
  });
  vi.stubGlobal("fetch", request);
  expect(await fetchImageHistory("radar", { date: "2026-10-22" })).toEqual([item]);
  expect((await fetchDailyImages("rainfall")).map(p => p.label)).toEqual(["今日", "昨日", "前日"]);
  expect((await fetchRainfallTop("10min")).metric).toBe("10min");
  expect(request.mock.calls.every(([, options]) => options.cache === "no-cache")).toBe(true);
});

test.each(["sst", "temperature", "weather_chart", "850hpa", "tchp", "cimss_wind_analysis", "cimss_steering_flow", "seaice_arctic", "seaice_antarctic", "radar", "satellite", "rainfall"].flatMap(type =>
  ["/", "/weather-static/"].map(base => [type, base])
))("%s reads static JSON under base %s", async (type, base) => {
  vi.stubEnv("BASE_URL", base);
  const payload = { image_type: type };
  const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)));
  vi.stubGlobal("fetch", request);
  expect(await fetchLatestImage(type)).toEqual(payload);
  expect(request).toHaveBeenCalledExactlyOnceWith(`${base}data/images/${type}/latest.json`, { cache: "no-cache" });
});

test.each(["sst", "temperature", "weather_chart", "850hpa", "tchp", "cimss_wind_analysis", "cimss_steering_flow", "seaice_arctic", "seaice_antarctic", "radar", "satellite", "rainfall"])("missing %s JSON fails without falling back to Flask", async (type) => {
  const request = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
  vi.stubGlobal("fetch", request);
  await expect(fetchLatestImage(type)).rejects.toThrow(type);
  expect(request).toHaveBeenCalledExactlyOnceWith(`/data/images/${type}/latest.json`, { cache: "no-cache" });
});

test("other products retain their API URL", async () => {
  const request = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", request);
  await fetchLatestImage("unsupported_product");
  expect(request).toHaveBeenCalledExactlyOnceWith("http://127.0.0.1:5174/api/images/latest?type=unsupported_product");
});

test.each(["/", "/weather-static/"])("tropical index reads static JSON under base %s", async base => {
  vi.stubEnv("BASE_URL", base);
  const payload = { schema_version: 1 };
  const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)));
  vi.stubGlobal("fetch", request);
  const controller = new AbortController();
  expect(await fetchTropicalOfficialIndex({ signal: controller.signal })).toEqual(payload);
  expect(request).toHaveBeenCalledExactlyOnceWith(`${base}data/tropical/official/index.json`,
    { cache: "no-cache", signal: controller.signal });
});

test.each([
  ["404", () => Promise.resolve(new Response("", { status: 404 }))],
  ["network error", () => Promise.reject(new TypeError("Failed to fetch"))],
  ["broken JSON", () => Promise.resolve(new Response("{not json"))],
])("tropical index rejects on %s without falling back to Flask", async (_, response) => {
  const request = vi.fn(response);
  vi.stubGlobal("fetch", request);
  await expect(fetchTropicalOfficialIndex()).rejects.toThrow();
  expect(request).toHaveBeenCalledExactlyOnceWith("/data/tropical/official/index.json", { cache: "no-cache" });
});

test("tropical storm files are read only for checked ids and kinds", async () => {
  const request = vi.fn(async () => ({ ok: true, json: async () => ({ ok: 1 }) }));
  vi.stubGlobal("fetch", request);
  expect(await fetchTropicalStormFile("2026-jma-tc2638", "forecast")).toEqual({ ok: 1 });
  expect(request.mock.calls[0][0]).toMatch(/data\/tropical\/official\/storms\/2026-jma-tc2638\/forecast\.json$/);
  expect(request.mock.calls[0][1].cache).toBe("no-cache");
  for (const [id, kind] of [["../x", "analysis"], ["2026-jma-tc2638", "index"], ["2026-JMA-TC2638", "analysis"], [null, "analysis"]]) {
    await expect(fetchTropicalStormFile(id, kind)).rejects.toThrow();
  }
  expect(request).toHaveBeenCalledTimes(1);
});
