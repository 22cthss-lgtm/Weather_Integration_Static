import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import App from "./App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); window.history.replaceState({}, "", "/"); });

test.each(["/", "/weather-test/"])("Hero, links and JSON use deployment base %s", async base => {
  vi.stubEnv("BASE_URL", base);
  window.history.replaceState({}, "", base);
  const request = vi.fn(async () => ({ ok: false }));
  vi.stubGlobal("fetch", request);
  const { container } = render(<BrowserRouter basename={base}><App /></BrowserRouter>);
  await screen.findAllByText("目前無有效資料，請稍後重新整理。");
  expect(container.querySelector('.dashboard-hero-image').getAttribute('src')).toBe(`${base}Hero_Section_Image.jpeg`);
  expect(screen.getByRole('link', { name: /Radar 目前/ }).getAttribute('href')).toBe(`${base}images/radar`);
  expect(request.mock.calls.every(([url]) => url.startsWith(`${base}data/images/`))).toBe(true);
  // The home page links to the tropical page but never reads its data.
  expect(screen.getByRole('link', { name: 'Tropical Cyclones' }).getAttribute('href')).toBe(`${base}tropical`);
  expect(screen.getByRole('link', { name: /熱帶系統專區/ }).getAttribute('href')).toBe(`${base}tropical`);
  expect(request.mock.calls.some(([url]) => url.includes('tropical'))).toBe(false);
});

test.each(["/", "/weather-test/"])("/tropical loads the lazy overview under base %s", async base => {
  vi.stubEnv("BASE_URL", base);
  window.history.replaceState({}, "", `${base}tropical?storm=bad`);
  const request = vi.fn(async () => ({ ok: false }));
  vi.stubGlobal("fetch", request);
  render(<BrowserRouter basename={base}><App /></BrowserRouter>);
  expect(await screen.findByText("熱帶系統資料暫時無法取得")).toBeTruthy();
  expect(screen.queryByText(/目前無活躍熱帶系統/)).toBeNull();
  expect(request).toHaveBeenCalledExactlyOnceWith(`${base}data/tropical/official/index.json`,
    expect.objectContaining({ cache: "no-cache" }));
});
