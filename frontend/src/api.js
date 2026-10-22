const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:5174";
const STATIC_IMAGE_TYPES = new Set([
  "sst", "temperature", "weather_chart", "850hpa", "tchp",
  "cimss_wind_analysis", "cimss_steering_flow", "seaice_arctic", "seaice_antarctic",
  "radar", "satellite", "rainfall",
]);
const CURRENT_IMAGE_TYPES = new Set(["radar", "satellite", "rainfall"]);

async function readStatic(path) {
  const response = await fetch(`${import.meta.env.BASE_URL}${path}`, { cache: "no-cache" });
  if (!response.ok) throw new Error(`無法讀取已發布資料：${path}`);
  return response.json();
}

export async function fetchCurrentImageHistory(type, date) {
  if (!CURRENT_IMAGE_TYPES.has(type) || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    throw new Error("Invalid current-day image request");
  }
  const data = await readStatic(`data/images/${type}/history/${date}.json`);
  if (data.image_type !== type || data.date !== date || !Array.isArray(data.items)) {
    throw new Error("Invalid published image history");
  }
  return data;
}

export async function fetchLatestImage(type) {
  if (STATIC_IMAGE_TYPES.has(type)) {
    const response = await fetch(`${import.meta.env.BASE_URL}data/images/${type}/latest.json`, {
      cache: "no-cache",
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch latest image for ${type} (static JSON)`);
    }
    return response.json();
  }
  const response = await fetch(`${API_BASE_URL}/api/images/latest?type=${encodeURIComponent(type)}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch latest image for ${type}`);
  }
  return response.json();
}

export async function fetchImageHistory(type, { date = "", limit = "" } = {}) {
  if (CURRENT_IMAGE_TYPES.has(type)) {
    const data = await fetchCurrentImageHistory(type, date);
    return limit ? data.items.slice(-Number(limit)) : data.items;
  }
  const params = new URLSearchParams({ type });
  if (date) {
    params.set("date", date);
  }
  if (limit) {
    params.set("limit", String(limit));
  }

  const response = await fetch(`${API_BASE_URL}/api/images/history?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch history for ${type}`);
  }
  return response.json();
}

export async function backfillImages(type, { range = "today", date = "" } = {}) {
  const params = new URLSearchParams({ type });
  if (range) {
    params.set("range", range);
  }
  if (date) {
    params.set("date", date);
  }

  const response = await fetch(`${API_BASE_URL}/api/images/backfill?${params.toString()}`, {
    method: "POST",
  });
  return parseJson(response, `Failed to backfill images for ${type}`);
}

export async function fetchDailyImages(type, { date = "" } = {}) {
  if (type === "rainfall") {
    const data = await readStatic("data/images/rainfall/daily/latest.json");
    if (!Array.isArray(data.items) || data.items.length !== 3) throw new Error("Invalid daily rainfall images");
    return data.items;
  }
  const params = new URLSearchParams({ type });
  if (date) {
    params.set("date", date);
  }

  const response = await fetch(`${API_BASE_URL}/api/images/daily?${params.toString()}`);
  return parseJson(response, `Failed to fetch daily images for ${type}`);
}

export async function fetchRainfallTop(metric = "10min") {
  const data = await readStatic("data/rainfall/rankings/latest.json");
  const ranking = data.rankings?.[metric];
  if (!ranking || !Array.isArray(ranking.items)) throw new Error(`無法讀取雨量排行：${metric}`);
  return ranking;
}

export async function fetchImageStatus() {
  const response = await fetch(`${API_BASE_URL}/api/images/status`);
  return parseJson(response, "Failed to fetch image status");
}

export async function refreshImage(type) {
  const params = new URLSearchParams({ type });
  const response = await fetch(`${API_BASE_URL}/api/images/refresh?${params.toString()}`, {
    method: "POST",
  });
  return parseJson(response, `Failed to refresh ${type}`);
}

async function parseJson(response, fallbackMessage) {
  let payload = null;

  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    throw new Error(payload?.error || fallbackMessage);
  }

  return payload;
}

export async function fetchFaqs({ category = "", q = "" } = {}) {
  const params = new URLSearchParams();
  if (category) {
    params.set("category", category);
  }
  if (q) {
    params.set("q", q);
  }

  const queryString = params.toString();
  const response = await fetch(`${API_BASE_URL}/api/faqs${queryString ? `?${queryString}` : ""}`);
  return parseJson(response, "Failed to fetch FAQs");
}

export async function fetchFaq(id) {
  const response = await fetch(`${API_BASE_URL}/api/faqs/${id}`);
  return parseJson(response, `Failed to fetch FAQ ${id}`);
}

export async function fetchFaqCategories() {
  const response = await fetch(`${API_BASE_URL}/api/faqs/categories`);
  return parseJson(response, "Failed to fetch FAQ categories");
}

export async function createFaq(payload) {
  const response = await fetch(`${API_BASE_URL}/api/faqs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJson(response, "Failed to create FAQ");
}

export async function updateFaq(id, payload) {
  const response = await fetch(`${API_BASE_URL}/api/faqs/${id}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJson(response, `Failed to update FAQ ${id}`);
}

export async function deleteFaq(id) {
  const response = await fetch(`${API_BASE_URL}/api/faqs/${id}`, {
    method: "DELETE",
  });
  return parseJson(response, `Failed to delete FAQ ${id}`);
}

export async function uploadFaqImage(file) {
  const formData = new FormData();
  formData.append("image", file);
  const response = await fetch(`${API_BASE_URL}/api/faqs/images`, {
    method: "POST",
    body: formData,
  });
  return parseJson(response, "Failed to upload FAQ image");
}
