import { formatImageDate, formatImageTime, formatImageTitle } from "../image-time";
import { useEffect, useState } from "react";
import { fetchDailyImages, fetchRainfallTop } from "../api";
import useCurrentImage, { taipeiDate } from "../useCurrentImage";
import SourceImage from "../SourceImage";

const rainfallMetrics = [
  { key: "10min", label: "10 Min" },
  { key: "1hr", label: "1 Hr" },
  { key: "3hr", label: "3 Hr" },
  { key: "6hr", label: "6 Hr" },
  { key: "12hr", label: "12 Hr" },
  { key: "24hr", label: "24 Hr" },
  { key: "1day", label: "Since Yesterday" },
  { key: "2days", label: "Since 2 Days Ago" },
];

function formatObservedAt(observedAt) {
  if (!observedAt) {
    return "-";
  }

  return formatDateTimeTaiwan(observedAt);
}

  function formatDateTimeTaiwan(value) {
    if (!value) {
      return "-";
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }

    return new Intl.DateTimeFormat("zh-TW", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
      .format(date)
      .replace(/\//g, "-");
  }

export default function RainFallPage() {
  const { image, error, history: rainfallHistory, selectedTime: selectedRainfallTime,
    setSelectedTime: setSelectedRainfallTime, selected: selectedRainfall, status } = useCurrentImage("rainfall");
  const [selectedMetric, setSelectedMetric] = useState("10min");
  const [rainfallTop, setRainfallTop] = useState(null);
  const [rainfallTopError, setRainfallTopError] = useState("");
  const [isRainfallTopLoading, setIsRainfallTopLoading] = useState(false);
  const [rainfallDailyImages, setRainfallDailyImages] = useState([]);
  const [dailyError, setDailyError] = useState("");

  useEffect(() => {
    let active = true;
    fetchDailyImages("rainfall").then(items => {
      if (active) setRainfallDailyImages(items);
    }).catch(() => { if (active) setDailyError("官方今日／昨日／前日雨量圖讀取失敗。"); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    setIsRainfallTopLoading(true);
    setRainfallTopError("");
    fetchRainfallTop(selectedMetric).then(ranking => {
      if (active) setRainfallTop(ranking);
    }).catch(err => {
      if (active) { setRainfallTop(null); setRainfallTopError(err.message); }
    }).finally(() => { if (active) setIsRainfallTopLoading(false); });
    return () => { active = false; };
  }, [selectedMetric]);

  const previousDailyImages = rainfallDailyImages.filter(entry => entry.label === "昨日" || entry.label === "前日");

  return (
    <section>
      {image ? <>
      <h2>{formatImageTitle(selectedRainfall)}</h2>
      <div className="image-meta-row">
        <p>Source: {selectedRainfall.source}</p>
        <a className="source-link" href={selectedRainfall.source_url} target="_blank" rel="noreferrer">
          Original source
            </a>
      </div>
      <p>{selectedRainfall.image_time ? `Image Time: ${formatImageTime(selectedRainfall.image_time)}` : `Fetched At: ${formatImageTime(selectedRainfall.fetched_at)}`}</p>
      </> : <p>{error || "Loading..."}</p>}
      <div className="detail-layout">
        {image ? <>
        <div className="controls">
          <label className="time-select">
            <span>Available Rainfall Images (Taipei date)</span>
            <select
              value={selectedRainfallTime}
              onChange={(event) => setSelectedRainfallTime(event.target.value)}
              disabled={!rainfallHistory.length}
            >
              {rainfallHistory.map((entry) => (
                <option value={entry.image_time} key={`${entry.image_type}-${entry.image_time}`}>
                  {formatImageTime(entry.image_time)}
                </option>
              ))}
            </select>
          </label>
          <p className="status-message status" aria-live="polite">
            {status}
          </p>
        </div>
        <SourceImage image={selectedRainfall} />
        </> : null}
        {previousDailyImages.length ? (
          <section className="rainfall-daily-section" aria-label="Daily rainfall representatives">
            <div className="rainfall-daily-grid">
              {previousDailyImages.map((entry) => (
                <article className="image-panel rainfall-daily-card" key={`${entry.label}-${entry.image_time}`}>
                  <p>{entry.label} {formatImageDate(entry.represented_date)}</p>
                  <SourceImage image={entry} className="detail-image rainfall-daily-image" alt={`${entry.label} ${formatImageDate(entry.represented_date)}`} />
                </article>
              ))}
            </div>
          </section>
        ) : null}
      </div>
      {dailyError ? <p className="status-message">{dailyError}</p> : null}
      {rainfallDailyImages.length && rainfallDailyImages[0].represented_date !== taipeiDate()
        ? <p className="status-message">單日雨量圖尚未更新至今日；請依圖上標示的實際日期判讀。</p> : null}
      <section className="rainfall-monitoring-section" aria-labelledby="rainfall-monitoring-heading">
        <div className="rainfall-monitoring-header">
          <div>
            <h3 id="rainfall-monitoring-heading">Real-time Rainfall Monitoring</h3>
            {rainfallTop?.fetched_at ? <p style={{marginTop: 18}}>Data fetched: {formatDateTimeTaiwan(rainfallTop.fetched_at)}</p> : null}
          </div>
        </div>
        <div className="image-tabs rainfall-metric-tabs" role="tablist" aria-label="Rainfall ranking metric">
          {rainfallMetrics.map((metric) => (
            <button
              className={`image-tab ${selectedMetric === metric.key ? "active" : ""}`}
              type="button"
              role="tab"
              aria-selected={selectedMetric === metric.key}
              key={metric.key}
              onClick={() => setSelectedMetric(metric.key)}
            >
              {metric.label}
            </button>
          ))}
        </div>
        <div className="rainfall-ranking-panel" role="tabpanel">
          {isRainfallTopLoading ? (
            <p className="status-message">Loading rainfall ranking...</p>
          ) : rainfallTopError ? (
            <p className="error-message">{rainfallTopError}</p>
          ) : rainfallTop?.items?.length ? (
            <div className="rainfall-ranking-table-wrap">
              <table className="rainfall-ranking-table">
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>County</th>
                    <th>Town</th>
                    <th>Station</th>
                    <th>Rainfall</th>
                    <th>Observed At</th>
                  </tr>
                </thead>
                <tbody>
                  {rainfallTop.items.map((item) => (
                    <tr key={`${item.station_id}-${item.observed_at}`}>
                      <td>{item.rank}</td>
                      <td>{item.county || "-"}</td>
                      <td>{item.town || "-"}</td>
                      <td>{item.station_name}</td>
                      <td>{Number(item.rainfall).toFixed(1)} mm</td>
                      <td>{formatObservedAt(item.observed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="status-message">No rainfall observation data available.</p>
          )}
        </div>
      </section>
    </section>
  );
}
