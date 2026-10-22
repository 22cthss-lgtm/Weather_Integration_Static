import React from "react";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

function image(type, time = "2026-10-22T01:00:00+08:00") {
  return { image_type: type, source: "CWA", title: `${type} ${time}`,
    image_url: `https://example.com/${type}/${time}.png`, source_url: "https://www.cwa.gov.tw/",
    image_time: time, fetched_at: "2026-10-21T17:05:00+00:00" };
}

function serve(type, { yesterday = false, historyFails = false } = {}) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-22T01:05:00+08:00"));
  const latest = image(type, yesterday ? "2026-10-21T23:50:00+08:00" : undefined);
  const first = image(type, `2026-10-22T${type === "rainfall" ? "00:30" : "00:00"}:00+08:00`);
  const items = [first, latest];
  const request = vi.fn(async url => {
    let payload;
    if (url === `/data/images/${type}/latest.json`) payload = latest;
    else if (url === `/data/images/${type}/history/2026-10-22.json`) {
      if (historyFails) return { ok: false, json: async () => ({}) };
      payload = { image_type: type, date: "2026-10-22", items, complete: false, missing: ["gap"], failed: [] };
    } else if (url === "/data/images/rainfall/daily/latest.json") {
      payload = { date: "2026-10-22", items: ["今日", "昨日", "前日"].map((label, index) => ({
        ...image("rainfall_daily"), label, represented_date: `2026-10-${22 - index}`,
      })) };
    } else if (url === "/data/rainfall/rankings/latest.json") {
      payload = { fetched_at: latest.fetched_at, rankings: Object.fromEntries(
        ["10min", "1hr", "3hr", "6hr", "12hr", "24hr", "1day", "2days"].map(metric => [metric,
          { metric, fetched_at: latest.fetched_at, items: [{ rank: 1, station_id: "A", station_name: `Station ${metric}`,
            county: "Taipei", town: "Town", rainfall: 1, observed_at: "2026-10-21T17:00:00+00:00" }] }])) };
    } else throw new Error(`Unexpected request: ${url}`);
    return { ok: true, json: async () => payload };
  });
  vi.stubGlobal("fetch", request);
  return { latest, first, request };
}

test.each(["radar", "satellite", "rainfall"])("%s opens latest, switches current-day slots and has no backfill", async type => {
  const { latest, first, request } = serve(type);
  render(<MemoryRouter initialEntries={[`/images/${type}`]}><App /></MemoryRouter>);
  await screen.findByAltText(latest.title);
  expect(screen.queryByRole("button", { name: /backfill/i })).toBeNull();
  const select = screen.getByRole("combobox");
  expect(select.value).toBe(latest.image_time);
  expect(within(select).getAllByRole("option")).toHaveLength(2);
  fireEvent.change(select, { target: { value: first.image_time } });
  expect(screen.getByAltText(first.title).getAttribute("src")).toBe(first.image_url);
  expect(request.mock.calls.every(([url]) => !url.includes("/api/"))).toBe(true);
});

test("previous-day latest is labelled and never offered as today's history", async () => {
  const { latest, request } = serve("radar", { yesterday: true });
  render(<MemoryRouter initialEntries={["/images/radar"]}><App /></MemoryRouter>);
  await screen.findByAltText(latest.title);
  expect(screen.getByText(/當日資料尚未取得/)).toBeTruthy();
  expect(screen.getByRole("combobox").disabled).toBe(true);
  expect(request.mock.calls.some(([url]) => url.includes("/history/"))).toBe(false);
});

test("history fetch failure preserves latest image and reports the panel error", async () => {
  const { latest } = serve("satellite", { historyFails: true });
  render(<MemoryRouter initialEntries={["/images/satellite"]}><App /></MemoryRouter>);
  await screen.findByAltText(latest.title);
  expect(await screen.findByText(/時次資料讀取失敗/)).toBeTruthy();
});

test("official rainfall daily dates and all original eight ranking tabs remain usable", async () => {
  serve("rainfall");
  render(<MemoryRouter initialEntries={["/images/rainfall"]}><App /></MemoryRouter>);
  await screen.findByAltText("今日 2026-10-22");
  expect(screen.getByAltText("昨日 2026-10-21")).toBeTruthy();
  expect(screen.getByAltText("前日 2026-10-20")).toBeTruthy();
  const metrics = ["10min", "1hr", "3hr", "6hr", "12hr", "24hr", "1day", "2days"];
  const tabs = screen.getAllByRole("tab");
  expect(tabs).toHaveLength(8);
  for (let i = 0; i < tabs.length; i++) {
    fireEvent.click(tabs[i]);
    expect(await screen.findByText(`Station ${metrics[i]}`)).toBeTruthy();
    expect(screen.getByText("2026-10-22 01:00")).toBeTruthy();
  }
});

test("failed official image has an explicit message instead of a different time", async () => {
  const { latest } = serve("radar");
  render(<MemoryRouter initialEntries={["/images/radar"]}><App /></MemoryRouter>);
  const img = await screen.findByAltText(latest.title);
  fireEvent.error(img);
  expect(screen.getByText(/此時次的官方圖片目前無法取得/)).toBeTruthy();
  expect(screen.queryByAltText(latest.title)).toBeNull();
});

test("rainfall daily images and ranking still render if latest image metadata fails", async () => {
  const { request } = serve("rainfall");
  vi.stubGlobal("fetch", async url => url === "/data/images/rainfall/latest.json"
    ? { ok: false, json: async () => ({}) } : request(url));
  render(<MemoryRouter initialEntries={["/images/rainfall"]}><App /></MemoryRouter>);
  expect(await screen.findByAltText("昨日 2026-10-21")).toBeTruthy();
  expect(await screen.findByText("Station 10min")).toBeTruthy();
});
