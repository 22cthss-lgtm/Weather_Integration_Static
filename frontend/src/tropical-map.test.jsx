// Real Leaflet (not the stand-in used by tropical-detail.test.jsx) mounted, updated and unmounted in
// jsdom, with and without StrictMode. jsdom has no canvas, so getContext returns a no-op context.
// Guards the teardown: no redraw may run on a destroyed canvas, and only one map stays mounted.
import { StrictMode } from "react";
import { expect, test, vi } from "vitest";
import { act, render } from "@testing-library/react";
import TrackMap from "./pages/tropical/TrackMap";
import { buildTracks, defaultToggles, drawables } from "./tropical/tracks";
import { checkStormFile } from "./tropical/storm-files";
import { cempakaAnalysis, cempakaForecast } from "./tropical/storm-test-fixtures";

const ctx = new Proxy({}, { get: (t, k) => (k in t ? t[k] : () => ({})), set: (t, k, v) => { t[k] = v; return true; } });
HTMLCanvasElement.prototype.getContext = function () { return ctx; };

test("mount, update, unmount without stray redraw errors", async () => {
  const errors = [];
  const onError = event => { errors.push(String(event.error || event.message)); event.preventDefault(); };
  window.addEventListener("error", onError);
  const spy = vi.spyOn(console, "error").mockImplementation(message => errors.push(String(message)));
  const tracks = buildTracks(checkStormFile(cempakaAnalysis(), "analysis", "2026-jma-tc2638"),
    checkStormFile(cempakaForecast(), "forecast", "2026-jma-tc2638"));
  const items = drawables(tracks, defaultToggles());
  for (const strict of [false, true]) {
    const tree = <TrackMap items={items} colors={{ cwa: "#0f0", jma: "#00f", jtwc: "#f00" }} onSelectNode={() => {}} ready />;
    const view = render(strict ? <StrictMode>{tree}</StrictMode> : tree);
    await act(async () => { await new Promise(r => setTimeout(r, 50)); });
    expect(document.querySelectorAll(".leaflet-container")).toHaveLength(1);
    view.rerender(strict ? <StrictMode>{tree}</StrictMode> : tree);
    view.unmount();
    await act(async () => { await new Promise(r => setTimeout(r, 100)); });
  }
  window.removeEventListener("error", onError);
  spy.mockRestore();
  expect(errors).toEqual([]);
  expect(document.querySelectorAll(".leaflet-container")).toHaveLength(0);
});

test("model layers draw on the real map without errors and stay out of the first fit (11f F6)", async () => {
  const { default: L } = await import("leaflet");
  const { buildModelTracks, checkModelFile, enabledModelTracks } = await import("./tropical/models");
  const { penaModels06 } = await import("./tropical/model-test-fixtures");
  const errors = [];
  const onError = event => { errors.push(String(event.error || event.message)); event.preventDefault(); };
  window.addEventListener("error", onError);
  const spy = vi.spyOn(console, "error").mockImplementation(message => errors.push(String(message)));
  const fit = vi.spyOn(L.Map.prototype, "fitBounds");
  const tracks = buildTracks(checkStormFile(cempakaAnalysis(), "analysis", "2026-jma-tc2638"),
    checkStormFile(cempakaForecast(), "forecast", "2026-jma-tc2638"));
  const file = penaModels06();
  const models = buildModelTracks({ status: "ok", file: checkModelFile(file, "2026-jtwc-04c", file.cycle) });
  const shown = enabledModelTracks(models, { gfs: true, aigfs: true, ifs: false, aifs: false });
  const colors = { cwa: "#0f0", jma: "#00f", jtwc: "#f00", gfs: "#60f", aigfs: "#c06" };
  const officialItems = drawables(tracks, defaultToggles());
  const withModels = drawables(tracks, defaultToggles(), null, null, shown);
  const view = render(<TrackMap items={withModels} colors={colors} onSelectNode={() => {}} ready />);
  await act(async () => { await new Promise(r => setTimeout(r, 50)); });
  expect(fit).toHaveBeenCalledTimes(1);
  const fitted = fit.mock.calls[0][0];
  const officialPoints = officialItems.flatMap(item => (item.type === "line" ? item.latlngs : item.type === "node" ? [item.latlng] : []));
  const key = points => points.map(point => point.join(",")).sort();
  expect(key(fitted)).toEqual(key(officialPoints)); // the map orders items by type before drawing
  // PENA's model tracks cross 180: plotted longitudes run past 180 instead of wrapping.
  expect(withModels.some(item => item.type === "modelLine" && item.latlngs.some(([, lon]) => lon > 180))).toBe(true);
  view.rerender(<TrackMap items={officialItems} colors={colors} onSelectNode={() => {}} ready />);
  view.rerender(<TrackMap items={withModels} colors={colors} onSelectNode={() => {}} ready />);
  expect(fit).toHaveBeenCalledTimes(1);
  view.unmount();
  await act(async () => { await new Promise(r => setTimeout(r, 100)); });
  fit.mockRestore();
  window.removeEventListener("error", onError);
  spy.mockRestore();
  expect(errors).toEqual([]);
});
