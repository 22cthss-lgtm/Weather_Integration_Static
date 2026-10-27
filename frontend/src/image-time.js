export function formatImageDate(value) {
  if (!value) return "-";
  // A represented date is a calendar date, not an instant to shift by timezone.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value.replace(/-/g, "/");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date);
  const get = type => parts.find(part => part.type === type).value;
  return `${get("year")}/${get("month")}/${get("day")}`;
}

export function formatImageTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const get = type => parts.find(part => part.type === type).value;
  return `${formatImageDate(value)} ${get("hour")}:${get("minute")}`;
}

export function formatImageTitle(image) {
  if (!image.image_time) return image.title;
  return image.title.replace(
    /\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?$/,
    formatImageTime(image.image_time),
  );
}
