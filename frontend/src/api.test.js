// @vitest-environment node
import { afterEach, expect, test, vi } from "vitest";
import { fetchLatestImage } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

test.each(["sst", "temperature", "weather_chart", "850hpa", "tchp"].flatMap(type =>
  ["/", "/weather-static/"].map(base => [type, base])
))("%s reads static JSON under base %s", async (type, base) => {
  vi.stubEnv("BASE_URL", base);
  const payload = { image_type: type };
  const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)));
  vi.stubGlobal("fetch", request);
  expect(await fetchLatestImage(type)).toEqual(payload);
  expect(request).toHaveBeenCalledExactlyOnceWith(`${base}data/images/${type}/latest.json`, { cache: "no-cache" });
});

test.each(["sst", "temperature", "weather_chart", "850hpa", "tchp"])("missing %s JSON fails without falling back to Flask", async (type) => {
  const request = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
  vi.stubGlobal("fetch", request);
  await expect(fetchLatestImage(type)).rejects.toThrow(type);
  expect(request).toHaveBeenCalledExactlyOnceWith(`/data/images/${type}/latest.json`, { cache: "no-cache" });
});

test("other products retain their API URL", async () => {
  const request = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", request);
  await fetchLatestImage("radar");
  expect(request).toHaveBeenCalledExactlyOnceWith("http://127.0.0.1:5174/api/images/latest?type=radar");
});
