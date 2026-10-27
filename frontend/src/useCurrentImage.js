import { formatImageDate } from "./image-time";
import { useEffect, useState } from "react";
import { fetchCurrentImageHistory, fetchLatestImage } from "./api";

export function taipeiDate(value = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(value));
  const get = type => parts.find(part => part.type === type).value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export default function useCurrentImage(type) {
  const [today, setToday] = useState(() => taipeiDate());
  const [image, setImage] = useState(null);
  const [history, setHistory] = useState([]);
  const [selectedTime, setSelectedTime] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    const timer = setInterval(() => setToday(taipeiDate()), 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let active = true;
    setError(""); setHistory([]); setStatus("");
    async function load() {
      try {
        const latest = await fetchLatestImage(type);
        if (!active) return;
        setImage(latest);
        setSelectedTime(latest.image_time || "");
        if (taipeiDate(latest.image_time) !== today) return;
        try {
          const data = await fetchCurrentImageHistory(type, today);
          if (!active) return;
          const byTime = new Map(data.items.filter(item => taipeiDate(item.image_time) === today)
            .map(item => [item.image_time, item]));
          byTime.set(latest.image_time, latest);
          setHistory([...byTime.values()].sort((a, b) => a.image_time.localeCompare(b.image_time)));
          if (!data.complete) setStatus("部分時次尚未取得，僅列出已成功發布的圖片。");
        } catch {
          if (active) {
            setHistory([latest]);
            setStatus("時次資料讀取失敗；目前仍可顯示最新成功圖片。");
          }
        }
      } catch (err) {
        if (active) setError(err.message);
      }
    }
    load();
    return () => { active = false; };
  }, [type, today]);

  const isToday = image && taipeiDate(image.image_time) === today;
  return { image, error, history: isToday ? history : [], selectedTime, setSelectedTime,
    selected: (isToday && history.find(entry => entry.image_time === selectedTime)) || image,
    status: image && !isToday
      ? `當日資料尚未取得；目前顯示 ${formatImageDate(image.image_time)} 的最新成功圖片（台北時間）。`
      : status || `${history.length} images available for this date.` };
}
