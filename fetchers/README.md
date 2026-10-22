# 氣象圖資靜態資料更新

Python Fetcher → 原有 Services → ImagePayload → 靜態 JSON → React。
不需要 Flask、SQLite、API Key 或原始後端專案。

## 安裝與執行

在專案根目錄執行（Python 3.10 以上）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r fetchers\requirements.txt

# 更新五種已移植圖資（含 SST）
.\.venv\Scripts\python.exe -B fetchers\update_images.py

# 僅更新本階段四種圖資
.\.venv\Scripts\python.exe -B fetchers\update_images.py temperature weather_chart 850hpa tchp

# 原有 SST 入口仍可使用
.\.venv\Scripts\python.exe -B fetchers\update_sst.py
```

Windows 需求包含 tzdata，供 ZoneInfo("Asia/Taipei") 使用。
預設輸出以入口檔案位置定位，不依賴工作目錄。
可用 `--output-root <目錄>` 指定另一個 images 根目錄。
省略產品參數會更新全部；未知產品名稱在抓取前即回報錯誤。

## 共用設計與資料契約

`update_images.py` 註冊表只對應 Service 與指定抓取方法，CWA 不呼叫
會順便抓取其他產品的 fetch()。沿用原有來源解析、發布延遲及回溯搜尋邏輯。
`src/publication.py` 統一處理驗證、序列化及原子寫檔；update_sst.py 也使用此模組。
新產品只需新增註冊及必要的時間解析，不需複製發布流程。

每個產品輸出至 `frontend/public/data/images/{type}/latest.json`。
內容為單一物件，保留七個欄位：image_type、source、title、image_url、
source_url、fetched_at、image_time。不新增資料庫 ID 或外層包裝。
圖片保留官方遠端網址，不下載或重新託管圖片。

| type | 原有來源／Service | image_time 語意 |
| --- | --- | --- |
| sst | JMA／OceanService | 每日產品日期，YYYY-MM-DD |
| temperature | CWA／fetch_temperature | 台北時刻，ISO 8601 含 +08:00 |
| weather_chart | CWA／fetch_weather_chart | 已知時含 +08:00；未知為 null |
| 850hpa | KMA／KMAService | 韓國時刻，ISO 8601 含 +09:00 |
| tchp | CWA／fetch_tchp | 每日產品日期，YYYY-MM-DD |

fetched_at 一律為實際取得 metadata 的 UTC 時間，含 +00:00。
不把抓取時間、網址快取參數或 HTTP Last-Modified 當成圖片觀測時間。
KMA API 的 tm 是 KST；回溯圖片檔名是 UTC，轉換後代表相同時刻。
TCHP 來源只有日期，不補上午夜或推測觀測時區。
目前 CWA 天氣圖頁面未提供既有解析器可辨識的圖片時刻，因此保留 null；
原 ImagePage 顯示轉成台北時間的 Fetched At。

## 失敗處理

- metadata、解析或圖片驗證失敗，保留該產品上一次成功的 JSON。
- 發布前確認圖片 HTTP 狀態與 image Content-Type；HTML 錯誤頁不算成功。
- 必須恰好一筆且通過欄位、網址及時間驗證，才開始寫入。
- 先寫同目錄暫存檔並 flush/fsync，再原子替換；寫入失敗清理暫存檔。
- 各圖資獨立更新，單一失敗不阻止其他產品；任一失敗時整批退出碼為 1，
  錯誤寫入 stderr。首次抓取失敗不建立空 JSON。
- 舊檔可能因來源中斷而過期，可由 fetched_at 追查最後成功抓取時間。

## React 與部署

api.js 的五種 latest-image 類型讀取各自靜態路徑，尊重 Vite BASE_URL，
使用 cache: "no-cache"，失敗不回退 Flask。Dashboard、ImagePage、CSS 均不變。
其餘未移植圖資與歷史、回補等功能仍保留原 API 行為，不在本階段範圍。

```powershell
cd frontend
npm install
npm run dev
```

詳細頁為 /images/temperature、/images/weather_chart、/images/850hpa、
/images/tchp 及 /images/sst。本機更新 JSON 後重新整理即可；
正式發佈必須更新 JSON 後重新 Build。Vite 會將 public 資源原樣複製至
`dist/data/images/{type}/latest.json`。
若部署到 Repository 子路徑，仍須另設 Vite base、React Router basename
及靜態主機路由策略。本階段沒有建立排程或發布設定。

## 驗證

```powershell
# 專案根目錄
.\.venv\Scripts\python.exe -B -m unittest discover -s fetchers\tests -v
cd frontend
npm test -- --run
npm run build
```

Python 測試覆蓋圖片時間、KMA API／回溯一致性、產品選擇、來源失敗、
空／多筆／無效資料保留舊檔、圖片驗證失敗、原子替換及無 Flask／資料庫匯入。
React 測試涵蓋根目錄與子路徑、讀取失敗不回退，以及 Dashboard／詳細頁呈現。
整合測試直接使用 public 中真實 Fetcher 輸出，請先成功更新五種 JSON；
單元測試不會將模擬資料寫入 public。
