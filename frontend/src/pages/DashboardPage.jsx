import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchLatestImage } from "../api";
import { formatImageTime } from "../image-time";

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
  const [unavailable, setUnavailable] = useState({});

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function getCardLabel(defaultLabel) {
    return defaultLabel;
  }

  function getCardMeta(categoryKey, card) {
    if (card.image_time) {
      return `Image Time: ${formatImageTime(card.image_time)}`;
    }

    return `Fetched At: ${formatImageTime(card.fetched_at)}`;
  }

  useEffect(() => {
    let isMounted = true;
    const timers = new Set();
    const controllers = new Set();

    categories.forEach(async (category) => {
      let timer;
      const controller = new AbortController();
      controllers.add(controller);
      try {
        const card = await Promise.race([
          fetchLatestImage(category.key, { signal: controller.signal }),
          new Promise((_, reject) => {
            timer = setTimeout(() => {
              controller.abort();
              reject(new Error("Published data request timed out"));
            }, 15000);
            timers.add(timer);
          }),
        ]);
        if (!card || typeof card.title !== "string" || !card.title.trim()
            || typeof card.image_url !== "string" || !/^https?:\/\//i.test(card.image_url)
            || (card.image_type && card.image_type !== category.key)
            || Number.isNaN(new Date(card.image_time || card.fetched_at).getTime())) {
          throw new Error("Invalid published image metadata");
        }
        if (!isMounted) {
          return;
        }
        setCards((currentCards) => ({
          ...currentCards,
          [category.key]: card,
        }));
      } catch {
        if (isMounted) setUnavailable(current => ({ ...current, [category.key]: true }));
      } finally {
        clearTimeout(timer);
        timers.delete(timer);
        controllers.delete(controller);
      }
    });

    return () => {
      isMounted = false;
      timers.forEach(clearTimeout);
      controllers.forEach(controller => controller.abort());
    };
  }, []);

  return (
    <section className="dashboard-page">
      <section className="dashboard-hero" aria-label="Real-Time Weather Overview">
        <img src={`${import.meta.env.BASE_URL}Hero_Section_Image.jpeg`} alt="" className="dashboard-hero-image" />
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
                      <p>{unavailable[category.key] ? "目前無有效資料，請稍後重新整理。" : "Loading..."}</p>
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
