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
