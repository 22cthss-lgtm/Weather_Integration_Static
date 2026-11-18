import { afterEach, expect, test, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TropicalPage from "./pages/TropicalPage";
import { NOW, makeIndex } from "./tropical/test-fixtures";
import { cempakaAnalysis, cempakaForecast } from "./tropical/storm-test-fixtures";

// VITE_TROPICAL_MODEL_LAYERS=off (design.md 7.7, 11f F1).
vi.mock("./tropical/features", () => ({ MODEL_LAYERS_ENABLED: false }));
vi.mock("./pages/tropical/TrackMap", () => ({
  default: ({ items }) => <div data-testid="map" data-items={JSON.stringify(items)} />,
}));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const ID = "2026-jma-tc2638";

test("with the build switch off there is no model section, request or attribution line", async () => {
  const routes = {
    "/data/tropical/official/index.json": makeIndex(),
    [`/data/tropical/official/storms/${ID}/analysis.json`]: cempakaAnalysis(),
    [`/data/tropical/official/storms/${ID}/forecast.json`]: cempakaForecast(),
  };
  const request = vi.fn(async url => (url in routes
    ? { ok: true, json: async () => routes[url] }
    : { ok: false, status: 404, json: async () => ({}) }));
  vi.stubGlobal("fetch", request);
  render(<MemoryRouter initialEntries={[`/tropical?storm=${ID}&tab=forecast`]}><TropicalPage getNow={() => NOW} /></MemoryRouter>);
  await screen.findByTestId("map");
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(request.mock.calls.map(([url]) => url).filter(url => url.includes("/models/"))).toEqual([]);
  expect(screen.queryByRole("group", { name: "數值模式路徑（原始輸出）" })).toBeNull();
  expect(document.body.textContent).not.toMatch(/數值模式|NOAA|ECMWF/);
  expect(JSON.parse(screen.getByTestId("map").getAttribute("data-items")).length).toBeGreaterThan(0);
});
