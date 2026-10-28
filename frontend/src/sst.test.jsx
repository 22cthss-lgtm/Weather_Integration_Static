import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import ImagePage from "./pages/ImagePage";
import { formatImageTime } from "./image-time";

// Integration fixture is the actual Fetcher output, never a replacement dataset.
const sst = JSON.parse(readFileSync(resolve("public/data/images/sst/latest.json"), "utf8"));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function serveRealSst() {
  const request = vi.fn(async (url) => {
    if (url !== "/data/images/sst/latest.json") {
      throw new Error("Other products are outside this SST integration test");
    }
    return { ok: true, json: async () => sst };
  });
  vi.stubGlobal("fetch", request);
  return request;
}

test("Dashboard SST card renders actual Fetcher metadata without inventing midnight", async () => {
  const request = serveRealSst();
  render(<MemoryRouter><DashboardPage /></MemoryRouter>);
  const image = await screen.findByAltText(sst.title);
  expect(image.getAttribute("src")).toBe(sst.image_url);
  const card = image.closest("a");
  expect(card.getAttribute("href")).toBe("/images/sst");
  expect(within(card).getByText(`Image Time: ${formatImageTime(sst.image_time)}`)).toBeTruthy();
  expect(request.mock.calls.filter(([url]) => url.includes("type=sst"))).toHaveLength(0);
});

test("SST detail uses the same static JSON, source link and product date", async () => {
  const request = serveRealSst();
  render(
    <MemoryRouter initialEntries={["/images/sst"]}>
      <Routes><Route path="/images/:type" element={<ImagePage />} /></Routes>
    </MemoryRouter>,
  );
  const image = await screen.findByAltText(sst.title);
  expect(image.getAttribute("src")).toBe(sst.image_url);
  expect(screen.getByText(`Image Time: ${sst.image_time}`)).toBeTruthy();
  expect(screen.getByRole("link", { name: "Image Original source" }).getAttribute("href")).toBe(sst.source_url);
  expect(request).toHaveBeenCalledExactlyOnceWith("/data/images/sst/latest.json", { cache: "no-cache" });
});
