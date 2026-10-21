import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchLatestImage } from "../api";

const categories = [
  { key: "satellite", label: "Satellite" },
  { key: "radar", label: "Radar" },
  { key: "850hpa", label: "KMA 850hPa" },
  { key: "temperature", label: "Temperature" },
  { key: "rainfall", label: "Rainfall" },
  { key: "weather_chart", label: "CWA Surface Chart" },
  { key: "tchp", label: "CWA TCHP" },
  { key: "cimss_wind_analysis", label: "CIMSS / Wind Analysis" },
  { key: "cimss_steering_flow", label: "CIMSS / Steering Flow" },
  { key: "seaice_arctic", label: "NSIDC Arctic Sea Ice Extent" },
  { key: "seaice_antarctic", label: "NSIDC Antarctic Sea Ice Extent" },
  { key: "sst", label: "JMA SST" },
];

const categoryMap = Object.fromEntries(categories.map((category) => [category.key, category]));

const sections = [
  {
    id: "taiwan-real-time-weather-overview",
    title: "Taiwan Real-Time Weather Overview",
    categoryKeys: ["satellite", "radar", "temperature", "rainfall"],
  },
  {
    id: "synoptic-weather-analysis",
    title: "Synoptic Weather Analysis",
    categoryKeys: ["weather_chart", "850hpa"],
  },
  {
    id: "ocean-and-typhoon-potential",
    title: "Ocean and Typhoon Potential",
    categoryKeys: ["tchp", "sst", "cimss_wind_analysis", "cimss_steering_flow"],
  },
  {
    id: "polar-and-climate-monitoring",
    title: "Polar and Climate Monitoring",
    categoryKeys: ["seaice_arctic", "seaice_antarctic"],
  },
];

export default function DashboardPage() {
  const [cards, setCards] = useState({});

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function getCardLabel(defaultLabel) {
    return defaultLabel;
  }

  function getCardMeta(categoryKey, card) {
    if (card.image_time) {
      return `Image Time: ${card.image_time}`;
    }

    return `Fetched At: ${card.fetched_at}`;
  }

  useEffect(() => {
    let isMounted = true;

    categories.forEach(async (category) => {
      try {
        const card = await fetchLatestImage(category.key);
        if (!isMounted) {
          return;
        }
        setCards((currentCards) => ({
          ...currentCards,
          [category.key]: card,
        }));
      } catch {
        // Keep the card in its loading state if one source is temporarily unavailable.
      }
    });

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <section className="dashboard-page">
      <section className="dashboard-hero" aria-label="Real-Time Weather Overview">
        <img src="/Hero_Section_Image.jpeg" alt="" className="dashboard-hero-image" />
        <div className="dashboard-hero-overlay">
          <div className="dashboard-hero-content">
            <h2>Real-Time Weather Overview</h2>
            <nav className="dashboard-hero-links" aria-label="Dashboard sections">
              {sections.map((section) => (
                <a href={`#${section.id}`} key={section.id}>
                  {section.title}
                </a>
              ))}
            </nav>
          </div>
        </div>
      </section>
      <div className="dashboard-sections">
        {sections.map((section) => (
          <section className="dashboard-section" id={section.id} key={section.title}>
            <h3 className="dashboard-section-title">{section.title}</h3>
            <div className="grid">
              {section.categoryKeys.map((categoryKey) => {
                const category = categoryMap[categoryKey];
                const card = cards[category.key];

                return (
                  <Link className="card" to={`/images/${category.key}`} key={category.key}>
                    <h3>{getCardLabel(category.label)}</h3>
                    {card ? (
                      <img src={card.image_url} alt={card.title} loading="lazy" decoding="async" />
                    ) : (
                      <p>Loading...</p>
                    )}
                    {card ? <p className="card-meta">{getCardMeta(category.key, card)}</p> : null}
                  </Link>
                );
              })}
            </div>
          </section>
        ))}
      </div>
      <button className="back-to-top-button" type="button" onClick={scrollToTop} aria-label="Back to top">
        ↑
      </button>
    </section>
  );
}
