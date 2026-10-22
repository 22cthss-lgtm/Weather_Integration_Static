import useCurrentImage from "../useCurrentImage";
import SourceImage from "../SourceImage";

export default function SatellitePage() {
  const { image, error, history: satelliteHistory, selectedTime: selectedSatelliteTime,
    setSelectedTime: setSelectedSatelliteTime, selected: selectedSatellite, status } = useCurrentImage("satellite");
  if (error && !image) return <p>{error}</p>;
  if (!image) return <p>Loading...</p>;

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
            <span>Available Satellite Images (Taipei date)</span>
            <select
              value={selectedSatelliteTime}
              onChange={(event) => setSelectedSatelliteTime(event.target.value)}
              disabled={!satelliteHistory.length}
            >
              {satelliteHistory.map((entry) => (
                <option value={entry.image_time} key={`${entry.image_type}-${entry.image_time}`}>
                  {entry.image_time}
                </option>
              ))}
            </select>
          </label>
          <p className="status-message status" aria-live="polite">
            {status}
          </p>
          <p className="source-link">
            <a href={selectedSatellite.source_url} target="_blank" rel="noreferrer">
              Original source
            </a>
          </p>
        </div>
        <SourceImage image={selectedSatellite} />
      </div>
    </section>
  );
}
