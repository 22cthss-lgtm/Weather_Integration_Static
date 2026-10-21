import { useEffect, useState } from "react";
import { backfillImages, fetchImageHistory, fetchLatestImage } from "../api";

function getImageDate(entry) {
  return entry?.image_time?.slice(0, 10) || "";
}

function formatBackfillSummary(summary) {
  if (!summary) {
    return "";
  }

  return `Backfill complete: ${summary.inserted} inserted, ${summary.skipped_existing} already existed, ${summary.missing} missing, ${summary.failed} failed.`;
}

export default function RadarPage() {
  const [image, setImage] = useState(null);
  const [error, setError] = useState("");
  const [radarHistory, setRadarHistory] = useState([]);
  const [selectedRadarTime, setSelectedRadarTime] = useState("");
  const [isBackfilling, setIsBackfilling] = useState(false);
  const [backfillSummary, setBackfillSummary] = useState(null);

  async function loadRadarData() {
    const latest = await fetchLatestImage("radar");
    const historyDate = getImageDate(latest);
    const history = historyDate ? await fetchImageHistory("radar", { date: historyDate }) : [];
    const hasLatestInHistory = history.some((entry) => entry.image_time === latest.image_time);

    setImage(latest);
    setRadarHistory(history);
    setSelectedRadarTime(hasLatestInHistory ? latest.image_time : history.at(-1)?.image_time || latest.image_time || "");
  }

  useEffect(() => {
    async function load() {
      try {
        setError("");
        setImage(null);
        setBackfillSummary(null);
        setRadarHistory([]);
        setSelectedRadarTime("");
        await loadRadarData();
      } catch (err) {
        setError(err.message);
      }
    }

    load();
  }, []);

  async function handleBackfillRadar() {
    setIsBackfilling(true);
    setError("");

    try {
      const summary = await backfillImages("radar", { range: "today" });
      setBackfillSummary(summary);
      await loadRadarData();
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

  const selectedRadar = radarHistory.find((entry) => entry.image_time === selectedRadarTime) || image;
  const backfillMessage = formatBackfillSummary(backfillSummary);

  return (
    <section>
      <h2>{selectedRadar.title}</h2>
      <div className="image-meta-row">
        <p>Source: {selectedRadar.source}</p>
        <p>{selectedRadar.image_time ? `Image Time: ${selectedRadar.image_time}` : `Fetched At: ${selectedRadar.fetched_at}`}</p>
      </div>
      <div className="detail-layout">
        <div className="controls">
          <label className="time-select">
            <span>Today Available Radar Images</span>
            <select
              value={selectedRadarTime}
              onChange={(event) => setSelectedRadarTime(event.target.value)}
              disabled={!radarHistory.length}
            >
              {radarHistory.map((entry) => (
                <option value={entry.image_time} key={`${entry.id}-${entry.image_time}`}>
                  {entry.image_time}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary-button backfill-button"
            type="button"
            onClick={handleBackfillRadar}
            disabled={isBackfilling}
          >
            {isBackfilling ? "Backfilling..." : "Backfill Images"}
          </button>
          <p className="status-message status" aria-live="polite">
            {backfillMessage || (radarHistory.length ? `${radarHistory.length} images available for this date.` : "No radar history loaded.")}
          </p>
          <p className="source-link">
            <a href={selectedRadar.source_url} target="_blank" rel="noreferrer">
              Original source
            </a>
          </p>
        </div>
        <img className="detail-image cwa-detail-image" src={selectedRadar.image_url} alt={selectedRadar.title} />
      </div>
    </section>
  );
}
