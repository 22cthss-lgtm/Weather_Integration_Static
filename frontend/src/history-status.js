const gapFields = ["pending", "missing", "failed", "official_missing", "legacy_unknown"];

export function historyStatus(data, availableCount) {
  if (data.schema_version === undefined) {
    const gaps = (data.missing?.length || 0) + (data.failed?.length || 0);
    return data.complete
      ? `已取得 ${availableCount} 個時次（舊版清單）。`
      : `已取得 ${availableCount} 個時次；舊版缺漏 ${gaps}，無法可靠區分尚未探查、缺圖、失敗或既定排除。僅列出已成功發布的圖片。`;
  }
  if (data.schema_version !== 2 || !Array.isArray(data.items) || typeof data.complete !== "boolean"
      || gapFields.some(field => !Array.isArray(data[field]) || data[field].some(t => typeof t !== "string"))) {
    throw new Error("Unsupported or invalid history classification");
  }
  const seen = new Set(data.items.map(item => item.image_time));
  for (const field of gapFields) {
    for (const time of data[field]) {
      if (seen.has(time)) throw new Error("Overlapping history classification");
      seen.add(time);
    }
  }
  const labels = ["尚未探查", "已確認缺圖", "請求／驗證失敗", "既定排除", "舊版分類不明"];
  const parts = gapFields.flatMap((field, i) => data[field].length ? [`${labels[i]} ${data[field].length}`] : []);
  if (data.complete !== (parts.length === 0)) throw new Error("Invalid history completeness");
  return `已取得 ${availableCount} 個時次；${parts.length ? parts.join("；") + "。僅列出已成功發布的圖片。" : "當日清單完整。"}`;
}
