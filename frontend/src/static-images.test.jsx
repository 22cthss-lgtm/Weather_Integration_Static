import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import ImagePage from "./pages/ImagePage";

const types = ["temperature", "weather_chart", "850hpa", "tchp"];
// Real outputs are deliberately required: a successful live update precedes this suite.
const products = Object.fromEntries(types.map(type => [type,
  JSON.parse(readFileSync(resolve(`public/data/images/${type}/latest.json`), "utf8"))
]));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function serveProducts() {
  const request = vi.fn(async url => {
    const type = types.find(type => url === `/data/images/${type}/latest.json`);
    if (!type) throw new Error("Outside static image integration scope");
    return { ok: true, json: async () => products[type] };
  });
  vi.stubGlobal("fetch", request);
  return request;
}

test("Dashboard renders all four real resources", async () => {
  const request = serveProducts();
  render(<MemoryRouter><DashboardPage /></MemoryRouter>);
  for (const type of types) {
    const product = products[type];
    const image = await screen.findByAltText(product.title);
    expect(image.getAttribute("src")).toBe(product.image_url);
    const card = image.closest("a");
    expect(card.getAttribute("href")).toBe(`/images/${type}`);
    expect(within(card).getByText(product.image_time
      ? `Image Time: ${product.image_time}` : `Fetched At: ${product.fetched_at}`)).toBeTruthy();
    expect(request.mock.calls.some(([url]) => url.includes(`type=${type}`))).toBe(false);
  }
});

test.each(types)("%s detail preserves image, source and time contract", async type => {
  const request = serveProducts();
  const product = products[type];
  render(
    <MemoryRouter initialEntries={[`/images/${type}`]}>
      <Routes><Route path="/images/:type" element={<ImagePage />} /></Routes>
    </MemoryRouter>
  );
  const image = await screen.findByAltText(product.title);
  expect(image.getAttribute("src")).toBe(product.image_url);
  expect(screen.getByRole("link", { name: "Image Original source" }).getAttribute("href")).toBe(product.source_url);
  if (product.image_time) {
    expect(screen.getByText(`Image Time: ${product.image_time}`)).toBeTruthy();
  } else {
    const local = new Date(product.fetched_at).toLocaleString("sv-SE", {
      timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
    expect(screen.getByText(`Fetched At: ${local}`)).toBeTruthy();
  }
  expect(request).toHaveBeenCalledExactlyOnceWith(`/data/images/${type}/latest.json`, { cache: "no-cache" });
});
