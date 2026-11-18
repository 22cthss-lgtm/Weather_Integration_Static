import { afterEach, expect, test, vi } from "vitest";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TropicalPage from "./pages/TropicalPage";
import { NOW, cempaka, endedStorm, makeIndex, source } from "./tropical/test-fixtures";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.useRealTimers(); });

const NO_STORM_TEXT = "目前無活躍熱帶系統";

function serve(payload) {
  const request = vi.fn(async () => ({ ok: true, json: async () => payload }));
  vi.stubGlobal("fetch", request);
  return request;
}

async function renderPage({ url = "/tropical", now = NOW } = {}) {
  const view = render(
    <MemoryRouter initialEntries={[url]}><TropicalPage getNow={() => now} /></MemoryRouter>,
  );
  await screen.findByRole("heading", { name: /資料來源與署名/ });
  expect(screen.queryByText("讀取中…")).toBeNull();
  return view;
}

function pageText() {
  return document.body.textContent;
}

function expectNoRawValues() {
  expect(pageText()).not.toMatch(/\bnull\b|undefined|NaN/);
}

test("reads the index under the deployment base without caching surprises", async () => {
  vi.stubEnv("BASE_URL", "/weather-test/");
  const request = serve(makeIndex());
  await renderPage();
  expect(request).toHaveBeenCalledTimes(1);
  const [url, options] = request.mock.calls[0];
  expect(url).toBe("/weather-test/data/tropical/official/index.json");
  expect(options.cache).toBe("no-cache");
  expect(options.signal).toBeTruthy();
});

test("OK_WITH_STORMS lists agencies separately with averaging periods and dual times", async () => {
  serve(makeIndex());
  await renderPage();
  expect(screen.getByText("以下為各機構目前發報中的系統。")).toBeTruthy();
  const card = screen.getByRole("article", { name: "CEMPAKA" });
  expect(within(card).getByText("查帕卡")).toBeTruthy();
  expect(within(card).getByText(/JTWC 31W｜JMA TC2638｜JMA 編號 2632｜CWA 第 31 號颱風｜CWA 熱帶性低氣壓 TD 35/)).toBeTruthy();
  expect(within(card).getByText("65 kt（JTWC，1 分鐘平均）")).toBeTruthy();
  expect(within(card).getByText("60 kt／30 m/s（JMA，10 分鐘平均）")).toBeTruthy();
  expect(within(card).getByText("30 m/s（CWA，10 分鐘平均）")).toBeTruthy();
  expect(within(card).getByText("29.1°N 150.2°E")).toBeTruthy();
  expect(within(card).getAllByText("2026-11-11 06:00 UTC").length).toBeGreaterThan(0);
  expect(within(card).getAllByText("臺灣 2026-11-11 14:00").length).toBeGreaterThan(0);
  // Agency categories are verbatim; CWA has none and shows no empty label.
  expect(within(card).getByText("TYPHOON")).toBeTruthy();
  expect(within(card).getByText("STS")).toBeTruthy();
  const cwa = within(card).getByRole("region", { name: "CWA 中央氣象署" });
  expect(within(cwa).queryByText("機構分類（原文）")).toBeNull();
  // No cross-agency ranking words.
  expect(pageText()).not.toMatch(/最強|最弱|平均強度/);
  expect(pageText()).not.toContain(NO_STORM_TEXT);
  expectNoRawValues();
});

test("OK_NO_STORMS with an empty list says there is no active system", async () => {
  serve(makeIndex({ status: "OK_NO_STORMS", storms: [], cwa: source("ok", undefined, { active_count: 0 }) }));
  await renderPage();
  expect(screen.getByText(`${NO_STORM_TEXT}。`)).toBeTruthy();
  expect(screen.queryByRole("article")).toBeNull();
  expect(screen.getByText("本次回報活躍系統：0")).toBeTruthy();
});

test("OK_NO_STORMS lists recently ended systems under the no-storm message", async () => {
  serve(makeIndex({ status: "OK_NO_STORMS", storms: [endedStorm()] }));
  await renderPage();
  expect(screen.getByText(`${NO_STORM_TEXT}。`)).toBeTruthy();
  const ended = screen.getByRole("region", { name: "近期結束的系統" });
  const card = within(ended).getByRole("article", { name: "PENA" });
  expect(within(card).getByText("已結束")).toBeTruthy();
  expect(within(card).getByText("2026-11-10 12:00 UTC")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "活躍系統" })).toBeNull();
});

test.each([
  ["empty storms", []],
  ["only ended storms", [endedStorm()]],
])("PARTIAL with %s never says there is no system", async (_, storms) => {
  serve(makeIndex({ status: "PARTIAL", storms, jma: source("failed") }));
  await renderPage();
  expect(screen.getByText("部分來源無法取得，無法確認是否有活躍系統。")).toBeTruthy();
  expect(pageText()).not.toContain(NO_STORM_TEXT);
  const jma = screen.getByText(/JMA 日本氣象廳/, { selector: ".tc-source-name" }).closest("li");
  expect(within(jma).getByText("本次失敗：HTTP 錯誤（http_error）")).toBeTruthy();
});

test("PARTIAL with storms keeps the successful data and marks the gap", async () => {
  serve(makeIndex({ status: "PARTIAL", jtwc: { ...source("failed", "2026-11-11T09:03:00Z"), required: false } }));
  await renderPage();
  expect(screen.getByText(/部分來源無法取得：以下為取得成功的來源/)).toBeTruthy();
  expect(screen.getByRole("article", { name: "CEMPAKA" })).toBeTruthy();
  const jtwc = screen.getByText(/JTWC 聯合颱風警報中心/, { selector: ".tc-source-name" }).closest("li");
  expect(within(jtwc).getByText("選用來源")).toBeTruthy();
  expect(within(jtwc).getByText("2026-11-11 09:03 UTC")).toBeTruthy();
});

test.each([
  ["just under three hours", Date.parse("2026-11-11T13:32:59Z"), false],
  ["exactly three hours", Date.parse("2026-11-11T13:33:00Z"), false],
  ["over three hours", Date.parse("2026-11-11T13:33:01Z"), true],
])("STALE threshold %s", async (_, now, stale) => {
  serve(makeIndex({ status: "OK_NO_STORMS", storms: [] }));
  await renderPage({ now });
  if (stale) {
    expect(screen.getByText("資料可能已過期，目前狀況無法確認")).toBeTruthy();
    expect(screen.getByText("當時沒有活躍熱帶系統（已過期，不代表現在）。", { exact: false })).toBeTruthy();
    expect(pageText()).not.toContain(NO_STORM_TEXT);
  } else {
    expect(screen.queryByText("資料可能已過期，目前狀況無法確認")).toBeNull();
    expect(screen.getByText(`${NO_STORM_TEXT}。`)).toBeTruthy();
  }
});

test("STALE overrides PARTIAL, shows last confirmation times and keeps the storms", async () => {
  serve(makeIndex({ status: "PARTIAL", cwa: source("failed", null),
    jtwc: { ...source("failed"), required: false } }));
  await renderPage();
  const banner = screen.getByRole("alert");
  expect(within(banner).getByText("資料可能已過期，目前狀況無法確認")).toBeTruthy();
  expect(within(banner).getByText(/CWA 最後確認時間/)).toBeTruthy();
  expect(within(banner).getAllByText(/尚無成功紀錄/).length).toBe(1);
  expect(within(banner).getByText("2026-11-11 10:33 UTC")).toBeTruthy();
  expect(within(banner).getByText("已過期")).toBeTruthy();
  expect(screen.getByRole("article", { name: "CEMPAKA" })).toBeTruthy();
});

test.each([
  ["404", async () => ({ ok: false, status: 404, json: async () => ({}) })],
  ["network error", async () => { throw new TypeError("Failed to fetch"); }],
  ["broken JSON", async () => ({ ok: true, json: async () => { throw new SyntaxError("Unexpected token"); } })],
  ["unexpected fields", async () => ({ ok: true, json: async () => ({ ...makeIndex(), schema_version: 9 }) })],
  ["storms not a list", async () => ({ ok: true, json: async () => ({ ...makeIndex({ status: "OK_NO_STORMS" }), storms: {} }) })],
])("UNAVAILABLE on %s is never shown as no storms", async (_, response) => {
  vi.stubGlobal("fetch", vi.fn(response));
  await renderPage({ url: "/tropical?storm=2026-jma-tc2638" });
  expect(screen.getByText("熱帶系統資料暫時無法取得")).toBeTruthy();
  expect(pageText()).not.toContain(NO_STORM_TEXT);
  expect(pageText()).not.toContain("找不到這個系統");
  expect(screen.queryByRole("article")).toBeNull();
  expect(screen.queryByText("來源狀態")).toBeNull();
});

test("a stalled request ends as UNAVAILABLE after the timeout", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn((_, { signal }) => new Promise((_, reject) => {
    signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
  })));
  render(<MemoryRouter initialEntries={["/tropical"]}><TropicalPage getNow={() => NOW} /></MemoryRouter>);
  expect(screen.getByText("讀取中…")).toBeTruthy();
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
  expect(screen.getByText("熱帶系統資料暫時無法取得")).toBeTruthy();
});

test("every nullable field renders without errors or raw null text", async () => {
  const nullable = cempaka({
    cyclone_id: "2026-cwa-36", name: null, name_zh: null,
    ids: { jtwc: null, jma_tc: null, jma_number: null, cwa_ty: null, cwa_td: null },
    match: { jtwc: null, jma: null, cwa: "origin" },
    summary: {
      jtwc: null, jma: null,
      cwa: { analysis_time: "2026-11-11T06:00:00Z", active: true, lat: 15.0, lon: 130.0, category: null,
        max_wind: null, pressure_hpa: null },
    },
  });
  const empty = cempaka({ cyclone_id: "2026-jtwc-40w", name: null, name_zh: null, summary: null, ids: null });
  serve(makeIndex({ storms: [nullable, empty] }));
  await renderPage();
  const cards = screen.getAllByRole("article", { name: "未命名系統" });
  expect(cards).toHaveLength(2);
  expect(within(cards[0]).getByText("編號：—")).toBeTruthy();
  expect(within(cards[1]).getByText("沒有機構資料。")).toBeTruthy();
  expect(screen.getByText(/未命名的系統在各機構命名前/)).toBeTruthy();
  expectNoRawValues();
});

test("same-name storms listed side by side show the possible-duplicate hint", async () => {
  const jtwcOnly = cempaka({ cyclone_id: "2026-jtwc-31w", name_zh: null,
    match: { jtwc: "origin", jma: null, cwa: null },
    summary: { ...cempaka().summary, jma: null, cwa: null } });
  const other = cempaka({ cyclone_id: "2026-jtwc-32w", name: "DIFFERENT", name_zh: null });
  serve(makeIndex({ storms: [cempaka(), jtwcOnly, other] }));
  await renderPage();
  const hints = screen.getAllByText(/可能為同一系統/);
  expect(hints).toHaveLength(2);
  expect(within(screen.getByRole("article", { name: "DIFFERENT" })).queryByText(/可能為同一系統/)).toBeNull();
});

test("a valid storm parameter in the index opens that system's page", async () => {
  serve(makeIndex({ storms: [cempaka(), endedStorm()] }));
  await renderPage({ url: "/tropical?storm=2026-jma-tc2637&tab=forecast" });
  const page = screen.getByRole("article", { name: "PENA" });
  expect(within(page).getByRole("link", { name: "預報路徑" }).getAttribute("aria-current")).toBe("page");
  expect(screen.queryByRole("article", { name: "CEMPAKA" })).toBeNull();
  expect(pageText()).not.toContain("找不到這個系統");
});

test("a well-formed storm missing from the index shows the not-found notice on the overview", async () => {
  serve(makeIndex());
  await renderPage({ url: "/tropical?storm=2026-jtwc-99w" });
  expect(screen.getByText("找不到這個系統，可能已結束或編號已變更。")).toBeTruthy();
  expect(screen.getByRole("article", { name: "CEMPAKA" })).toBeTruthy();
});

test.each(["2026-JMA-TC2638", "x", "2026-jma-tc2638/../a", "%3Cscript%3E"])(
  "a malformed storm parameter %s is ignored", async storm => {
    serve(makeIndex());
    await renderPage({ url: `/tropical?storm=${storm}&tab=evil` });
    expect(pageText()).not.toContain("找不到這個系統");
    expect(screen.getByRole("article", { name: "CEMPAKA" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "系統資料分頁" })).toBeNull();
  });

test("attribution names CWA, JMA and JTWC and is marked provisional", async () => {
  serve(makeIndex());
  await renderPage();
  const footer = screen.getByRole("contentinfo");
  expect(within(footer).getByText(/暫定文字/)).toBeTruthy();
  // JTWC, and NOAA/NWS when the model layers are built in (design.md 11f F9).
  expect(within(footer).getByText(/JTWC）資料，該資料不受著作權保護（17 U\.S\.C\. §403）/)).toBeTruthy();
  expect(within(footer).getByText(/出典：気象庁ホームページ/)).toBeTruthy();
  expect(within(footer).getByText(/交通部中央氣象署/)).toBeTruthy();
});

test("STALE with storms uses past-tense wording, not the current-status sentence", async () => {
  serve(makeIndex());
  await renderPage({ now: Date.parse("2026-11-11T14:00:00Z") });
  const banner = screen.getByRole("alert");
  expect(within(banner).getByText(/當時各機構發報中的系統如下（已過期，可能已有變化）/)).toBeTruthy();
  expect(pageText()).not.toContain("以下為各機構目前發報中的系統");
  expect(screen.getByRole("article", { name: "CEMPAKA" })).toBeTruthy();
});

test("a fresh index claiming no storms while a required source failed is UNAVAILABLE", async () => {
  serve(makeIndex({ status: "OK_NO_STORMS", storms: [], cwa: source("failed", "2026-11-11T10:00:00Z") }));
  await renderPage();
  expect(screen.getByText("熱帶系統資料暫時無法取得")).toBeTruthy();
  expect(pageText()).not.toContain(NO_STORM_TEXT);
});
