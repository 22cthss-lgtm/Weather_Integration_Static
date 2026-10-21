import { useEffect, useState } from "react";
import { fetchLatestImage } from "../api";

const SEA_ICE_COLLECTIONS = {
  seaice_arctic: {
    heading: "NSIDC Arctic Sea Ice",
    tabs: [
      { id: "extent", imageType: "seaice_arctic_extent", label: "Sea Ice Extent" },
      { id: "concentration", imageType: "seaice_arctic_concentration", label: "Sea Ice Concentration" },
      { id: "timeseries", imageType: "seaice_arctic_timeseries", label: "Time Series" },
    ],
  },
  seaice_antarctic: {
    heading: "NSIDC Antarctic Sea Ice",
    tabs: [
      { id: "extent", imageType: "seaice_antarctic_extent", label: "Sea Ice Extent" },
      { id: "concentration", imageType: "seaice_antarctic_concentration", label: "Sea Ice Concentration" },
      { id: "timeseries", imageType: "seaice_antarctic_timeseries", label: "Time Series" },
    ],
  },
};

function getSeaIceEntry(images, tab) {
  return images.find((entry) => entry.image_type === tab.imageType) || images[0];
}

export default function SeaIcePage({ type }) {
  const collection = SEA_ICE_COLLECTIONS[type];
  const [image, setImage] = useState(null);
  const [error, setError] = useState("");
  const [activeTabId, setActiveTabId] = useState(collection?.tabs[0]?.id || "");

  useEffect(() => {
    async function load() {
      try {
        setError("");
        setImage(null);

        const result = await fetchLatestImage(type);
        setImage(result);
      } catch (err) {
        setError(err.message);
      }
    }

    load();
  }, [type]);

  useEffect(() => {
    setActiveTabId(collection?.tabs[0]?.id || "");
  }, [collection]);

  if (!collection) {
    return <p>Unsupported sea ice collection: {type}</p>;
  }

  if (error) {
    return <p>{error}</p>;
  }

  if (!image) {
    return <p>Loading...</p>;
  }

  if (!Array.isArray(image.images) || !image.images.length) {
    return <p>No sea ice images available.</p>;
  }

  const activeTab = collection.tabs.find((tab) => tab.id === activeTabId) || collection.tabs[0];
  const activeEntry = getSeaIceEntry(image.images, activeTab);
  const tabPanelId = `${type}-tab-panel`;

  return (
    <section>
      <h2>{collection.heading}</h2>
      <div className="image-meta-row">
        <p>Source: {image.source}
          <a className="source-link" href={image.source_url} target="_blank" rel="noreferrer">
          Original source
        </a>
        </p>
      </div>
      <p>{activeEntry.image_time ? `Image Time: ${activeEntry.image_time}` : `Fetched At: ${activeEntry.fetched_at}`}</p>

      <div className="image-tabs" role="tablist" aria-label={`${collection.heading} views`}>
        {collection.tabs.map((tab) => {
          const isActive = activeTab.id === tab.id;

          return (
            <button
              className={isActive ? "image-tab active" : "image-tab"}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-controls={tabPanelId}
              id={`${type}-tab-${tab.id}`}
              key={tab.id}
              onClick={() => setActiveTabId(tab.id)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <article
        className="image-panel image-tab-panel"
        role="tabpanel"
        id={tabPanelId}
        aria-labelledby={`${type}-tab-${activeTab.id}`}
      >
        <img className="detail-image" src={activeEntry.image_url} alt={activeEntry.title} />
      </article>
    </section>
  );
}
