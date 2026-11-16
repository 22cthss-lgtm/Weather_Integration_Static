import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchTropicalOfficialIndex } from "../api";
import {
  AGENCIES, REQUIRED_AGENCIES, deriveDisplayState, isValidTropicalIndex, parseTropicalQuery,
  sameNameStormIds,
} from "../tropical/status";
import {
  AGENCY_LABELS, AGENCY_SHORT, formatDualTime, formatErrorCode, formatIds, formatPosition,
  formatPressure, formatWind, textOrNull,
} from "../tropical/format";
import "./tropical.css";

const REQUEST_TIMEOUT_MS = 15000;
const CLOCK_TICK_MS = 60000;

function DualTime({ stamp, missing = "—" }) {
  const time = formatDualTime(stamp);
  if (!time) return <>{missing}</>;
  return (
    <span className="tc-time">
      <span>{time.utc}</span>
      <span>臺灣 {time.taipei}</span>
    </span>
  );
}

function Banner({ display, index }) {
  if (display.state === "UNAVAILABLE") {
    return (
      <div className="tc-banner tc-banner-unavailable" role="alert">
        <strong>熱帶系統資料暫時無法取得</strong>
        <p>這不代表目前沒有熱帶系統，請稍後重新整理，或參考中央氣象署的颱風消息。</p>
      </div>
    );
  }
  const noActive = !display.hasActive;
  let detail;
  if (display.indexStatus === "PARTIAL") {
    detail = noActive
      ? "部分來源無法取得，無法確認是否有活躍系統。"
      : "部分來源無法取得：以下為取得成功的來源與先前保存的資料，可能不完整。";
  } else if (display.indexStatus === "OK_NO_STORMS") {
    detail = "目前無活躍熱帶系統。";
  } else {
    detail = "以下為各機構目前發報中的系統。";
  }

  if (display.state === "STALE") {
    const stale = display.staleSources;
    return (
      <div className="tc-banner tc-banner-stale" role="alert">
        <strong>資料可能已過期，目前狀況無法確認</strong>
        <ul className="tc-stale-list">
          {REQUIRED_AGENCIES.map(agency => (
            <li key={agency}>
              {AGENCY_SHORT[agency]} 最後確認時間：
              <DualTime stamp={index.sources[agency].last_ok_at} missing="尚無成功紀錄" />
              {stale.includes(agency) ? <span className="tc-flag">已過期</span> : null}
            </li>
          ))}
        </ul>
        <p>最後一次確認時的狀態：{display.indexStatus === "OK_NO_STORMS"
          ? "當時沒有活躍熱帶系統（已過期，不代表現在）。"
          : display.indexStatus === "OK_WITH_STORMS"
            ? "當時各機構發報中的系統如下（已過期，可能已有變化）。"
            : detail}</p>
      </div>
    );
  }
  const tone = display.state === "PARTIAL" ? "tc-banner-partial" : "tc-banner-ok";
  return (
    <div className={`tc-banner ${tone}`} role="status">
      <strong>{detail}</strong>
    </div>
  );
}

function AgencySummary({ agency, summary }) {
  const position = formatPosition(summary.lat, summary.lon);
  const wind = formatWind(agency, summary.max_wind);
  const pressure = formatPressure(summary.pressure_hpa);
  const category = textOrNull(summary.category);
  return (
    <section className="tc-agency" aria-label={AGENCY_LABELS[agency]}>
      <h5>{AGENCY_LABELS[agency]}</h5>
      <dl>
        <dt>機構判定</dt>
        <dd>{summary.active === true ? "活躍" : summary.active === false ? "已不視為活躍" : "—"}</dd>
        <dt>分析時間</dt>
        <dd><DualTime stamp={summary.analysis_time} /></dd>
        <dt>位置</dt>
        <dd>{position || "—"}</dd>
        <dt>最大風速</dt>
        <dd>{wind || "—"}</dd>
        <dt>中心氣壓</dt>
        <dd>{pressure || "—"}</dd>
        {category ? <><dt>機構分類（原文）</dt><dd>{category}</dd></> : null}
      </dl>
    </section>
  );
}

function StormCard({ storm, selected, sameName }) {
  const name = textOrNull(storm.name);
  const nameZh = textOrNull(storm.name_zh);
  const ids = formatIds(storm.ids);
  const summaries = storm.summary && typeof storm.summary === "object" ? storm.summary : {};
  const shown = AGENCIES.filter(agency => summaries[agency] && typeof summaries[agency] === "object");
  const ended = storm.status === "ended";
  return (
    <article
      className={`tc-storm${selected ? " tc-storm-selected" : ""}`}
      id={`storm-${storm.cyclone_id}`}
      aria-current={selected ? "true" : undefined}
      aria-label={name || nameZh || "未命名系統"}
    >
      <header className="tc-storm-header">
        <h4>
          {name || "未命名系統"}
          {nameZh ? <span className="tc-name-zh">{nameZh}</span> : null}
        </h4>
        <span className={`status-badge ${ended ? "status-badge-empty" : "status-badge-fresh"}`}>
          {ended ? "已結束" : "活躍"}
        </span>
      </header>
      {sameName ? (
        <p className="tc-hint">可能為同一系統：另有同名的系統並列，各機構的資料尚未合併。</p>
      ) : null}
      {selected ? <p className="tc-hint">已選取此系統。個別系統頁尚未開放，目前只提供總覽。</p> : null}
      <p className="tc-ids">編號：{ids.length ? ids.join("｜") : "—"}</p>
      {ended ? (
        <p className="tc-ids">結束判定時間：<DualTime stamp={storm.ended_at} /></p>
      ) : null}
      {shown.length ? (
        <div className="tc-agency-grid">
          {shown.map(agency => <AgencySummary key={agency} agency={agency} summary={summaries[agency]} />)}
        </div>
      ) : <p className="status-message">沒有機構資料。</p>}
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

function Attribution() {
  return (
    <footer className="tc-attribution" aria-labelledby="tc-attribution-title">
      <h3 id="tc-attribution-title">資料來源與署名（暫定文字，正式版本待定稿）</h3>
      <ul>
        <li>
          <strong>JTWC：</strong>本頁含美國聯合颱風警報中心（JTWC）資料，該資料不受著作權保護（17 U.S.C. §403）。
          JTWC 產品主要供美國政府機關使用，一般使用者請以本國氣象機關與區域專業氣象中心的資訊為準（臺灣以中央氣象署為準）。
          本站未修改其內容後宣稱著作權。
        </li>
        <li>
          <strong>JMA：</strong>出典：気象庁ホームページ（
          <a href="https://www.jma.go.jp/" target="_blank" rel="noreferrer">https://www.jma.go.jp/</a>
          ）。本頁的表格是以氣象廳資料加工作成（気象庁のデータを加工して作成）；本站與日本政府無關，內容並非日本政府製作。
        </li>
        <li>
          <strong>CWA：</strong>提供機關：交通部中央氣象署；資料：颱風消息資料集 W-C0034-005（正式資料名稱待確認）；
          依「政府資料開放授權條款」使用。CWA 風速的平均期間依慣例視為 10 分鐘，尚未經官方文件確認。
        </li>
        <li>
          強度不可跨機構比較：JTWC 為 1 分鐘平均風速，JMA 與 CWA 為 10 分鐘平均風速；分類為各機構原文，未做對照。
          本頁不排序、不平均各機構的數值。
        </li>
      </ul>
    </footer>
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

  useEffect(() => {
    if (!selectedFound) return;
    const element = document.getElementById(`storm-${query.storm}`);
    element?.scrollIntoView?.({ block: "start" });
  }, [selectedFound, query.storm]);

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
                  selected={storm.cyclone_id === query.storm} sameName={sameName.has(storm.cyclone_id)} />
              ))}
            </section>
          ) : null}
          {endedStorms.length ? (
            <section className="tc-section" aria-labelledby="tc-ended-title">
              <h3 id="tc-ended-title">近期結束的系統</h3>
              {endedStorms.map(storm => (
                <StormCard key={storm.cyclone_id} storm={storm}
                  selected={storm.cyclone_id === query.storm} sameName={sameName.has(storm.cyclone_id)} />
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
