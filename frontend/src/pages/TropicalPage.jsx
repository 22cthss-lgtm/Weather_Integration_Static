import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchTropicalOfficialIndex } from "../api";
import {
  AGENCIES, REQUIRED_AGENCIES, deriveDisplayState, isValidTropicalIndex, parseTropicalQuery,
  sameNameStormIds,
} from "../tropical/status";
import { AGENCY_LABELS, formatErrorCode, formatIds, textOrNull } from "../tropical/format";
import { AgencySummary, Attribution, Banner, DualTime } from "./tropical/common";
import StormDetail from "./tropical/StormDetail";
import "./tropical.css";

const REQUEST_TIMEOUT_MS = 15000;
const CLOCK_TICK_MS = 60000;

function stormLink(cycloneId) {
  return `?storm=${encodeURIComponent(cycloneId)}`;
}

function StormCard({ storm, sameName }) {
  const name = textOrNull(storm.name);
  const nameZh = textOrNull(storm.name_zh);
  const ids = formatIds(storm.ids);
  const summaries = storm.summary && typeof storm.summary === "object" ? storm.summary : {};
  const shown = AGENCIES.filter(agency => summaries[agency] && typeof summaries[agency] === "object");
  const ended = storm.status === "ended";
  return (
    <article className="tc-storm" id={`storm-${storm.cyclone_id}`} aria-label={name || nameZh || "未命名系統"}>
      <header className="tc-storm-header">
        <h4>
          <Link className="tc-storm-link" to={stormLink(storm.cyclone_id)}>{name || "未命名系統"}</Link>
          {nameZh ? <span className="tc-name-zh">{nameZh}</span> : null}
        </h4>
        <span className={`status-badge ${ended ? "status-badge-empty" : "status-badge-fresh"}`}>
          {ended ? "已結束" : "活躍"}
        </span>
      </header>
      {sameName ? (
        <p className="tc-hint">可能為同一系統：另有同名的系統並列，各機構的資料尚未合併。</p>
      ) : null}
      <p className="tc-ids">編號：{ids.length ? ids.join("｜") : "—"}</p>
      {ended ? (
        <p className="tc-ids">結束判定時間：<DualTime stamp={storm.ended_at} /></p>
      ) : null}
      {shown.length ? (
        <div className="tc-agency-grid">
          {shown.map(agency => <AgencySummary key={agency} agency={agency} summary={summaries[agency]} />)}
        </div>
      ) : <p className="status-message">沒有機構資料。</p>}
      <p className="tc-storm-more">
        <Link to={stormLink(storm.cyclone_id)}>查看路徑、預報與各機構分析</Link>
      </p>
    </article>
  );
}

function SourceStatus({ index, staleSources }) {
  return (
    <section className="tc-section" aria-labelledby="tc-sources-title">
      <h3 id="tc-sources-title">來源狀態</h3>
      <ul className="tc-source-list">
        {AGENCIES.map(agency => {
          const source = index.sources[agency];
          const ok = source.state === "ok";
          return (
            <li key={agency} className="tc-source">
              <div className="tc-source-name">
                {AGENCY_LABELS[agency]}
                <span className="tc-required">{REQUIRED_AGENCIES.includes(agency) ? "必要來源" : "選用來源"}</span>
              </div>
              <div>
                <span className={`status-badge ${ok ? "status-badge-fresh" : "status-badge-stale"}`}>
                  {ok ? "本次正常" : `本次失敗：${formatErrorCode(source.error_code)}`}
                </span>
                {staleSources.includes(agency) ? <span className="tc-flag">已過期</span> : null}
              </div>
              <div>最後確認：<DualTime stamp={source.last_ok_at} missing="尚無成功紀錄" /></div>
              {ok && Number.isInteger(source.active_count) ? (
                <div>本次回報活躍系統：{source.active_count}</div>
              ) : null}
            </li>
          );
        })}
      </ul>
      <p className="status-message">索引產生時間：<DualTime stamp={index.fetched_at} /></p>
    </section>
  );
}

/**
 * /tropical overview (design.md 3.4, 7.1, 7.5, 7.6). `getNow` is injectable for tests;
 * it is the only place the page reads the clock.
 */
export default function TropicalPage({ getNow = () => Date.now() }) {
  const [searchParams] = useSearchParams();
  const query = parseTropicalQuery(searchParams);
  const [result, setResult] = useState({ loading: true, index: null });
  const [now, setNow] = useState(() => getNow());
  // analysis.json / forecast.json already read in this page lifetime (design.md 7.4).
  const stormFiles = useRef(new Map());

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    fetchTropicalOfficialIndex({ signal: controller.signal })
      .then(data => (isValidTropicalIndex(data) ? data : null))
      .catch(() => null)
      .then(index => {
        if (!active) return;
        setNow(getNow());
        setResult({ loading: false, index });
      })
      .finally(() => clearTimeout(timer));
    const tick = setInterval(() => setNow(getNow()), CLOCK_TICK_MS);
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
      clearInterval(tick);
    };
    // getNow is a test seam, not a reactive input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const index = result.index;
  const storms = index ? index.storms : [];
  const selectedFound = Boolean(query.storm && storms.some(storm => storm.cyclone_id === query.storm));

  if (result.loading) {
    return (
      <section className="tc-page">
        <h2>熱帶系統專區｜西北太平洋</h2>
        <p className="status-message" role="status">讀取中…</p>
      </section>
    );
  }

  const display = deriveDisplayState(index, now);
  const sameName = sameNameStormIds(storms);
  const activeStorms = storms.filter(storm => storm.status === "active");
  const endedStorms = storms.filter(storm => storm.status === "ended");
  const hasUnnamed = storms.some(storm => !textOrNull(storm.name));

  if (display.state !== "UNAVAILABLE" && selectedFound) {
    const storm = storms.find(item => item.cyclone_id === query.storm);
    return (
      <section className="tc-page">
        <h2>熱帶系統專區｜西北太平洋</h2>
        <Banner display={display} index={index} />
        <StormDetail key={storm.cyclone_id} storm={storm} tab={query.tab} sameName={sameName.has(storm.cyclone_id)}
          cache={stormFiles.current} />
        <Attribution />
      </section>
    );
  }

  return (
    <section className="tc-page">
      <h2>熱帶系統專區｜西北太平洋</h2>
      <Banner display={display} index={index} />
      {display.state !== "UNAVAILABLE" && query.storm && !selectedFound ? (
        <p className="tc-banner tc-banner-notice" role="status">找不到這個系統，可能已結束或編號已變更。</p>
      ) : null}
      {display.state !== "UNAVAILABLE" ? (
        <>
          {activeStorms.length ? (
            <section className="tc-section" aria-labelledby="tc-active-title">
              <h3 id="tc-active-title">活躍系統</h3>
              {activeStorms.map(storm => (
                <StormCard key={storm.cyclone_id} storm={storm}
                  sameName={sameName.has(storm.cyclone_id)} />
              ))}
            </section>
          ) : null}
          {endedStorms.length ? (
            <section className="tc-section" aria-labelledby="tc-ended-title">
              <h3 id="tc-ended-title">近期結束的系統</h3>
              {endedStorms.map(storm => (
                <StormCard key={storm.cyclone_id} storm={storm}
                  sameName={sameName.has(storm.cyclone_id)} />
              ))}
            </section>
          ) : null}
          {hasUnnamed ? (
            <p className="status-message">
              未命名的系統在各機構命名前，可能由不同機構各列一筆；本站目前不會自動合併。
            </p>
          ) : null}
          <SourceStatus index={index} staleSources={display.staleSources} />
        </>
      ) : null}
      <Attribution />
    </section>
  );
}
