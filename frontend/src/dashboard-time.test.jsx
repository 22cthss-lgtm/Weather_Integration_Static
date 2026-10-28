import React from "react";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test.each([
  ["2026-10-27T01:05:42Z", "Image Time: 2026/10/27 09:05"],
  [null, "Fetched At: 2026/10/28 00:15"],
])("Dashboard formats image and fallback times in Taipei (%s)", async (imageTime, expected) => {
  vi.stubGlobal("fetch", vi.fn(async url => {
    if (url !== "/data/images/radar/latest.json") throw new Error("Outside test scope");
    return { ok: true, json: async () => ({
      title: "Radar", image_url: "https://example.com/radar.png",
      image_time: imageTime, fetched_at: "2026-10-27T16:15:59Z",
    }) };
  }));
  render(<MemoryRouter><DashboardPage /></MemoryRouter>);
  expect(await screen.findByText(expected)).toBeTruthy();
});
