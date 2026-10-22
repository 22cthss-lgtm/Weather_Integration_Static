import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

const types = ["radar", "satellite", "rainfall"];
const products = Object.fromEntries(types.map(type => [type,
  JSON.parse(readFileSync(resolve(`public/data/images/${type}/latest.json`), "utf8"))]));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

function serveRealOutputs() {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(products.radar.fetched_at));
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
  serveRealOutputs();
  const product = products[type];
  const date = product.image_time.slice(0, 10);
  const history = JSON.parse(readFileSync(resolve(`public/data/images/${type}/history/${date}.json`), "utf8"));
  render(<MemoryRouter initialEntries={[`/images/${type}`]}><App /></MemoryRouter>);
  await screen.findByAltText(product.title);
  const options = await screen.findAllByRole("option");
  expect(options.map(option => option.value)).toEqual(history.items.map(item => item.image_time));
  expect(screen.getByRole("combobox").value).toBe(product.image_time);
});
