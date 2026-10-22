// @vitest-environment node
import { afterEach, expect, test, vi } from "vitest";
import { fetchDailyImages, fetchImageHistory, fetchLatestImage, fetchRainfallTop } from "./api";

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
