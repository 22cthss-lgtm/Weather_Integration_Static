import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchLatestImage } from "../api";

const compactImageTypes = new Set(["temperature", "radar", "satellite", "weather_chart", "850hpa", "tchp", "sst"]);

export default function ImagePage() {
  const { type } = useParams();
  const [image, setImage] = useState(null);
  const [error, setError] = useState("");
  const sectionClassNames = ["image-detail-page"];

  if (compactImageTypes.has(type)) {
    sectionClassNames.push("image-detail-page-compact");
  }

  if (type === "tchp") {
    sectionClassNames.push("image-detail-page-tchp");
  }

  const sectionClassName = sectionClassNames.join(" ");

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

  if (error) {
    return <p>{error}</p>;
  }

  if (!image) {
    return <p>Loading...</p>;
  }
  
  const fetchedAt = new Date(image.fetched_at)
    .toLocaleString("sv-SE", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <section className={sectionClassName}>
      <h2>{image.title}</h2>
      <p>Source: {image.source}
        <a className = "source-link" href={image.source_url} target="_blank" rel="noreferrer">
          Image Original source</a>
      </p>
      <p>{image.image_time ? `Image Time: ${image.image_time}` : `Fetched At: ${fetchedAt}`}</p>
      <img className="detail-image" src={image.image_url} alt={image.title} />
    </section>
  );
}
