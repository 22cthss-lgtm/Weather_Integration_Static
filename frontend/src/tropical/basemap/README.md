# 熱帶系統地圖底圖（`ne-land-wp.json`）

颱風頁 Forecast 分頁的陸地輪廓（design.md 7.2、7.3）。只由 `src/pages/tropical/TrackMap.jsx` 以動態 `import()` 載入，不進首頁 bundle。

## 來源

- 資料：Natural Earth 1:50m Physical Vectors — Land（`ne_50m_land`），檔內 `ne_50m_land.VERSION.txt` 為 `4.1.0`。
- 下載網址：`https://naciscdn.org/naturalearth/50m/physical/ne_50m_land.zip`（2026-11-18 10:10Z 取得一次，HTTP 200，457,183 bytes，SHA-256 `0b8e670cf80dce9cbebe2a193bc44ba5602758c22e1fa603980553646d7ff162`）。原始檔只存在本機 `.runtime/s7-basemap/raw/`，不入版控。
- 授權：Natural Earth 官方網站的使用條款（Terms of Use）說明其資料屬**公有領域**、不要求署名（design.md 7.2、7.6 已採用）。下載的 zip 內附 README 沒有授權文字，本次也沒有另外抓取條款頁面；S11 定稿署名時一併對照原文。頁面署名區仍標示來源。

## 處理步驟（一次性工具 `.runtime/s7-basemap/build_basemap.py`，只用 Python 標準函式庫，不入版控）

1. 以 `zipfile`＋`struct` 讀 `ne_50m_land.shp` 的每個多邊形環（shape type 5）。
2. 在 -180..180 座標下，以 Sutherland–Hodgman 將每個環分別裁到兩個框：經度 80..180、經度 -180..-140，緯度皆為 -10..65。第二個框再整體加 360，結果涵蓋 80..220（0–360 慣例，與前端 `unwrapLon` 相同）。**不能逐點把負經度加 360 再裁切**，否則跨越 0° 的歐亞大陸環會被扯壞。
3. 每個環以 Douglas–Peucker 簡化（容許誤差 0.02°），座標取小數 2 位，去除連續重複點；少於 3 點或面積小於 0.004 平方度的環捨棄。
4. 洞（shapefile 中逆時針的環）歸到包含它的外環；本範圍實際沒有洞。
5. 輸出一個 `FeatureCollection`，只有一個 `MultiPolygon` feature，`properties` 為空物件；精簡 JSON（無縮排）。

指令：`python -I .runtime/s7-basemap/build_basemap.py .runtime/s7-basemap/raw/ne_50m_land.zip <輸出> 0.02`

## 結果與解析度的選擇

- 422 個多邊形、7,896 點、116,714 bytes（gzip 約 36.6 KB）。範圍經度 80.0–220.0、緯度 -10.0–65.0。不含任何網址或屬性。
- 比較了容許誤差 0、0.02、0.05、0.1（195.7／116.7／69.0／40.3 KB）：0.02 仍保留臺灣、琉球群島與菲律賓各主要島嶼的輪廓；0.05 起琉球與巴丹群島的小島開始消失。1:50m 本身不含澎湖等更小的島。
- 裁切邊界（80°E、140°W、10°S、65°N）與 180° 處會有多邊形的直線切邊；地圖只填色、不描邊，所以不會畫出這些線。
