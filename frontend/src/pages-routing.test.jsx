import React from "react";
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
});
