import { afterEach, expect, test, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TropicalPage from "./pages/TropicalPage";
import { NOW, cempaka, makeIndex } from "./tropical/test-fixtures";
import { cempakaAnalysis, cempakaForecast } from "./tropical/storm-test-fixtures";
import { cempakaModels06, cempakaModels12, modelsIndex } from "./tropical/model-test-fixtures";

// Same stand-in as tropical-detail.test.jsx; model nodes are clickable too.
vi.mock("./pages/tropical/TrackMap", () => ({
  default: ({ items, onSelectNode, ready }) => {
    globalThis.__mapItemsSeen?.push(items);
    return (
    <div data-testid="map" data-items={JSON.stringify(items)} data-ready={String(ready)}>
      {items.filter(item => item.type === "node" || item.type === "modelNode").map(item => (
        <button key={item.nodeId} type="button" onClick={() => onSelectNode(item.nodeId)}>node {item.nodeId}</button>
      ))}
    </div>
    );
  },
}));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const ID = "2026-jma-tc2638";
const MODELS_INDEX_URL = "/data/tropical/models/index.json";
const modelUrl = cycle => `/data/tropical/models/storms/${ID}/${cycle}.json`;
const BAD_JSON = Symbol("bad json");

function serve(routes) {
  const request = vi.fn(async url => {
    if (!(url in routes)) return { ok: false, status: 404, json: async () => ({}) };
    const route = routes[url];
    if (route instanceof Error) throw route;
    if (route === BAD_JSON) return { ok: true, json: async () => { throw new SyntaxError("bad"); } };
    return { ok: true, json: async () => route };
  });
  vi.stubGlobal("fetch", request);
  return request;
}

function routesWith(models = {}, { index = makeIndex() } = {}) {
  return {
    "/data/tropical/official/index.json": index,
    [`/data/tropical/official/storms/${ID}/analysis.json`]: cempakaAnalysis(),
    [`/data/tropical/official/storms/${ID}/forecast.json`]: cempakaForecast(),
    ...models,
  };
}

const standard = () => routesWith({
  [MODELS_INDEX_URL]: modelsIndex({ [ID]: [{ cycle: "2026111106", models: ["aigfs", "gfs"] }] }),
  [modelUrl("2026111106")]: cempakaModels06(),
});

async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
}

async function open(url, routes) {
  const request = serve(routes);
  render(<MemoryRouter initialEntries={[url]}><TropicalPage getNow={() => NOW} /></MemoryRouter>);
  await screen.findByRole("heading", { name: /資料來源與署名/ });
  await settle();
  await settle();
  return request;
}

const openForecast = routes => open(`/tropical?storm=${ID}&tab=forecast`, routes);
const requested = request => request.mock.calls.map(([url]) => url);
const modelRequests = request => requested(request).filter(url => url.includes("/tropical/models/"));
const mapItems = () => JSON.parse(screen.getByTestId("map").getAttribute("data-items"));
const modelSection = () => screen.getByRole("group", { name: "數值模式路徑（原始輸出）" });
const modelBox = name => within(modelSection()).getByRole("checkbox", { name: new RegExp(`^${name}（`) });
const text = () => document.body.textContent;

test("model files are read only on the Forecast tab, once per page lifetime", async () => {
  const request = await open(`/tropical?storm=${ID}&tab=overview`, standard());
  expect(modelRequests(request)).toEqual([]);
  fireEvent.click(screen.getByRole("link", { name: "各機構分析" }));
  await settle();
  expect(modelRequests(request)).toEqual([]);
  fireEvent.click(screen.getByRole("link", { name: "預報路徑" }));
  await screen.findByTestId("map");
  await settle();
  await settle();
  expect(modelRequests(request)).toEqual([MODELS_INDEX_URL, modelUrl("2026111106")]);
  fireEvent.click(screen.getByRole("link", { name: "總覽" }));
  await settle();
  fireEvent.click(screen.getByRole("link", { name: "預報路徑" }));
  await screen.findByTestId("map");
  await settle();
  expect(modelRequests(request)).toEqual([MODELS_INDEX_URL, modelUrl("2026111106")]);
  expect(within(modelSection()).getByText(/模式起報時間（cycle）/)).toBeTruthy();
});

test("the overview list never reads model files", async () => {
  const request = await open("/tropical", standard());
  expect(modelRequests(request)).toEqual([]);
});

test("model layers start off, with their own legend; switching one on adds its line, nodes and ticks", async () => {
  await openForecast(standard());
  expect(within(modelSection()).getByText("數值模式原始輸出，非官方預報，亦非本站預報。")).toBeTruthy();
  const official = mapItems();
  expect(official.some(item => item.layer === "model")).toBe(false);
  for (const name of ["GFS", "AIGFS"]) expect(modelBox(name).checked).toBe(false);
  // This cycle has no ECMWF tracks: those switches are disabled and say why.
  for (const name of ["IFS", "AIFS"]) expect(modelBox(name).disabled).toBe(true);
  expect(within(modelSection()).getAllByText("（這個 cycle 沒有此模式）")).toHaveLength(2);
  const ticksBefore = screen.getAllByRole("button", { pressed: false }).length;

  fireEvent.click(modelBox("GFS"));
  const items = mapItems();
  expect(items.slice(0, official.length)).toEqual(official);
  const gfs = items.filter(item => item.model === "gfs");
  expect(gfs.filter(item => item.type === "modelLine")).toHaveLength(1);
  expect(gfs.filter(item => item.type === "modelNode")).toHaveLength(cempakaModels06().models.gfs.track.length);
  expect(items.some(item => item.model === "aigfs")).toBe(false);
  expect(screen.getAllByRole("button", { pressed: false }).length).toBeGreaterThan(ticksBefore);
  expect(within(screen.getByRole("group", { name: "選擇有效時間" })).getAllByText("GFS").length).toBeGreaterThan(0);
  expect(screen.getByText(/已開啟的數值模式起報時間（cycle）：/)).toBeTruthy();

  fireEvent.click(modelBox("GFS"));
  expect(mapItems()).toEqual(official);
  expect(screen.queryAllByText(/已開啟的數值模式起報時間（cycle）/)).toHaveLength(0);
});

test("a model node shows the model's own details and no matching internals", async () => {
  await openForecast(standard());
  fireEvent.click(modelBox("GFS"));
  fireEvent.click(screen.getByRole("button", { name: "node model:gfs:2" }));
  const detail = screen.getByRole("region", { name: "節點細節" });
  const point = cempakaModels06().models.gfs.track[2];
  expect(within(detail).getByText("GFS（NOAA）｜數值模式節點")).toBeTruthy();
  expect(within(detail).getByText("NOAA")).toBeTruthy();
  expect(within(detail).getByText(`起報後 +${point[0]} 小時`)).toBeTruthy();
  expect(within(detail).getByText(`模式 10 m 最大風 ${point[4]} kt（模式輸出，沒有平均期間）`)).toBeTruthy();
  expect(detail.textContent).not.toMatch(/WP31|jtwc_id|source_id|match/);
  expect(detail.textContent).not.toMatch(/分鐘平均/);
  // The timeline moved to the node's valid time and lists GFS there.
  const tick = screen.getByRole("button", { pressed: true });
  expect(tick.textContent).toMatch(/GFS/);
  expect(screen.getByText(/GFS 起報後 \+12 小時/)).toBeTruthy();
  // Switching the model off clears a node that belonged to it; this tick (11-11 18Z) also has
  // official nodes, so it stays selected, without GFS.
  fireEvent.click(modelBox("GFS"));
  expect(screen.queryByRole("region", { name: "節點細節" })).toBeNull();
  expect(screen.getByRole("button", { pressed: true }).textContent).not.toMatch(/GFS/);
  expect(screen.queryByText(/GFS 起報後/)).toBeNull();
});

const failures = {
  "index 404": routesWith(),
  "index bad JSON": routesWith({ [MODELS_INDEX_URL]: BAD_JSON }),
  "index network error": routesWith({ [MODELS_INDEX_URL]: new TypeError("offline") }),
  "index wrong shape": routesWith({ [MODELS_INDEX_URL]: { ...modelsIndex(), schema_version: 2 } }),
  "listed cycle file missing": routesWith({
    [MODELS_INDEX_URL]: modelsIndex({ [ID]: [{ cycle: "2026111106", models: ["gfs"] }] }),
  }),
  "cycle file bad JSON": routesWith({
    [MODELS_INDEX_URL]: modelsIndex({ [ID]: [{ cycle: "2026111106", models: ["gfs"] }] }),
    [modelUrl("2026111106")]: BAD_JSON,
  }),
  "cycle file for another cycle": routesWith({
    [MODELS_INDEX_URL]: modelsIndex({ [ID]: [{ cycle: "2026111106", models: ["gfs"] }] }),
    [modelUrl("2026111106")]: cempakaModels12(),
  }),
};

for (const [name, routes] of Object.entries(failures)) {
  test(`model read failure (${name}) only affects the model section`, async () => {
    await openForecast(routes);
    expect(within(modelSection()).getByText("數值模式資料暫時無法取得；官方路徑不受影響。")).toBeTruthy();
    for (const model of ["GFS", "AIGFS", "IFS", "AIFS"]) expect(modelBox(model).disabled).toBe(true);
    expect(mapItems().some(item => item.agency === "jtwc" && item.type === "line")).toBe(true);
    expect(text()).not.toMatch(/\bnull\b|undefined|NaN/);
  });
}

test("empty cycles (11e E16) and an unlisted storm are 'no model data', not a failure", async () => {
  const bridged = modelsIndex({ [ID]: [] });
  bridged.storms[ID].bridge.jtwc = "31W";
  for (const index of [bridged, modelsIndex()]) {
    const request = await openForecast(routesWith({ [MODELS_INDEX_URL]: index }));
    expect(within(modelSection()).getByText("目前沒有這個系統的數值模式資料。")).toBeTruthy();
    expect(modelRequests(request)).toEqual([MODELS_INDEX_URL]);
    cleanup();
  }
});

test("one bad model block disables only that model", async () => {
  const file = cempakaModels06();
  file.models.aigfs.track[0][1] = 95;
  await openForecast(routesWith({
    [MODELS_INDEX_URL]: modelsIndex({ [ID]: [{ cycle: "2026111106", models: ["aigfs", "gfs"] }] }),
    [modelUrl("2026111106")]: file,
  }));
  expect(modelBox("AIGFS").disabled).toBe(true);
  expect(within(modelSection()).getByText("（此模式的資料暫時無法取得）")).toBeTruthy();
  expect(modelBox("GFS").disabled).toBe(false);
});

test("newest cycle older than 18 hours on an active storm: 'may not be updated'; init times differ", async () => {
  const routes = routesWith({
    [MODELS_INDEX_URL]: modelsIndex({ [ID]: [{ cycle: "2026111012", models: ["aifs", "ifs"] }] }),
    [modelUrl("2026111012")]: cempakaModels12(),
  });
  await openForecast(routes);
  expect(within(modelSection()).getByText(/模式資料可能未更新/)).toBeTruthy();
  fireEvent.click(modelBox("IFS"));
  expect(screen.getByText(/已開啟的數值模式起報時間（cycle）與官方起報時間不同/)).toBeTruthy();
  // tau 30 of the 11-10 12Z cycle is 11-11 18Z, a time JTWC and CWA (06Z) also forecast.
  fireEvent.click(screen.getByRole("button", { name: "node model:ifs:5" }));
  const detail = screen.getByRole("region", { name: "節點細節" });
  expect(within(detail).getByText(/m\/s（模式輸出，沒有平均期間）/)).toBeTruthy();
  expect(screen.getByText("這一刻的節點來自不同的起報時間，不是同一時刻起報的比較。")).toBeTruthy();
});

test("an ended storm keeps showing its model data without the freshness hint", async () => {
  const ended = makeIndex({ status: "OK_NO_STORMS", storms: [cempaka({ status: "ended", ended_at: "2026-11-11T09:00:00Z" })] });
  await openForecast(routesWith({
    [MODELS_INDEX_URL]: modelsIndex({ [ID]: [{ cycle: "2026111012", models: ["aifs", "ifs"] }] }),
    [modelUrl("2026111012")]: cempakaModels12(),
  }, { index: ended }));
  expect(within(modelSection()).queryByText(/模式資料可能未更新/)).toBeNull();
  expect(modelBox("IFS").disabled).toBe(false);
});

test("wording: the model section and legends never call model output a forecast of this site", async () => {
  await openForecast(standard());
  fireEvent.click(modelBox("GFS"));
  const section = modelSection().textContent;
  expect(section).not.toMatch(/預測/);
  expect(section.replace("非官方預報，亦非本站預報", "")).not.toMatch(/預報/);
  expect(text()).not.toMatch(/預測/);
  const footer = screen.getByRole("contentinfo");
  expect(within(footer).getByText(/NOAA／NWS（數值模式 GFS、AIGFS）/)).toBeTruthy();
  expect(within(footer).getByText(/European Centre for Medium-Range Weather Forecasts \(ECMWF\)/)).toBeTruthy();
});

test("switching a model off and on again does not bring back its old selection (review 1)", async () => {
  await openForecast(standard());
  fireEvent.click(modelBox("GFS"));
  fireEvent.click(screen.getByRole("button", { name: "node model:gfs:0" }));
  // tau 0 of the 06Z cycle is a GFS-only tick (the official step for 06Z is "latest analysis").
  expect(screen.getByRole("region", { name: "節點細節" })).toBeTruthy();
  expect(screen.getByRole("button", { pressed: true }).textContent).toMatch(/GFS/);
  fireEvent.click(modelBox("GFS"));
  fireEvent.click(modelBox("GFS"));
  expect(screen.queryByRole("region", { name: "節點細節" })).toBeNull();
  expect(screen.queryByRole("button", { pressed: true })).toBeNull();
});

test("the model state keeps its identity across page clock ticks, so the map is not rebuilt (review 3)", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    let clock = NOW;
    serve(standard());
    render(<MemoryRouter initialEntries={[`/tropical?storm=${ID}&tab=forecast`]}>
      <TropicalPage getNow={() => clock} />
    </MemoryRouter>);
    await screen.findByTestId("map");
    await settle();
    await settle();
    globalThis.__mapItemsSeen = [];
    fireEvent.click(modelBox("GFS"));
    const before = globalThis.__mapItemsSeen.at(-1);
    const count = globalThis.__mapItemsSeen.length;
    clock += 61 * 1000;
    await act(async () => { vi.advanceTimersByTime(61 * 1000); });
    const after = globalThis.__mapItemsSeen.slice(count);
    expect(after.length).toBeGreaterThan(0); // the page re-rendered for the clock tick
    expect(after.every(items => items === before)).toBe(true);
    expect(before.some(item => item.model === "gfs")).toBe(true);
  } finally {
    delete globalThis.__mapItemsSeen;
    vi.useRealTimers();
  }
});
