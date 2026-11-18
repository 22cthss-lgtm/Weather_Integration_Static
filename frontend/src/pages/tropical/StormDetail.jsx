// One storm: /tropical?storm={cyclone_id}&tab=overview|forecast|analysis|imagery (design.md 7.1, 7.4).
import { Component, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchTropicalStormFile } from "../../api";
import { AGENCIES } from "../../tropical/status";
import { checkStormFile } from "../../tropical/storm-files";
import { MODEL_LAYERS_ENABLED } from "../../tropical/features";
import {
  MODELS_INDEX_KEY, checkModelFile, checkModelsIndex, fetchTropicalModelsFile, fetchTropicalModelsIndex,
  modelEntry, modelFileKey,
} from "../../tropical/models";
import {
  AGENCY_LABELS, AGENCY_SHORT, formatGust, formatIds, formatMovement, formatPosition, formatPressure,
  formatRadii, formatWind, textOrNull,
} from "../../tropical/format";
import { AgencySummary, DualTime, INTENSITY_NOTE } from "./common";
import ForecastPanel from "./ForecastPanel";

const REQUEST_TIMEOUT_MS = 15000;
const KINDS = ["analysis", "forecast"];

export const TABS = [
  { id: "overview", label: "總覽" },
  { id: "forecast", label: "預報路徑" },
  { id: "analysis", label: "各機構分析" },
  { id: "imagery", label: "圖像（尚未開放）" },
];

/**
 * Reads analysis.json and forecast.json once per page lifetime. Each value is
 * undefined while loading, null when the read or the shape check failed, else checkStormFile().
 */
function useStormFiles(cycloneId, cache) {
  const [files, setFiles] = useState(() => Object.fromEntries(
    KINDS.map(kind => [kind, cache.get(`${cycloneId}/${kind}`)]),
  ));
  useEffect(() => {
    let active = true;
    const controllers = [];
    for (const kind of KINDS) {
      const key = `${cycloneId}/${kind}`;
      if (cache.has(key)) continue;
      const controller = new AbortController();
      controllers.push(controller);
      const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
      fetchTropicalStormFile(cycloneId, kind, { signal: controller.signal })
        .then(data => checkStormFile(data, kind, cycloneId))
        .catch(() => null)
        .then(result => {
          if (!active) return;
          cache.set(key, result);
          setFiles(current => ({ ...current, [kind]: result }));
        })
        .finally(() => clearTimeout(timer));
    }
    return () => {
      active = false;
      for (const controller of controllers) controller.abort();
    };
  }, [cycloneId, cache]);
  return files;
}

/**
 * Model data for the Forecast tab (design.md 7.4, 11e E4, 11f F2): the models index, then the
 * newest cycle file of this storm. Requests start only while `active` (Forecast tab open and the
 * build switch on). Results, failures included, stay in the page-lifetime cache, so each file is
 * read at most once. A request cut off by leaving the tab is not cached and is made again later.
 * @returns {status: "loading" | "unavailable" | "none"} or {status: "ok", cycle, file}
 */
function useModelFiles(cycloneId, cache, active) {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    if (!active) return undefined;
    let alive = true;
    const pending = [];
    const load = (key, request, check) => {
      if (cache.has(key)) return;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
      pending.push({ controller, timer });
      request({ signal: controller.signal })
        .then(check)
        .catch(() => null)
        .then(result => {
          if (!alive) return;
          cache.set(key, result);
          setVersion(current => current + 1);
        })
        .finally(() => clearTimeout(timer));
    };
    load(MODELS_INDEX_KEY, fetchTropicalModelsIndex, checkModelsIndex);
    const index = cache.get(MODELS_INDEX_KEY);
    if (index) {
      const entry = modelEntry(index, cycloneId);
      if (entry.status === "ok") {
        load(modelFileKey(cycloneId, entry.cycle),
          options => fetchTropicalModelsFile(cycloneId, entry.cycle, options),
          data => checkModelFile(data, cycloneId, entry.cycle));
      }
    }
    return () => {
      alive = false;
      for (const { controller, timer } of pending) {
        clearTimeout(timer);
        controller.abort();
      }
    };
  }, [active, cycloneId, cache, version]);

  let status = "loading";
  let cycle = null;
  let file = null;
  if (cache.has(MODELS_INDEX_KEY)) {
    const index = cache.get(MODELS_INDEX_KEY);
    const entry = index === null ? { status: "unavailable" } : modelEntry(index, cycloneId);
    status = entry.status;
    if (entry.status === "ok") {
      const key = modelFileKey(cycloneId, entry.cycle);
      cycle = entry.cycle;
      file = cache.get(key) ?? null;
      status = !cache.has(key) ? "loading" : file === null ? "unavailable" : "ok";
    }
  }
  // A stable object while nothing changed, so the panel does not rebuild tracks and redraw the
  // map on every clock tick (review suggestion 3).
  return useMemo(() => (status === "ok" ? { status, cycle, file } : { status }), [status, cycle, file]);
}

// Last line of defence: an unexpected value inside one tab must not blank the whole page.
class TabBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) return <p className="tc-unavailable" role="note">此分頁的資料暫時無法顯示。</p>;
    return this.props.children;
  }
}

export function blockState(file, agency) {
  if (file === undefined) return { status: "loading" };
  if (file === null) return { status: "unavailable" };
  return file.agencies[agency];
}

export function Unavailable({ children = "此資料暫時無法取得。" }) {
  return <p className="tc-unavailable" role="note">{children}</p>;
}

function blockMessage(state, what) {
  if (state.status === "loading") return <p className="status-message">讀取中…</p>;
  if (state.status === "missing") return <p className="status-message">此機構目前沒有這個系統的{what}。</p>;
  return <Unavailable />;
}

function OverviewTab({ storm, analysis }) {
  const summaries = storm.summary && typeof storm.summary === "object" ? storm.summary : {};
  return (
    <section className="tc-section" aria-labelledby="tc-tab-title">
      <h3 id="tc-tab-title" className="tc-visually-hidden">總覽</h3>
      <p className="status-message">最新分析時間（各機構最大值）：<DualTime stamp={storm.last_fix_time} /></p>
      <div className="tc-agency-grid">
        {AGENCIES.map(agency => {
          const summary = summaries[agency];
          if (!summary || typeof summary !== "object") {
            return (
              <section key={agency} className="tc-agency" aria-label={AGENCY_LABELS[agency]}>
                <h5>{AGENCY_LABELS[agency]}</h5>
                <p className="status-message">此機構目前沒有這個系統的資料。</p>
              </section>
            );
          }
          const state = blockState(analysis, agency);
          let movement;
          if (state.status === "ok") {
            const fix = state.block.fix;
            movement = fix.analysis_time === summary.analysis_time
              ? formatMovement(fix.movement) || "—"
              : "—（詳細資料與索引的分析時間不同，請見「各機構分析」）";
          } else if (state.status === "loading") movement = "讀取中…";
          else if (state.status === "missing") movement = "—";
          else movement = "此資料暫時無法取得";
          return (
            <AgencySummary key={agency} agency={agency} summary={summary}>
              <dt>移動</dt>
              <dd>{movement}</dd>
            </AgencySummary>
          );
        })}
      </div>
      <p className="tc-note">{INTENSITY_NOTE}</p>
    </section>
  );
}

function PastTrackLabel({ block }) {
  const count = block.past_track.length;
  if (block.past_track_origin === "accumulated") {
    return <>{count} 點（本站累積：僅含本站開始觀察後的紀錄，不是完整生命史）</>;
  }
  if (block.past_track_origin === "source") return <>{count} 點（機構提供的過去路徑）</>;
  return <>{count} 點</>;
}

function AnalysisCard({ agency, state, summary }) {
  if (state.status !== "ok") {
    return (
      <section className="tc-agency" aria-label={AGENCY_LABELS[agency]}>
        <h5>{AGENCY_LABELS[agency]}</h5>
        {blockMessage(state, "分析資料")}
      </section>
    );
  }
  const block = state.block;
  const fix = block.fix;
  const category = textOrNull(fix.category);
  const radii = fix.radii.map(formatRadii).filter(Boolean);
  const bulletin = textOrNull(block.bulletin);
  const older = summary && typeof summary === "object" && summary.analysis_time !== fix.analysis_time;
  return (
    <section className="tc-agency" aria-label={AGENCY_LABELS[agency]}>
      <h5>{AGENCY_LABELS[agency]}</h5>
      {block.final ? <p className="tc-flag">機構已發布最終報</p> : null}
      {older ? (
        <p className="tc-hint">
          詳細資料的分析時間與索引不同（索引：<DualTime stamp={summary.analysis_time} />），可能尚未更新。
        </p>
      ) : null}
      <dl>
        <dt>分析時間</dt>
        <dd><DualTime stamp={fix.analysis_time} /></dd>
        <dt>發布時間</dt>
        <dd><DualTime stamp={block.issued_at} /></dd>
        {bulletin ? <><dt>報次</dt><dd>{bulletin}</dd></> : null}
        <dt>中心位置</dt>
        <dd>{formatPosition(fix.lat, fix.lon) || "—"}</dd>
        <dt>最大風速</dt>
        <dd>{formatWind(agency, fix.max_wind) || "—"}</dd>
        <dt>陣風</dt>
        <dd>{formatGust(fix.gust) || "—"}</dd>
        <dt>中心氣壓</dt>
        <dd>{formatPressure(fix.pressure_hpa) || "—"}</dd>
        <dt>移動</dt>
        <dd>{formatMovement(fix.movement) || "—"}</dd>
        {category ? <><dt>機構分類（原文）</dt><dd>{category}</dd></> : null}
        <dt>風圈</dt>
        <dd>{radii.length ? <ul className="tc-plain-list">{radii.map(text => <li key={text}>{text}</li>)}</ul> : "—"}</dd>
        <dt>過去路徑</dt>
        <dd><PastTrackLabel block={block} /></dd>
      </dl>
    </section>
  );
}

function AnalysisTab({ storm, analysis }) {
  const summaries = storm.summary && typeof storm.summary === "object" ? storm.summary : {};
  return (
    <section className="tc-section" aria-labelledby="tc-tab-title">
      <h3 id="tc-tab-title" className="tc-visually-hidden">各機構分析</h3>
      {analysis === null ? <Unavailable>各機構的詳細分析資料暫時無法取得。</Unavailable> : null}
      {analysis && analysis.fetchedAt ? (
        <p className="status-message">詳細資料產生時間：<DualTime stamp={analysis.fetchedAt} /></p>
      ) : null}
      <div className="tc-agency-grid">
        {AGENCIES.map(agency => (
          <AnalysisCard key={agency} agency={agency} state={blockState(analysis, agency)} summary={summaries[agency]} />
        ))}
      </div>
      <p className="tc-note">
        各欄只顯示機構實際提供的單位與平均期間，未換算；{INTENSITY_NOTE}
      </p>
    </section>
  );
}

export default function StormDetail({ storm, tab, sameName, cache, now = null, modelsEnabled = MODEL_LAYERS_ENABLED }) {
  const files = useStormFiles(storm.cyclone_id, cache);
  const models = useModelFiles(storm.cyclone_id, cache, modelsEnabled && tab === "forecast");
  const name = textOrNull(storm.name);
  const nameZh = textOrNull(storm.name_zh);
  const ids = formatIds(storm.ids);
  const ended = storm.status === "ended";
  const tabLink = id => `?storm=${encodeURIComponent(storm.cyclone_id)}&tab=${id}`;
  const agenciesWithData = AGENCIES.filter(agency => storm.summary && storm.summary[agency]);
  return (
    <article className="tc-detail" aria-label={name || nameZh || "未命名系統"}>
      <p><Link to="/tropical">← 回到總覽</Link></p>
      <header className="tc-storm-header">
        <h3>
          {name || "未命名系統"}
          {nameZh ? <span className="tc-name-zh">{nameZh}</span> : null}
        </h3>
        <span className={`status-badge ${ended ? "status-badge-empty" : "status-badge-fresh"}`}>
          {ended ? "已結束" : "活躍"}
        </span>
      </header>
      <p className="tc-ids">編號：{ids.length ? ids.join("｜") : "—"}</p>
      {ended ? (
        <p className="tc-hint">此系統已結束（結束判定時間：<DualTime stamp={storm.ended_at} />），以下為最後保存的資料。</p>
      ) : null}
      {sameName ? <p className="tc-hint">可能為同一系統：另有同名的系統並列，各機構的資料尚未合併。</p> : null}
      {agenciesWithData.length === 1 ? (
        <p className="tc-hint">目前只有 {AGENCY_SHORT[agenciesWithData[0]]} 有這個系統的資料。</p>
      ) : null}
      <nav className="tc-tabs" aria-label="系統資料分頁">
        {TABS.map(item => (
          <Link key={item.id} to={tabLink(item.id)} className="tc-tab"
            aria-current={item.id === tab ? "page" : undefined}>{item.label}</Link>
        ))}
      </nav>
      <TabBoundary key={tab}>
        {tab === "overview" ? <OverviewTab storm={storm} analysis={files.analysis} /> : null}
        {tab === "analysis" ? <AnalysisTab storm={storm} analysis={files.analysis} /> : null}
        {tab === "forecast" ? (
          <ForecastPanel analysis={files.analysis} forecast={files.forecast} storm={storm} now={now}
            models={modelsEnabled ? models : null} />
        ) : null}
        {tab === "imagery" ? <p className="status-message">圖像分頁尚未開放。</p> : null}
      </TabBoundary>
    </article>
  );
}
