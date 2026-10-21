import { useEffect, useState } from "react";
import { backfillImages, fetchDailyImages, fetchImageHistory, fetchLatestImage, fetchRainfallTop } from "../api";

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

function getImageDate(entry) {
  return entry?.image_time?.slice(0, 10) || "";
}

function formatBackfillSummary(summary) {
  if (!summary) {
    return "";
  }

  return `Backfill complete: ${summary.inserted} inserted, ${summary.skipped_existing} already existed, ${summary.missing} missing, ${summary.failed} failed.`;
}

function formatObservedAt(observedAt) {
  if (!observedAt) {
    return "-";
  }

  return observedAt.slice(0, 16).replace("T", " ");
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
  const [image, setImage] = useState(null);
  const [error, setError] = useState("");
  const [selectedMetric, setSelectedMetric] = useState("10min");
  const [rainfallTop, setRainfallTop] = useState(null);
  const [rainfallTopError, setRainfallTopError] = useState("");
  const [isRainfallTopLoading, setIsRainfallTopLoading] = useState(false);
  const [rainfallHistory, setRainfallHistory] = useState([]);
  const [selectedRainfallTime, setSelectedRainfallTime] = useState("");
  const [rainfallDailyImages, setRainfallDailyImages] = useState([]);
  const [isBackfilling, setIsBackfilling] = useState(false);
  const [backfillSummary, setBackfillSummary] = useState(null);

  async function loadRainfallData() {
    const latest = await fetchLatestImage("rainfall");
    const historyDate = getImageDate(latest);
    const [history, dailyImages] = historyDate
      ? await Promise.all([
          fetchImageHistory("rainfall", { date: historyDate }),
          fetchDailyImages("rainfall", { date: historyDate }),
        ])
      : [[], []];
    const selectableHistory = history.filter((entry) => !entry.image_time?.endsWith("00:00"));
    const hasLatestInHistory = selectableHistory.some((entry) => entry.image_time === latest.image_time);

    setImage(latest);
    setRainfallHistory(selectableHistory);
    setRainfallDailyImages(dailyImages);
    setSelectedRainfallTime(hasLatestInHistory ? latest.image_time : selectableHistory.at(-1)?.image_time || latest.image_time || "");
  }

  useEffect(() => {
    async function load() {
      try {
        setError("");
        setImage(null);
        setBackfillSummary(null);
        setRainfallHistory([]);
        setRainfallDailyImages([]);
        setSelectedRainfallTime("");
        await loadRainfallData();
      } catch (err) {
        setError(err.message);
      }
    }

    load();
  }, []);

  useEffect(() => {
    async function loadRainfallTop() {
      setIsRainfallTopLoading(true);
      setRainfallTopError("");

      try {
        const ranking = await fetchRainfallTop(selectedMetric);
        setRainfallTop(ranking);
      } catch (err) {
        setRainfallTop(null);
        setRainfallTopError(err.message);
      } finally {
        setIsRainfallTopLoading(false);
      }
    }

    loadRainfallTop();
  }, [selectedMetric]);

  async function handleBackfillRainfall() {
    setIsBackfilling(true);
    setError("");

    try {
      const summary = await backfillImages("rainfall", { range: "today" });
      setBackfillSummary(summary);
      await loadRainfallData();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsBackfilling(false);
    }
  }

  if (error) {
    return <p>{error}</p>;
  }

  if (!image) {
    return <p>Loading...</p>;
  }

  const selectedRainfall =
    rainfallHistory.find((entry) => entry.image_time === selectedRainfallTime) || image;
  const backfillMessage = formatBackfillSummary(backfillSummary);

  return (
    <section>
      <h2>{selectedRainfall.title}</h2>
      <div className="image-meta-row">
        <p>Source: {selectedRainfall.source}</p>
        <a className="source-link" href={selectedRainfall.source_url} target="_blank" rel="noreferrer">
          Original source
            </a>
      </div>
      <p>{selectedRainfall.image_time ? `Image Time: ${selectedRainfall.image_time}` : `Fetched At: ${selectedRainfall.fetched_at}`}</p>
      <div className="detail-layout">
        <div className="controls">
          <label className="time-select">
            <span>Today Available Rainfall Images</span>
            <select
              value={selectedRainfallTime}
              onChange={(event) => setSelectedRainfallTime(event.target.value)}
              disabled={!rainfallHistory.length}
            >
              {rainfallHistory.map((entry) => (
                <option value={entry.image_time} key={`${entry.id}-${entry.image_time}`}>
                  {entry.image_time}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary-button backfill-button"
            type="button"
            onClick={handleBackfillRainfall}
            disabled={isBackfilling}
          >
            {isBackfilling ? "Backfilling..." : "Backfill Images"}
          </button>
          <p className="status-message status" aria-live="polite">
            {backfillMessage || (rainfallHistory.length ? `${rainfallHistory.length} images available for this date.` : "No rainfall history loaded.")}
          </p>
        </div>
        <img className="detail-image cwa-detail-image" src={selectedRainfall.image_url} alt={selectedRainfall.title} />
        {rainfallDailyImages.length ? (
          <section className="rainfall-daily-section" aria-label="Daily rainfall representatives">
            <div className="rainfall-daily-grid">
              {rainfallDailyImages.map((entry) => (
                <article className="image-panel rainfall-daily-card" key={`${entry.label}-${entry.image_time}`}>
                  <p>{entry.represented_date}</p>
                  <img className="detail-image rainfall-daily-image" src={entry.image_url} alt={`${entry.label} ${entry.represented_date}`} />
                </article>
              ))}
            </div>
          </section>
        ) : null}
      </div>
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
