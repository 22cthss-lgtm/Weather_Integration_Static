// Forecast tab: official tracks (design.md 7.2–7.5) and, behind the build switch, deterministic
// model tracks as separate layers (design.md 7.7, 11e E3/E4, 11f). Ensembles are S9–S10.
import { Component, lazy, Suspense, useMemo, useState } from "react";
import { AGENCIES } from "../../tropical/status";
import {
  ANALYSIS_KEY, buildTimeline, buildTracks, defaultToggles, drawables, entriesAt, findNode, initTimes,
} from "../../tropical/tracks";
import {
  AGENCY_LABELS, AGENCY_SHORT, formatDualTime, formatGust, formatMovement, formatNote, formatPosition,
  formatPressure, formatProbabilityCircle, formatRadii, formatTau, formatWind, textOrNull,
} from "../../tropical/format";
import {
  MODELS, MODEL_COLORS, MODEL_INFO, MODEL_LEGEND, buildModelTracks, defaultModelToggles, enabledModelTracks,
  findModelNode, formatModelWind, isModelDataStale,
} from "../../tropical/models";
import { DualTime, INTENSITY_NOTE } from "./common";

// Leaflet, its CSS and the coastline load only when this tab opens (design.md 7.1, 7.2).
const TrackMap = lazy(() => import("./TrackMap"));

export const AGENCY_COLORS = { jtwc: "#d9480f", jma: "#1864ab", cwa: "#2b8a3e" };
const MAP_COLORS = { ...AGENCY_COLORS, ...MODEL_COLORS };

const LAYER_LABELS = {
  past: "過去路徑",
  forecast: "最新分析與預報路徑",
  circles: "機率圓（JMA 預報圓、CWA 70% 半徑）",
  radii: "最新分析的風圈",
};

const KIND_LABELS = { past: "過去路徑點", fix: "最新分析", forecast: "預報點" };

class MapBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) return <p className="tc-unavailable" role="note">地圖暫時無法載入；下方的時間軸與節點資料仍可使用。</p>;
    return this.props.children;
  }
}

function statusNote(track) {
  if (track.analysisStatus === "loading" || track.forecastStatus === "loading") return ["讀取中…"];
  if (track.analysisStatus === "missing" && track.forecastStatus === "missing") return ["沒有這個系統的資料"];
  const notes = [];
  if (track.analysisStatus === "unavailable" || track.analysisStatus === "invalid") notes.push("分析資料暫時無法取得");
  if (track.analysisStatus === "missing") notes.push("沒有分析資料");
  if (track.forecastStatus === "unavailable" || track.forecastStatus === "invalid") notes.push("預報資料暫時無法取得");
  if (track.forecastStatus === "missing") notes.push("沒有預報資料");
  if (track.forecastStatus === "ok" && !track.points.length) notes.push("這一報沒有預報點");
  return notes;
}

function shortTime(stamp) {
  const time = formatDualTime(stamp);
  return time ? `${time.utc.slice(5)}（臺灣 ${time.taipei.slice(5)}）` : "—";
}

function InitTimes({ tracks, modelInit }) {
  const withForecast = tracks.filter(track => track.points.length);
  const official = initTimes(tracks);
  const differ = official.length > 1;
  const modelDiffers = Boolean(modelInit) && official.some(time => time !== modelInit);
  return (
    <section className="tc-init" aria-labelledby="tc-init-title">
      <h4 id="tc-init-title">各機構的起報時間</h4>
      {withForecast.length ? (
        <ul className="tc-plain-list">
          {withForecast.map(track => (
            <li key={track.agency}>
              <span className="tc-swatch" style={{ background: AGENCY_COLORS[track.agency] }} aria-hidden="true" />
              {AGENCY_SHORT[track.agency]}：起報 <DualTime stamp={track.initTime} />；發布 <DualTime stamp={track.forecastIssuedAt} />
              {textOrNull(track.forecastBulletin) ? `；報次 ${track.forecastBulletin}` : ""}
            </li>
          ))}
        </ul>
      ) : <p className="status-message">目前沒有任何機構的預報點。</p>}
      {differ ? (
        <p className="tc-hint" role="note">
          各機構的起報時間不同：同一有效時間的位置來自不同時刻起報的預報，不是同一時刻的比較。
        </p>
      ) : null}
      {modelInit ? (
        <p className="status-message">已開啟的數值模式起報時間（cycle）：<DualTime stamp={modelInit} /></p>
      ) : null}
      {modelDiffers ? (
        <p className="tc-hint" role="note">
          已開啟的數值模式起報時間（cycle）與官方起報時間不同：同一有效時間的位置來自不同時刻起報的資料，不是同一時刻的比較。
        </p>
      ) : null}
    </section>
  );
}

function Timeline({ timeline, tracks, modelTracks, selectedKey, onSelectKey, onSelectNode }) {
  const steps = [timeline.analysis, ...timeline.ticks];
  const entries = selectedKey === null ? [] : entriesAt(timeline, selectedKey);
  const shown = tracks.filter(track => track.fix || track.points.length);
  return (
    <section className="tc-timeline" aria-labelledby="tc-timeline-title">
      <h4 id="tc-timeline-title">有效時間軸</h4>
      <p className="status-message">
        刻度是各機構實際的預報有效時間（UTC），沒有節點的時刻不補值。
        {modelTracks.length ? "已開啟的數值模式也加入它們實際輸出的時刻。" : null}
      </p>
      <div className="tc-ticks" role="group" aria-label="選擇有效時間">
        {steps.map(step => {
          const agencies = new Set(step.entries.map(entry => entry.agency));
          const models = new Set(step.entries.map(entry => entry.model).filter(Boolean));
          return (
            <button key={step.key} type="button" className="tc-tick" aria-pressed={selectedKey === step.key}
              onClick={() => onSelectKey(selectedKey === step.key ? null : step.key)}>
              <span className="tc-tick-time">
                {step.key === ANALYSIS_KEY ? "最新分析" : shortTime(step.time)}
              </span>
              <span className="tc-tick-agencies">
                {AGENCIES.filter(agency => agencies.has(agency)).map(agency => (
                  <span key={agency} className="tc-tick-agency" style={{ color: AGENCY_COLORS[agency] }}>
                    {AGENCY_SHORT[agency]}
                  </span>
                ))}
                {MODELS.filter(model => models.has(model)).map(model => (
                  <span key={model} className="tc-tick-agency tc-tick-model" style={{ color: MODEL_COLORS[model] }}>
                    {MODEL_INFO[model].short}
                  </span>
                ))}
              </span>
            </button>
          );
        })}
      </div>
      {selectedKey !== null ? (
        <div className="tc-tick-detail" aria-live="polite">
          {selectedKey !== ANALYSIS_KEY && new Set(entries.map(entry => entry.initTime)).size > 1 ? (
            <p className="tc-hint">這一刻的節點來自不同的起報時間，不是同一時刻起報的比較。</p>
          ) : null}
          <p>
            {selectedKey === ANALYSIS_KEY
              ? "最新分析：各機構的分析時間各自不同，逐一列出。"
              : <>有效時間：<DualTime stamp={selectedKey} /></>}
          </p>
          <ul className="tc-plain-list">
            {shown.map(track => {
              const entry = entries.find(item => item.agency === track.agency);
              return (
                <li key={track.agency}>
                  <span className="tc-swatch" style={{ background: AGENCY_COLORS[track.agency] }} aria-hidden="true" />
                  {entry ? (
                    <>
                      {AGENCY_SHORT[track.agency]}{" "}
                      {entry.tauH === null
                        ? <>分析時間 <DualTime stamp={entry.time} /></>
                        : <>{formatTau(entry.tauH)}（起報 {shortTime(entry.initTime)}）</>}
                      {" "}
                      <button type="button" className="tc-link-button" onClick={() => onSelectNode(entry.nodeId)}>
                        查看節點
                      </button>
                    </>
                  ) : <>此時刻沒有 {AGENCY_SHORT[track.agency]} 的節點。</>}
                </li>
              );
            })}
            {selectedKey === ANALYSIS_KEY ? null : modelTracks.map(track => {
              const entry = entries.find(item => item.model === track.model);
              const short = MODEL_INFO[track.model].short;
              return (
                <li key={track.model}>
                  <span className="tc-swatch tc-swatch-model" style={{ borderColor: MODEL_COLORS[track.model] }}
                    aria-hidden="true" />
                  {entry ? (
                    <>
                      {short} 起報後 {formatTau(entry.tauH)}（cycle {shortTime(entry.initTime)}）{" "}
                      <button type="button" className="tc-link-button" onClick={() => onSelectNode(entry.nodeId)}>
                        查看節點
                      </button>
                    </>
                  ) : <>此時刻沒有 {short} 的節點。</>}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function ModelNodeDetail({ node }) {
  const info = MODEL_INFO[node.model];
  return (
    <section className="tc-agency tc-node" aria-label="節點細節">
      <h5>{info.label}｜數值模式節點</h5>
      <p className="tc-note">{MODEL_LEGEND}</p>
      <dl>
        <dt>提供者</dt>
        <dd>{info.provider}</dd>
        <dt>模式起報時間（cycle）</dt>
        <dd><DualTime stamp={node.initTime} /></dd>
        <dt>時效</dt>
        <dd>起報後 {formatTau(node.tauH)}</dd>
        <dt>有效時間</dt>
        <dd><DualTime stamp={node.time} /></dd>
        <dt>中心位置</dt>
        <dd>{formatPosition(node.lat, node.lon) || "—"}</dd>
        <dt>中心氣壓</dt>
        <dd>{formatPressure(node.pressure) || "—"}</dd>
        <dt>風速</dt>
        <dd>{formatModelWind(node.wind, node.windUnit) || "—"}</dd>
      </dl>
      <p className="tc-note">模式風速是模式輸出的 10 m 最大風，與機構的平均風速定義不同，不可比較。</p>
    </section>
  );
}

const MODEL_STATUS_NOTES = { missing: "這個 cycle 沒有此模式", invalid: "此模式的資料暫時無法取得" };

function ModelLayers({ models, modelTracks, toggles, onToggle, storm, now }) {
  let message = null;
  if (models.status === "loading") message = <p className="status-message">數值模式資料讀取中…</p>;
  else if (models.status === "unavailable") {
    message = <p className="tc-unavailable" role="note">數值模式資料暫時無法取得；官方路徑不受影響。</p>;
  } else if (models.status === "none") message = <p className="status-message">目前沒有這個系統的數值模式資料。</p>;
  const ok = models.status === "ok";
  const stale = ok && isModelDataStale(storm, models.file.initTime, now);
  return (
    <fieldset className="tc-layers tc-models">
      <legend>數值模式路徑（原始輸出）</legend>
      <p className="tc-note"><strong>{MODEL_LEGEND}</strong>各模式預設關閉，可自行開啟比較。</p>
      {message}
      {ok ? <p className="status-message">模式起報時間（cycle）：<DualTime stamp={models.file.initTime} /></p> : null}
      {stale ? (
        <p className="tc-hint" role="note">模式資料可能未更新：最新的模式起報時間距今已超過 18 小時。</p>
      ) : null}
      <div className="tc-layer-row">
        {MODELS.map(model => {
          const track = modelTracks.find(item => item.model === model);
          const has = Boolean(track && track.points.length);
          const note = track ? MODEL_STATUS_NOTES[track.status] : null;
          return (
            <label key={model} className="tc-check">
              <input type="checkbox" checked={has && toggles[model]} disabled={!has} onChange={() => onToggle(model)} />
              <span className="tc-swatch tc-swatch-model" style={{ borderColor: MODEL_COLORS[model] }} aria-hidden="true" />
              {MODEL_INFO[model].label}
              {note ? <span className="tc-check-note">（{note}）</span> : null}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function NodeDetail({ node, track }) {
  if (node && node.kind === "model") return <ModelNodeDetail node={node} />;
  if (!node) return <p className="status-message">點選地圖上的節點，或在時間軸選擇時刻後按「查看節點」，可看到該點的細節。</p>;
  const category = textOrNull(node.category);
  const circle = formatProbabilityCircle(node.agency, node.probabilityCircle);
  const note = formatNote(node.note);
  const radii = node.radii.map(formatRadii).filter(Boolean);
  const movement = node.kind === "fix" ? formatMovement(node.movement) : null;
  const gust = formatGust(node.gust);
  return (
    <section className="tc-agency tc-node" aria-label="節點細節">
      <h5>{AGENCY_LABELS[node.agency]}｜{KIND_LABELS[node.kind]}</h5>
      <dl>
        <dt>{node.kind === "forecast" ? "有效時間" : "分析時間"}</dt>
        <dd><DualTime stamp={node.time} /></dd>
        {node.kind === "forecast" ? (
          <>
            <dt>預報時效</dt>
            <dd>{formatTau(node.tauH)}（起報 <DualTime stamp={track.initTime} />）</dd>
          </>
        ) : null}
        <dt>中心位置</dt>
        <dd>{formatPosition(node.lat, node.lon) || "—"}</dd>
        <dt>最大風速</dt>
        <dd>{formatWind(node.agency, node.maxWind) || "—"}</dd>
        {gust ? <><dt>陣風</dt><dd>{gust}</dd></> : null}
        <dt>中心氣壓</dt>
        <dd>{formatPressure(node.pressure) || "—"}</dd>
        {category ? <><dt>機構分類（原文）</dt><dd>{category}</dd></> : null}
        {movement ? <><dt>移動</dt><dd>{movement}</dd></> : null}
        {circle ? <><dt>機率圓</dt><dd>{circle}</dd></> : null}
        {radii.length ? (
          <><dt>風圈</dt><dd><ul className="tc-plain-list">{radii.map(text => <li key={text}>{text}</li>)}</ul></dd></>
        ) : null}
        {note ? <><dt>機構註記</dt><dd>{note}</dd></> : null}
      </dl>
    </section>
  );
}

/**
 * @param models null when the build switch is off (no model section at all), else the state from
 *   StormDetail's useModelFiles: {status: "loading" | "unavailable" | "none"} or {status: "ok", cycle, file}
 * @param now the page clock (ms), used only for the model freshness hint
 */
export default function ForecastPanel({ analysis, forecast, storm = null, now = null, models = null }) {
  const tracks = useMemo(() => buildTracks(analysis, forecast), [analysis, forecast]);
  const modelTracks = useMemo(() => buildModelTracks(models), [models]);
  const [toggles, setToggles] = useState(defaultToggles);
  const [modelToggles, setModelToggles] = useState(defaultModelToggles);
  const shownModels = useMemo(() => enabledModelTracks(modelTracks, modelToggles), [modelTracks, modelToggles]);
  const timeline = useMemo(() => buildTimeline(tracks, shownModels), [tracks, shownModels]);
  const [chosenKey, setSelectedKey] = useState(null);
  const [chosenNodeId, setSelectedNodeId] = useState(null);
  // A tick or node that belonged to a model layer just switched off is no longer selected.
  const selectedKey = chosenKey === null || chosenKey === ANALYSIS_KEY
    || timeline.ticks.some(tick => tick.key === chosenKey) ? chosenKey : null;
  const selectedNode = chosenNodeId ? findNode(tracks, chosenNodeId) || findModelNode(shownModels, chosenNodeId) : null;
  const selectedNodeId = selectedNode ? chosenNodeId : null;
  const items = useMemo(() => drawables(tracks, toggles, selectedKey, selectedNodeId, shownModels),
    [tracks, toggles, selectedKey, selectedNodeId, shownModels]);
  const selectedTrack = selectedNode && selectedNode.kind !== "model"
    ? tracks.find(track => track.agency === selectedNode.agency) : null;
  const modelInit = shownModels.length ? shownModels[0].initTime : null;

  const selectNode = nodeId => {
    const found = findNode(tracks, nodeId) || findModelNode(shownModels, nodeId);
    setSelectedNodeId(nodeId);
    if (found) {
      setSelectedKey(found.kind === "fix" ? ANALYSIS_KEY
        : found.kind === "forecast" || found.kind === "model" ? found.time : null);
    }
  };
  const toggle = (group, key) => setToggles(current => ({
    ...current, [group]: { ...current[group], [key]: !current[group][key] },
  }));
  const toggleModel = model => {
    const next = { ...modelToggles, [model]: !modelToggles[model] };
    setModelToggles(next);
    if (next[model]) return;
    // Forget a selection that belonged to the model switched off, so switching it on again does
    // not bring it back.
    if (chosenNodeId && chosenNodeId.startsWith(`model:${model}:`)) setSelectedNodeId(null);
    if (chosenKey !== null && chosenKey !== ANALYSIS_KEY) {
      const remaining = buildTimeline(tracks, enabledModelTracks(modelTracks, next));
      if (!remaining.ticks.some(tick => tick.key === chosenKey)) setSelectedKey(null);
    }
  };

  return (
    <section className="tc-section" aria-labelledby="tc-tab-title">
      <h3 id="tc-tab-title" className="tc-visually-hidden">預報路徑</h3>
      {analysis === null && forecast === null ? (
        <p className="tc-unavailable" role="note">此系統的分析與預報資料暫時無法取得。</p>
      ) : null}
      <fieldset className="tc-layers">
        <legend>圖層</legend>
        <div className="tc-layer-row">
          {tracks.map(track => {
            const notes = statusNote(track);
            const has = Boolean(track.fix || track.points.length);
            return (
              <label key={track.agency} className="tc-check">
                <input type="checkbox" checked={toggles.agencies[track.agency]} disabled={!has}
                  onChange={() => toggle("agencies", track.agency)} />
                <span className="tc-swatch" style={{ background: AGENCY_COLORS[track.agency] }} aria-hidden="true" />
                {AGENCY_SHORT[track.agency]}
                {notes.length ? <span className="tc-check-note">（{notes.join("；")}）</span> : null}
              </label>
            );
          })}
        </div>
        <div className="tc-layer-row">
          {Object.entries(LAYER_LABELS).map(([layer, label]) => (
            <label key={layer} className="tc-check">
              <input type="checkbox" checked={toggles.layers[layer]} onChange={() => toggle("layers", layer)} />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      {models ? (
        <ModelLayers models={models} modelTracks={modelTracks} toggles={modelToggles} onToggle={toggleModel}
          storm={storm} now={now} />
      ) : null}
      <MapBoundary>
        <Suspense fallback={<div className="tc-map tc-map-loading" role="status">地圖載入中…</div>}>
          <TrackMap items={items} colors={MAP_COLORS} onSelectNode={selectNode}
            ready={analysis !== undefined && forecast !== undefined} />
        </Suspense>
      </MapBoundary>
      <ul className="tc-legend tc-plain-list">
        <li>實線：過去路徑；虛線：預報路徑；大圓點：最新分析。</li>
        <li>淡色圓：機構的機率圓（JMA 預報圓為颱風中心進入的機率範圍，CWA 為 70% 機率半徑），<strong>不是暴風範圍</strong>。</li>
        <li>扇形：最新分析的風圈（依機構門檻與單位）；只畫四象限或全域的風圈，其他形式只列在文字中。</li>
        <li>past_track 標為「本站累積」的機構，過去路徑只含本站開始觀察後的紀錄。</li>
        {models ? <li>點線與空心圓：數值模式路徑。<strong>{MODEL_LEGEND}</strong></li> : null}
      </ul>
      <p className="tc-note">{INTENSITY_NOTE}</p>
      <InitTimes tracks={tracks} modelInit={modelInit} />
      <Timeline timeline={timeline} tracks={tracks} modelTracks={shownModels} selectedKey={selectedKey}
        onSelectKey={key => { setSelectedKey(key); setSelectedNodeId(null); }} onSelectNode={selectNode} />
      <NodeDetail node={selectedNode} track={selectedTrack} />
    </section>
  );
}
