import { useEffect, useState } from "react";
import { fetchLatestImage } from "../api";

const CIMSS_COLLECTIONS = {
  cimss_wind_analysis: {
    heading: "CIMSS Wind Analysis",
    tabs: [
      { id: "cimss_wind_shear", imageType: "cimss_wind_shear", label: "Wind Shear" },
      { id: "cimss_850mb_vorticity", imageType: "cimss_850mb_vorticity", label: "850mb Vorticity" },
    ],
  },
  cimss_steering_flow: {
    heading: "CIMSS Steering Flow",
    tabs: [
      { id: "cimss_steering_flow_200_700mb", imageType: "cimss_steering_flow_200_700mb", label: "200 - 700 mb" },
      { id: "cimss_steering_flow_250_850mb", imageType: "cimss_steering_flow_250_850mb", label: "250 - 850 mb" },
      { id: "cimss_steering_flow_300_850mb", imageType: "cimss_steering_flow_300_850mb", label: "300 - 850 mb" },
      { id: "cimss_steering_flow_400_850mb", imageType: "cimss_steering_flow_400_850mb", label: "400 - 850 mb" },
      { id: "cimss_steering_flow_500_850mb", imageType: "cimss_steering_flow_500_850mb", label: "500 - 850 mb" },
      { id: "cimss_steering_flow_700_850mb", imageType: "cimss_steering_flow_700_850mb", label: "700 - 850 mb" },
    ],
  },
};

function getCimssEntry(images, tab) {
  return images.find((entry) => entry.image_type === tab.imageType) || images[0];
}

export default function CimssPage({ type }) {
  const collection = CIMSS_COLLECTIONS[type];
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
    return <p>Unsupported CIMSS collection: {type}</p>;
  }

  if (error) {
    return <p>{error}</p>;
  }

  if (!image) {
    return <p>Loading...</p>;
  }

  if (!Array.isArray(image.images) || !image.images.length) {
    return <p>No cimss images available.</p>;
  }

  const activeTab = collection.tabs.find((tab) => tab.id === activeTabId) || collection.tabs[0];
  const activeEntry = getCimssEntry(image.images, activeTab);
  const tabPanelId = `${type}-tab-panel`;

  return (
    <section>
      <h2>{collection.heading}</h2>
      <div className="image-meta-row">
        <p>Source: {image.source}</p>
        <a className="source-link" href={image.source_url} target="_blank" rel="noreferrer">
          Original source
        </a>
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
      <p>

      </p>
    </section>
  );
}
