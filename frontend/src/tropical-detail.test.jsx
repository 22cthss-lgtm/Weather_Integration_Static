import { afterEach, expect, test, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TropicalPage from "./pages/TropicalPage";
import { NOW, cempaka, endedStorm, makeIndex } from "./tropical/test-fixtures";
import { cempakaAnalysis, cempakaForecast, penaAnalysis, penaForecast } from "./tropical/storm-test-fixtures";

// The real map needs a canvas and is checked in the browser; here a stand-in exposes what the
// panel asks it to draw and lets a test "click" a node.
vi.mock("./pages/tropical/TrackMap", () => ({
  default: ({ items, onSelectNode, ready }) => (
    <div data-testid="map" data-items={JSON.stringify(items)} data-ready={String(ready)}>
      {items.filter(item => item.type === "node").map(item => (
        <button key={item.nodeId} type="button" onClick={() => onSelectNode(item.nodeId)}>node {item.nodeId}</button>
      ))}
    </div>
  ),
}));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

const ID = "2026-jma-tc2638";
const INDEX_URL = "/data/tropical/official/index.json";
const fileUrl = (id, kind) => `/data/tropical/official/storms/${id}/${kind}.json`;

function serve(routes) {
  const request = vi.fn(async url => {
    if (!(url in routes)) return { ok: false, status: 404, json: async () => ({}) };
    const route = routes[url];
    if (route instanceof Error) throw route;
    return { ok: true, json: async () => (typeof route === "function" ? route() : route) };
  });
  vi.stubGlobal("fetch", request);
  return request;
}

const MISSING = Symbol("missing");

function cempakaRoutes({ index = makeIndex(), analysis = cempakaAnalysis(), forecast = cempakaForecast() } = {}) {
  const routes = { [INDEX_URL]: index };
  if (analysis !== MISSING) routes[fileUrl(ID, "analysis")] = analysis;
  if (forecast !== MISSING) routes[fileUrl(ID, "forecast")] = forecast;
  return routes;
}

async function renderAt(url) {
  const view = render(<MemoryRouter initialEntries={[url]}><TropicalPage getNow={() => NOW} /></MemoryRouter>);
  await screen.findByRole("heading", { name: /資料來源與署名/ });
  return view;
}

async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
}

function requested(request) {
  return request.mock.calls.map(([url]) => url);
}

function text() {
  return document.body.textContent;
}

function expectNoRawValues() {
  expect(text()).not.toMatch(/\bnull\b|undefined|NaN/);
}

async function openForecast(routes = cempakaRoutes()) {
  const request = serve(routes);
  await renderAt(`/tropical?storm=${ID}&tab=forecast`);
  await screen.findByTestId("map");
  await settle();
  return request;
}

function mapItems() {
  return JSON.parse(screen.getByTestId("map").getAttribute("data-items"));
}

test("the overview never reads storm files and links each card to its storm page", async () => {
  const request = serve(cempakaRoutes());
  await renderAt("/tropical");
  await settle();
  expect(requested(request)).toEqual([INDEX_URL]);
  const card = screen.getByRole("article", { name: "CEMPAKA" });
  const links = within(card).getAllByRole("link");
  expect(links.every(link => link.getAttribute("href") === `/tropical?storm=${ID}`)).toBe(true);
  fireEvent.click(links[0]);
  await screen.findByRole("navigation", { name: "系統資料分頁" });
  await settle();
  expect(requested(request)).toEqual([INDEX_URL, fileUrl(ID, "analysis"), fileUrl(ID, "forecast")]);
});

test("the storm page opens on the overview tab with movement from analysis.json", async () => {
  serve(cempakaRoutes());
  await renderAt(`/tropical?storm=${ID}`);
  await settle();
  const tab = screen.getByRole("link", { name: "總覽" });
  expect(tab.getAttribute("aria-current")).toBe("page");
  const jma = screen.getByRole("region", { name: "JMA 日本氣象廳" });
  expect(within(jma).getByText("ENE，27 kt／50 km/h")).toBeTruthy();
  expect(within(jma).getByText("60 kt／30 m/s（JMA，10 分鐘平均）")).toBeTruthy();
  expect(screen.getByRole("link", { name: "← 回到總覽" }).getAttribute("href")).toBe("/tropical");
  expectNoRawValues();
});

test.each([["evil"], ["Forecast"], [""]])("an unknown tab %s falls back to the overview", async tab => {
  serve(cempakaRoutes());
  await renderAt(`/tropical?storm=${ID}&tab=${tab}`);
  expect(screen.getByRole("link", { name: "總覽" }).getAttribute("aria-current")).toBe("page");
});

test("the imagery tab says it is not open yet", async () => {
  serve(cempakaRoutes());
  await renderAt(`/tropical?storm=${ID}&tab=imagery`);
  expect(screen.getByText("圖像分頁尚未開放。")).toBeTruthy();
});

test("analysis lists every agency in its own units, averaging, radii and past-track origin", async () => {
  serve(cempakaRoutes());
  await renderAt(`/tropical?storm=${ID}&tab=analysis`);
  await settle();
  const jtwc = screen.getByRole("region", { name: "JTWC 聯合颱風警報中心" });
  expect(within(jtwc).getByText("65 kt（JTWC，1 分鐘平均）")).toBeTruthy();
  expect(within(jtwc).getByText("80 kt")).toBeTruthy();
  expect(within(jtwc).getByText("70°，33 kt")).toBeTruthy();
  expect(within(jtwc).getByText("34 kt 風圈（半徑 nm）：東北 100、東南 105、西南 95、西北 70")).toBeTruthy();
  expect(within(jtwc).getByText("021")).toBeTruthy();
  expect(within(jtwc).getByText(/本站累積：僅含本站開始觀察後的紀錄/)).toBeTruthy();
  expect(within(jtwc).getByText("TYPHOON")).toBeTruthy();
  const cwa = screen.getByRole("region", { name: "CWA 中央氣象署" });
  expect(within(cwa).getByText("30 m/s（CWA，10 分鐘平均）")).toBeTruthy();
  expect(within(cwa).getByText("15 m/s 風圈（半徑 km）：東北 180、東南 120、西南 120、西北 160")).toBeTruthy();
  expect(within(cwa).getByText(/2 點（機構提供的過去路徑）/)).toBeTruthy();
  // CWA category is null: the row is not shown at all.
  expect(within(cwa).queryByText("機構分類（原文）")).toBeNull();
  // No converted or cross-agency value appears.
  expect(within(cwa).queryByText(/kt/)).toBeNull();
  expect(within(jtwc).queryByText(/m\/s/)).toBeNull();
  expect(text()).not.toMatch(/最強|最弱|平均值/);
  expectNoRawValues();
});

test("a final report and an older detail file are marked", async () => {
  const analysis = cempakaAnalysis();
  analysis.agencies.jma.final = true;
  const index = makeIndex({ storms: [cempaka()] });
  index.storms[0].summary.jma.analysis_time = "2026-11-11T12:00:00Z";
  index.storms[0].last_fix_time = "2026-11-11T12:00:00Z";
  serve(cempakaRoutes({ index, analysis }));
  await renderAt(`/tropical?storm=${ID}&tab=analysis`);
  await settle();
  const jma = screen.getByRole("region", { name: "JMA 日本氣象廳" });
  expect(within(jma).getByText("機構已發布最終報")).toBeTruthy();
  expect(within(jma).getByText(/詳細資料的分析時間與索引不同/)).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "CWA 中央氣象署" })).queryByText(/索引不同/)).toBeNull();
});

test.each([
  ["404", { analysis: MISSING, forecast: MISSING }],
  ["a network error", { analysis: new Error("offline"), forecast: new Error("offline") }],
  ["bad JSON shape", { analysis: () => "not json", forecast: { schema_version: 2 } }],
  ["another storm's file", {
    analysis: { ...cempakaAnalysis(), cyclone_id: "2026-jma-tc2637" },
    forecast: { ...cempakaForecast(), cyclone_id: "2026-jma-tc2637" },
  }],
])("storm files that fail with %s leave the page usable", async (_, files) => {
  serve(cempakaRoutes(files));
  await renderAt(`/tropical?storm=${ID}&tab=analysis`);
  await settle();
  expect(screen.getByText("各機構的詳細分析資料暫時無法取得。")).toBeTruthy();
  expect(screen.getAllByText("此資料暫時無法取得。")).toHaveLength(3);
  fireEvent.click(screen.getByRole("link", { name: "總覽" }));
  // The overview still shows the index summary for every agency.
  expect(screen.getByText("65 kt（JTWC，1 分鐘平均）")).toBeTruthy();
  expect(screen.getAllByText("此資料暫時無法取得")).toHaveLength(3);
  fireEvent.click(screen.getByRole("link", { name: "預報路徑" }));
  await screen.findByTestId("map");
  expect(screen.getByText("此系統的分析與預報資料暫時無法取得。")).toBeTruthy();
  expect(mapItems()).toEqual([]);
  expect(screen.getByText("目前沒有任何機構的預報點。")).toBeTruthy();
  expectNoRawValues();
});

test("a null JMA block, a null JTWC forecast and empty CWA points only affect those parts", async () => {
  const analysis = cempakaAnalysis();
  analysis.agencies.jma = null;
  const forecast = cempakaForecast();
  forecast.agencies.jtwc = null;
  forecast.agencies.cwa.points = [];
  await openForecast(cempakaRoutes({ analysis, forecast }));
  const layers = screen.getByRole("group", { name: "圖層" });
  expect(within(layers).getByText(/（沒有分析資料）/)).toBeTruthy();
  expect(within(layers).getByText(/（沒有預報資料）/)).toBeTruthy();
  expect(within(layers).getByText(/（這一報沒有預報點）/)).toBeTruthy();
  const agencies = new Set(mapItems().map(item => item.agency));
  expect([...agencies].sort()).toEqual(["cwa", "jma", "jtwc"]);
  fireEvent.click(screen.getByRole("link", { name: "各機構分析" }));
  expect(within(screen.getByRole("region", { name: "JMA 日本氣象廳" }))
    .getByText("此機構目前沒有這個系統的分析資料。")).toBeTruthy();
  expectNoRawValues();
});

test("one invalid forecast block is reported without hiding the others", async () => {
  const forecast = cempakaForecast();
  forecast.agencies.jtwc.points[1].valid_time = "2026-01-01T00:00:00Z";
  await openForecast(cempakaRoutes({ forecast }));
  expect(within(screen.getByRole("group", { name: "圖層" })).getByText(/（預報資料暫時無法取得）/)).toBeTruthy();
  expect(mapItems().some(item => item.agency === "jtwc" && item.layer === "forecast")).toBe(false);
  expect(mapItems().some(item => item.agency === "jma" && item.layer === "forecast")).toBe(true);
});

test("layer and agency switches change what the map draws", async () => {
  await openForecast();
  expect(mapItems().some(item => item.type === "radii")).toBe(false);
  fireEvent.click(screen.getByRole("checkbox", { name: "最新分析的風圈" }));
  expect(mapItems().some(item => item.type === "radii")).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "JMA" }));
  expect(mapItems().some(item => item.agency === "jma")).toBe(false);
  fireEvent.click(screen.getByRole("checkbox", { name: /機率圓/ }));
  expect(mapItems().some(item => item.type === "circle")).toBe(false);
  fireEvent.click(screen.getByRole("checkbox", { name: "過去路徑" }));
  expect(mapItems().some(item => item.layer === "past")).toBe(false);
});

test("the timeline shows real ticks, marks agencies without a node and keeps init times apart", async () => {
  await openForecast();
  const ticks = within(screen.getByRole("group", { name: "選擇有效時間" })).getAllByRole("button");
  expect(ticks.map(button => button.textContent)).toEqual([
    "最新分析CWAJMAJTWC",
    "11-11 12:00 UTC（臺灣 11-11 20:00）CWA",
    "11-11 18:00 UTC（臺灣 11-12 02:00）CWAJTWC",
    "11-11 21:00 UTC（臺灣 11-12 05:00）JMA",
    "11-12 06:00 UTC（臺灣 11-12 14:00）JTWC",
    "11-12 09:00 UTC（臺灣 11-12 17:00）JMA",
  ]);
  expect(screen.getByText(/各機構的起報時間不同/)).toBeTruthy();
  fireEvent.click(ticks[2]);
  expect(ticks[2].getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByText("此時刻沒有 JMA 的節點。")).toBeTruthy();
  expect(screen.getByText(/JTWC \+12 小時（起報 11-11 06:00 UTC（臺灣 11-11 14:00））/)).toBeTruthy();
  const marked = mapItems().filter(item => item.type === "node" && item.highlighted).map(item => item.nodeId).sort();
  expect(marked).toEqual(["cwa:forecast:1", "jtwc:forecast:0"]);
  // The CWA 70% circle at that time is emphasised too; JMA has none at 18Z.
  expect(mapItems().filter(item => item.type === "circle" && item.highlighted).map(item => item.nodeId)).toEqual(["cwa:forecast:1"]);
  fireEvent.click(ticks[2]);
  expect(ticks[2].getAttribute("aria-pressed")).toBe("false");
});

test("clicking a node shows its details and moves the timeline to its valid time", async () => {
  await openForecast();
  fireEvent.click(screen.getByRole("button", { name: "node jma:forecast:0" }));
  const detail = screen.getByRole("region", { name: "節點細節" });
  expect(within(detail).getByText("JMA 日本氣象廳｜預報點")).toBeTruthy();
  expect(within(detail).getByText("32.1°N 158.6°E")).toBeTruthy();
  expect(within(detail).getByText("55 kt／30 m/s（JMA，10 分鐘平均）")).toBeTruthy();
  expect(within(detail).getByText("預報圓（中心進入機率 70%）：85 km")).toBeTruthy();
  expect(within(detail).getByText("LOW")).toBeTruthy();
  const pressed = within(screen.getByRole("group", { name: "選擇有效時間" }))
    .getAllByRole("button").filter(button => button.getAttribute("aria-pressed") === "true");
  expect(pressed.map(button => button.textContent)).toEqual(["11-11 21:00 UTC（臺灣 11-12 05:00）JMA"]);

  fireEvent.click(screen.getByRole("button", { name: "node cwa:forecast:1" }));
  expect(within(screen.getByRole("region", { name: "節點細節" })).getByText("變性為溫帶氣旋（EXTRATROPICAL）")).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "節點細節" })).getByText("70% 機率半徑：70 km")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "node jtwc:fix:0" }));
  const fix = screen.getByRole("region", { name: "節點細節" });
  expect(within(fix).getByText("JTWC 聯合颱風警報中心｜最新分析")).toBeTruthy();
  expect(within(fix).getByText("70°，33 kt")).toBeTruthy();
  expectNoRawValues();
});

test("switching tabs reuses the files already read", async () => {
  const request = await openForecast();
  fireEvent.click(screen.getByRole("link", { name: "各機構分析" }));
  fireEvent.click(screen.getByRole("link", { name: "預報路徑" }));
  await screen.findByTestId("map");
  await settle();
  expect(requested(request).filter(url => url.includes("/storms/"))).toHaveLength(2);
});

test("a single-agency system across 180 shows east/west longitudes", async () => {
  const pena = cempaka({
    cyclone_id: "2026-jtwc-04c", name: "PENA", name_zh: null, origin_basin: "CP",
    ids: { jtwc: "04C", jma_tc: null, jma_number: null, cwa_ty: null, cwa_td: null },
    summary: { jma: null, cwa: null, jtwc: { analysis_time: "2026-11-12T06:00:00Z", active: true, lat: 9.8,
      lon: -171.3, category: "TROPICAL DEPRESSION", max_wind: { kt: 35, ms: null, averaging_min: 1 }, pressure_hpa: 1006 } },
  });
  serve({
    [INDEX_URL]: makeIndex({ storms: [pena] }),
    [fileUrl("2026-jtwc-04c", "analysis")]: penaAnalysis(),
    [fileUrl("2026-jtwc-04c", "forecast")]: penaForecast(),
  });
  await renderAt("/tropical?storm=2026-jtwc-04c&tab=forecast");
  await screen.findByTestId("map");
  await settle();
  expect(screen.getByText("目前只有 JTWC 有這個系統的資料。")).toBeTruthy();
  expect(screen.queryByText(/各機構的起報時間不同/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "node jtwc:forecast:2" }));
  expect(within(screen.getByRole("region", { name: "節點細節" })).getByText("10.2°N 180.0°")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "node jtwc:fix:0" }));
  expect(within(screen.getByRole("region", { name: "節點細節" })).getByText("9.8°N 171.3°W")).toBeTruthy();
  const line = mapItems().find(item => item.type === "line");
  expect(line.latlngs.every(([, lon]) => lon > 179 && lon < 190)).toBe(true);
});

test("an ended system is still viewable with its last data", async () => {
  const analysis = { ...cempakaAnalysis(), cyclone_id: "2026-jma-tc2637" };
  const forecast = { ...cempakaForecast(), cyclone_id: "2026-jma-tc2637" };
  forecast.agencies.jma.points = [];
  serve({
    [INDEX_URL]: makeIndex({ storms: [cempaka(), endedStorm()] }),
    [fileUrl("2026-jma-tc2637", "analysis")]: analysis,
    [fileUrl("2026-jma-tc2637", "forecast")]: forecast,
  });
  await renderAt("/tropical?storm=2026-jma-tc2637&tab=forecast");
  await screen.findByTestId("map");
  await settle();
  expect(screen.getByText(/此系統已結束/)).toBeTruthy();
  expect(screen.getByText("已結束")).toBeTruthy();
  expect(within(screen.getByRole("group", { name: "圖層" })).getByText(/（這一報沒有預報點）/)).toBeTruthy();
});

test("an unreadable index with a storm parameter reads no storm file", async () => {
  const request = serve({});
  await renderAt(`/tropical?storm=${ID}&tab=forecast`);
  await settle();
  expect(screen.getByText("熱帶系統資料暫時無法取得")).toBeTruthy();
  expect(requested(request)).toEqual([INDEX_URL]);
  expect(screen.queryByRole("navigation", { name: "系統資料分頁" })).toBeNull();
});

test("a stalled storm file ends as unavailable after the timeout", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.stubGlobal("fetch", vi.fn((url, { signal }) => {
    if (url === INDEX_URL) return Promise.resolve({ ok: true, json: async () => makeIndex() });
    return new Promise((_, reject) => signal.addEventListener("abort", () => reject(new Error("aborted"))));
  }));
  render(<MemoryRouter initialEntries={[`/tropical?storm=${ID}&tab=analysis`]}><TropicalPage getNow={() => NOW} /></MemoryRouter>);
  await screen.findByRole("navigation", { name: "系統資料分頁" });
  expect(screen.getAllByText("讀取中…").length).toBeGreaterThan(0);
  await act(async () => { vi.advanceTimersByTime(15001); });
  await settle();
  expect(screen.getByText("各機構的詳細分析資料暫時無法取得。")).toBeTruthy();
});

test("the storm page carries the attribution and the no-comparison note", async () => {
  await openForecast();
  const footer = screen.getByRole("contentinfo");
  expect(within(footer).getByText(/Natural Earth/)).toBeTruthy();
  expect(within(footer).getByText(/出典：気象庁ホームページ/)).toBeTruthy();
  expect(screen.getAllByText(/強度不可跨機構比較/).length).toBeGreaterThanOrEqual(2);
});

test("the map is told to fit only after both storm files have settled", async () => {
  let release;
  const forecastGate = new Promise(resolve => { release = resolve; });
  vi.stubGlobal("fetch", vi.fn(async url => {
    if (url === INDEX_URL) return { ok: true, json: async () => makeIndex() };
    if (url === fileUrl(ID, "analysis")) return { ok: true, json: async () => cempakaAnalysis() };
    await forecastGate;
    return { ok: true, json: async () => cempakaForecast() };
  }));
  await renderAt(`/tropical?storm=${ID}&tab=forecast`);
  await screen.findByTestId("map");
  await settle();
  expect(screen.getByTestId("map").getAttribute("data-ready")).toBe("false");
  expect(mapItems().length).toBeGreaterThan(0); // analysis already drawn
  release();
  await settle();
  await settle();
  expect(screen.getByTestId("map").getAttribute("data-ready")).toBe("true");
});

test("a tick whose nodes come from different init times says so", async () => {
  const forecast = cempakaForecast();
  // Move JMA's +12 point onto 18Z by starting it at 06Z: same valid time as JTWC/CWA, different init.
  forecast.agencies.jma.init_time = "2026-11-11T06:00:00Z";
  forecast.agencies.jma.points[0].valid_time = "2026-11-11T18:00:00Z";
  forecast.agencies.jma.points[1].valid_time = "2026-11-12T06:00:00Z";
  forecast.agencies.cwa.init_time = "2026-11-11T00:00:00Z";
  forecast.agencies.cwa.points[0].valid_time = "2026-11-11T06:00:00Z";
  forecast.agencies.cwa.points[1].valid_time = "2026-11-11T12:00:00Z";
  forecast.agencies.cwa.points[1].tau_h = 12;
  forecast.agencies.jtwc.init_time = "2026-11-11T00:00:00Z";
  forecast.agencies.jtwc.points[0].tau_h = 18;
  forecast.agencies.jtwc.points[1].tau_h = 30;
  await openForecast(cempakaRoutes({ forecast }));
  const tick = within(screen.getByRole("group", { name: "選擇有效時間" })).getAllByRole("button")
    .find(button => button.textContent.startsWith("11-11 18:00"));
  fireEvent.click(tick);
  expect(screen.getByText("這一刻的節點來自不同的起報時間，不是同一時刻起報的比較。")).toBeTruthy();
});
