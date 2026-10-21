// @vitest-environment node
import { afterEach, expect, test, vi } from "vitest";
import { fetchLatestImage } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

test.each(["/", "/weather-static/"])("SST reads static JSON under base %s", async (base) => {
  vi.stubEnv("BASE_URL", base);
  const payload = { image_type: "sst" };
  const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)));
  vi.stubGlobal("fetch", request);
  expect(await fetchLatestImage("sst")).toEqual(payload);
  expect(request).toHaveBeenCalledExactlyOnceWith(`${base}data/images/sst/latest.json`, { cache: "no-cache" });
});

test("missing SST JSON fails without falling back to Flask", async () => {
  const request = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
  vi.stubGlobal("fetch", request);
  await expect(fetchLatestImage("sst")).rejects.toThrow("sst");
  expect(request).toHaveBeenCalledExactlyOnceWith("/data/images/sst/latest.json", { cache: "no-cache" });
});

test("other products retain their API URL", async () => {
  const request = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", request);
  await fetchLatestImage("radar");
  expect(request).toHaveBeenCalledExactlyOnceWith("http://127.0.0.1:5174/api/images/latest?type=radar");
});
