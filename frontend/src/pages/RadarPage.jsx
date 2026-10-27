import { formatImageTime, formatImageTitle } from "../image-time";
import useCurrentImage from "../useCurrentImage";
import SourceImage from "../SourceImage";

export default function RadarPage() {
  const { image, error, history: radarHistory, selectedTime: selectedRadarTime,
    setSelectedTime: setSelectedRadarTime, selected: selectedRadar, status } = useCurrentImage("radar");
  if (error && !image) return <p>{error}</p>;
  if (!image) return <p>Loading...</p>;

  return (
    <section>
      <h2>{formatImageTitle(selectedRadar)}</h2>
      <div className="image-meta-row">
        <p>Source: {selectedRadar.source}</p>
        <p>{selectedRadar.image_time ? `Image Time: ${formatImageTime(selectedRadar.image_time)}` : `Fetched At: ${formatImageTime(selectedRadar.fetched_at)}`}</p>
      </div>
      <div className="detail-layout">
        <div className="controls">
          <label className="time-select">
            <span>Available Radar Images (Taipei date)</span>
            <select
              value={selectedRadarTime}
              onChange={(event) => setSelectedRadarTime(event.target.value)}
              disabled={!radarHistory.length}
            >
              {radarHistory.map((entry) => (
                <option value={entry.image_time} key={`${entry.image_type}-${entry.image_time}`}>
                  {formatImageTime(entry.image_time)}
                </option>
              ))}
            </select>
          </label>
          <p className="status-message status" aria-live="polite">
            {status}
          </p>
          <p className="source-link">
            <a href={selectedRadar.source_url} target="_blank" rel="noreferrer">
              Original source
            </a>
          </p>
        </div>
        <SourceImage image={selectedRadar} />
      </div>
    </section>
  );
}
