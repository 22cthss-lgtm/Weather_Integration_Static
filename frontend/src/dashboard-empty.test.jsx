import React from "react";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

test("a stalled JSON request ends loading after 15 seconds", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  render(<MemoryRouter><DashboardPage /></MemoryRouter>);
  expect(screen.getAllByText("Loading...")).toHaveLength(12);
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
  expect(screen.getAllByText("目前無有效資料，請稍後重新整理。")).toHaveLength(12);
  expect(screen.queryByText("Loading...")).toBeNull();
  expect(fetch.mock.calls.every(([, options]) => options.signal.aborted)).toBe(true);
});

test.each([null, {}, { image_url: "javascript:bad", title: "Invalid" }])(
  "Dashboard ends loading with clear no-data feedback (%s)", async payload => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      if (payload === null) throw new Error("offline");
      return { ok: true, json: async () => payload };
    }));
    render(<MemoryRouter><DashboardPage /></MemoryRouter>);
    await screen.findAllByText("目前無有效資料，請稍後重新整理。");
    expect(screen.queryByText("Loading...")).toBeNull();
  }
);

test("one missing card does not hide successful cards or navigation", async () => {
  vi.stubGlobal("fetch", vi.fn(async url => {
    if (!url.includes("/radar/")) throw new Error("missing");
    return { ok: true, json: async () => ({ image_type: "radar", title: "Radar ready",
      image_url: "https://example.com/radar.png", image_time: "2026-10-27T10:00:00+08:00" }) };
  }));
  render(<MemoryRouter><DashboardPage /></MemoryRouter>);
  const image = await screen.findByAltText("Radar ready");
  expect(within(image.closest("a")).getByText("Image Time: 2026/10/27 10:00")).toBeTruthy();
  expect(image.closest("a").getAttribute("href")).toBe("/images/radar");
  await screen.findAllByText("目前無有效資料，請稍後重新整理。");
  const scroll = vi.fn();
  vi.stubGlobal("scrollTo", scroll);
  fireEvent.click(screen.getByRole("button", { name: "Back to top" }));
  expect(scroll).toHaveBeenCalledWith({ top: 0, behavior: "smooth" });
});
