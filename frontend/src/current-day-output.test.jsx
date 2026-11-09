import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { taipeiDate } from "./useCurrentImage";

const types = ["radar", "satellite", "rainfall"];
const products = Object.fromEntries(types.map(type => [type,
  JSON.parse(readFileSync(resolve(`public/data/images/${type}/latest.json`), "utf8"))]));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

function serveRealOutputs(clock = products.radar.fetched_at) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(clock));
  const request = vi.fn(async url => {
    if (!url.startsWith("/data/") || url.includes("..")) throw new Error("Only published JSON is supported");
    const data = JSON.parse(readFileSync(resolve(`public${url}`), "utf8"));
    return { ok: true, json: async () => data };
  });
  vi.stubGlobal("fetch", request);
  return request;
}

test("Dashboard renders all three actual CWA latest outputs", async () => {
  const request = serveRealOutputs();
  render(<MemoryRouter><App /></MemoryRouter>);
  for (const type of types) {
    const image = await screen.findByAltText(products[type].title);
    expect(image.getAttribute("src")).toBe(products[type].image_url);
    expect(image.closest("a").getAttribute("href")).toBe(`/images/${type}`);
  }
  expect(request.mock.calls.every(([url]) => !url.includes("/api/"))).toBe(true);
});

test.each(types)("%s detail reads actual current-day Fetcher output", async type => {
  const product = products[type];
  // Resources can legitimately retain data from different days after partial
  // source failures. Test this product's same-day inventory independently.
  serveRealOutputs(product.image_time);
  const date = product.image_time.slice(0, 10);
  const history = JSON.parse(readFileSync(resolve(`public/data/images/${type}/history/${date}.json`), "utf8"));
  render(<MemoryRouter initialEntries={[`/images/${type}`]}><App /></MemoryRouter>);
  await screen.findByAltText(product.title);
  const options = await screen.findAllByRole("option");
  // The page always offers the latest successful image as a slot, even when the
  // day's history file has not caught up yet. Shortly after Taipei midnight the
  // previous day's file is no longer extended while its 23:xx latest is still
  // published, so the history items alone are not the expected option list.
  const expected = [...new Set([
    ...history.items.map(item => item.image_time).filter(time => taipeiDate(time) === date),
    product.image_time,
  ])].sort();
  expect(options.map(option => option.value)).toEqual(expected);
  expect(screen.getByRole("combobox").value).toBe(product.image_time);
});

test("latest published after the day's history stopped still appears as the newest slot", async () => {
  // Reproduces Pages chain runs #161-164 and #302-304: just after Taipei midnight the
  // 23:30 latest image exists but that day's history file stops at 23:00.
  const latest = { ...products.radar, image_time: "2026-11-07T23:30:00+08:00" };
  const items = ["2026-11-07T22:30:00+08:00", "2026-11-07T23:00:00+08:00"]
    .map(image_time => ({ ...products.radar, image_time }));
  const files = {
    "/data/images/radar/latest.json": latest,
    "/data/images/radar/history/2026-11-07.json": {
      image_type: "radar", date: "2026-11-07", items, complete: true,
      range_end: "2026-11-07T23:00:00+08:00",
    },
  };
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(latest.image_time));
  vi.stubGlobal("fetch", vi.fn(async url => {
    if (!(url in files)) throw new Error(`unexpected ${url}`);
    return { ok: true, json: async () => files[url] };
  }));
  render(<MemoryRouter initialEntries={["/images/radar"]}><App /></MemoryRouter>);
  await screen.findByAltText(latest.title);
  const options = await screen.findAllByRole("option");
  expect(options.map(option => option.value)).toEqual([...items.map(item => item.image_time), latest.image_time]);
  expect(screen.getByRole("combobox").value).toBe(latest.image_time);
  await screen.findByText(/歷史清單尚未涵蓋最新圖/);
});

test.each(types)("%s retained output stays visible without yesterday's time options", async type => {
  const product = products[type];
  const nextDay = new Date(new Date(product.image_time).getTime() + 24 * 60 * 60 * 1000);
  const request = serveRealOutputs(nextDay);
  render(<MemoryRouter initialEntries={[`/images/${type}`]}><App /></MemoryRouter>);
  const image = await screen.findByAltText(product.title);
  expect(image.getAttribute("src")).toBe(product.image_url);
  await screen.findByText(/當日資料尚未取得/);
  expect(screen.getByRole("combobox").disabled).toBe(true);
  expect(screen.queryAllByRole("option")).toHaveLength(0);
  expect(request.mock.calls.some(([url]) => url.startsWith(`/data/images/${type}/history/`))).toBe(false);
});
