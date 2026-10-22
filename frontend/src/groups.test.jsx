import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

const collections = {
  cimss_wind_analysis: [
    ["cimss_wind_shear", "Wind Shear"], ["cimss_850mb_vorticity", "850mb Vorticity"],
  ],
  cimss_steering_flow: [
    ["cimss_steering_flow_200_700mb", "200 - 700 mb"],
    ["cimss_steering_flow_250_850mb", "250 - 850 mb"],
    ["cimss_steering_flow_300_850mb", "300 - 850 mb"],
    ["cimss_steering_flow_400_850mb", "400 - 850 mb"],
    ["cimss_steering_flow_500_850mb", "500 - 850 mb"],
    ["cimss_steering_flow_700_850mb", "700 - 850 mb"],
  ],
  seaice_arctic: [["seaice_arctic_extent", "Sea Ice Extent"],
    ["seaice_arctic_concentration", "Sea Ice Concentration"], ["seaice_arctic_timeseries", "Time Series"]],
  seaice_antarctic: [["seaice_antarctic_extent", "Sea Ice Extent"],
    ["seaice_antarctic_concentration", "Sea Ice Concentration"], ["seaice_antarctic_timeseries", "Time Series"]],
};

// Use actual successful Fetcher outputs; never write simulated data into public.
const groups = Object.fromEntries(Object.keys(collections).map(type => [type,
  JSON.parse(readFileSync(resolve(`public/data/images/${type}/latest.json`), "utf8")),
]));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function serveGroups() {
  const request = vi.fn(async url => {
    const type = Object.keys(groups).find(type => url === `/data/images/${type}/latest.json`);
    if (!type) throw new Error("Outside group integration scope");
    return { ok: true, json: async () => groups[type] };
  });
  vi.stubGlobal("fetch", request);
  return request;
}

test("Dashboard shows each group's first UI child as its representative", async () => {
  serveGroups();
  render(<MemoryRouter><App /></MemoryRouter>);
  for (const [type, tabs] of Object.entries(collections)) {
    const group = groups[type];
    expect(group.images.map(child => child.image_type)).toEqual(tabs.map(([id]) => id));
    const first = group.images[0];
    expect(group.image_url).toBe(first.image_url);
    const image = await screen.findByAltText(group.title);
    expect(image.getAttribute("src")).toBe(first.image_url);
    expect(image.closest("a").getAttribute("href")).toBe(`/images/${type}`);
  }
});

test.each(Object.keys(collections))("%s existing route switches every child in UI order", async type => {
  const request = serveGroups();
  const group = groups[type];
  render(<MemoryRouter initialEntries={[`/images/${type}`]}><App /></MemoryRouter>);
  await screen.findByRole("tablist");
  const tabs = screen.getAllByRole("tab");
  expect(tabs.map(tab => tab.textContent)).toEqual(collections[type].map(([, label]) => label));
  expect(tabs[0].getAttribute("aria-selected")).toBe("true");
  for (const [index, [id]] of collections[type].entries()) {
    const child = group.images.find(child => child.image_type === id);
    fireEvent.click(tabs[index]);
    const image = within(screen.getByRole("tabpanel")).getByRole("img");
    expect(image.getAttribute("src")).toBe(child.image_url);
    expect(image.getAttribute("alt")).toBe(child.title);
    expect(tabs[index].getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText(child.image_time ? `Image Time: ${child.image_time}`
      : `Fetched At: ${child.fetched_at}`)).toBeTruthy();
  }
  expect(screen.getByRole("link", { name: "Original source" }).getAttribute("href")).toBe(group.source_url);
  expect(request).toHaveBeenCalledExactlyOnceWith(`/data/images/${type}/latest.json`, { cache: "no-cache" });
});
