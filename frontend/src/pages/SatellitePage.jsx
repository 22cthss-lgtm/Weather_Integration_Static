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

export default function SatellitePage() {
  const [image, setImage] = useState(null);
  const [error, setError] = useState("");
  const [satelliteHistory, setSatelliteHistory] = useState([]);
  const [selectedSatelliteTime, setSelectedSatelliteTime] = useState("");
  const [isBackfilling, setIsBackfilling] = useState(false);
  const [backfillSummary, setBackfillSummary] = useState(null);

  async function loadSatelliteData() {
    const latest = await fetchLatestImage("satellite");
    const historyDate = getImageDate(latest);
    const history = historyDate ? await fetchImageHistory("satellite", { date: historyDate }) : [];
    const hasLatestInHistory = history.some((entry) => entry.image_time === latest.image_time);

    setImage(latest);
    setSatelliteHistory(history);
    setSelectedSatelliteTime(hasLatestInHistory ? latest.image_time : history.at(-1)?.image_time || latest.image_time || "");
  }

  useEffect(() => {
    async function load() {
      try {
        setError("");
        setImage(null);
        setBackfillSummary(null);
        setSatelliteHistory([]);
        setSelectedSatelliteTime("");
        await loadSatelliteData();
      } catch (err) {
        setError(err.message);
      }
    }
    load();
  }, []);

  async function handleBackfillSatellite() {
    setIsBackfilling(true);
    setError("");

    try {
      const summary = await backfillImages("satellite", { range: "today" });
      setBackfillSummary(summary);
      await loadSatelliteData();
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

  const selectedSatellite = satelliteHistory.find((entry) => entry.image_time === selectedSatelliteTime) || image;
  const backfillMessage = formatBackfillSummary(backfillSummary);

  return (
    <section>
      <h2>{selectedSatellite.title}</h2>
      <div className="image-meta-row">
        <p>Source: {selectedSatellite.source}</p>
        <p>{selectedSatellite.image_time ? `Image Time: ${selectedSatellite.image_time}` : `Fetched At: ${selectedSatellite.fetched_at}`}</p>
      </div>
      <div className="detail-layout">
        <div className="controls">
          <label className="time-select">
            <span>Today Available Satellite Images</span>
            <select
              value={selectedSatelliteTime}
              onChange={(event) => setSelectedSatelliteTime(event.target.value)}
              disabled={!satelliteHistory.length}
            >
              {satelliteHistory.map((entry) => (
                <option value={entry.image_time} key={`${entry.id}-${entry.image_time}`}>
                  {entry.image_time}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary-button backfill-button"
            type="button"
            onClick={handleBackfillSatellite}
            disabled={isBackfilling}
          >
            {isBackfilling ? "Backfilling..." : "Backfill Images"}
          </button>
          <p className="status-message status" aria-live="polite">
            {backfillMessage || (satelliteHistory.length ? `${satelliteHistory.length} images available for this date.` : "No satellite history loaded.")}
          </p>
          <p className="source-link">
            <a href={selectedSatellite.source_url} target="_blank" rel="noreferrer">
              Original source
            </a>
          </p>
        </div>
        <img className="detail-image cwa-detail-image" src={selectedSatellite.image_url} alt={selectedSatellite.title} />
      </div>
    </section>
  );
}
