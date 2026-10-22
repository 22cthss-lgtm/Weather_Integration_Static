# 氣象圖資靜態資料更新

Python Fetcher → 原有 Services → ImagePayload → 靜態 JSON → React。
不需要 Flask、SQLite、API Key 或原始後端專案。

## 安裝與執行

在專案根目錄執行（Python 3.10 以上）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r fetchers\requirements.txt

# 更新九種已移植資源（五種單圖與四種群組）
.\.venv\Scripts\python.exe -B fetchers\update_images.py

# 僅更新第四階段四種單圖
.\.venv\Scripts\python.exe -B fetchers\update_images.py temperature weather_chart 850hpa tchp

# 僅更新第五階段四種群組
.\.venv\Scripts\python.exe -B fetchers\update_images.py cimss_wind_analysis cimss_steering_flow seaice_arctic seaice_antarctic

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
圖片保留官方遠端網址，不在 public 儲存或重新託管圖片；群組抓取時會讀取圖片內容驗證與解析時間。

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
- 單圖必須恰好一筆；群組必須完整且無重複、額外或錯組子圖。全部通過欄位、網址及時間驗證後，才開始寫入。
- 先寫同目錄暫存檔並 flush/fsync，再原子替換；寫入失敗清理暫存檔。
- 各圖資獨立更新，單一失敗不阻止其他產品；任一失敗時整批退出碼為 1，
  錯誤寫入 stderr。首次抓取失敗不建立空 JSON。
- 舊檔可能因來源中斷而過期，可由 fetched_at 追查最後成功抓取時間。

## React 與部署

api.js 的九種 latest-image 類型讀取各自靜態路徑，尊重 Vite BASE_URL，
使用 cache: "no-cache"，失敗不回退 Flask。Dashboard、ImagePage、CimssPage、SeaIcePage、CSS 與路由均不變。
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
整合測試直接使用 public 中真實 Fetcher 輸出，請先成功更新九種 JSON；
單元測試不會將模擬資料寫入 public。


## 第五階段：CIMSS 與 Sea Ice 群組

四組皆沿用同一個 update_images.py 入口與 src/publication.py 原子 writer。
原有兩個 Service 保留來源網頁解析，新增圖片 HTTP／MIME／非空內容驗證。
單圖 PRODUCTS 與群組 GROUP_PRODUCTS 分開註冊，省略參數會更新全部九種資源。

| 群組 type | 子圖數 | images[] 順序（第一張為代表圖） |
| --- | --- | --- |
| cimss_wind_analysis | 2 | Wind Shear → 850mb Vorticity |
| cimss_steering_flow | 6 | 200–700 → 250–850 → 300–850 → 400–850 → 500–850 → 700–850 mb |
| seaice_arctic | 3 | Extent → Concentration → Time Series |
| seaice_antarctic | 3 | Extent → Concentration → Time Series |

每組輸出至 `frontend/public/data/images/{type}/latest.json`。
頂層七欄位加 images[]，每個子圖維持七欄位；沒有資料庫欄位：

```text
{
  image_type: 群組 type,
  source, title, image_url, source_url, fetched_at, image_time: 代表圖的欄位,
  images: [
    { image_type: 子圖 type, source, title, image_url, source_url, fetched_at, image_time },
    ...其餘完整子圖，順序如上表
  ]
}
```

頂層除 image_type 外，從第一張子圖複製全部欄位，Dashboard 顯示同一張代表圖。
每張子圖 fetched_at 為建構 payload 的 UTC 時間；頂層值跟隨代表圖，
不是另外推算的全群組最後完成時間。原詳細頁依各子圖自己的時間顯示。

CIMSS 只接受圖片內容中明確的 UTC／Z 文字時間，輸出 ISO 8601 +00:00。
Sea Ice 若解析到產品日期，使用 YYYY-MM-DD，不虛構午夜。
HTTP Last-Modified 不代表產品觀測時間，發布時不作為 image_time 備援。
有效圖片未包含既有解析器可辨識的文字時，image_time 合法為 null，
標題不加 None，詳細頁沿用原本 Fetched At 顯示方式。
這不是 OCR；點陣圖中可見的印字時間不保證能由原始 bytes 解析。

2026-10-22 真實抓取四組皆成功，已驗證 14 張非空官方圖片；
目前各子圖 image_time 均為 null。若需精確產品時刻，仍須查看原圖印字。
群組不強迫全部子圖同時刻，各自保留來源資訊，也不以最晚時間覆蓋其他子圖。
任一來源、子圖、必要欄位或替換步驟失敗，整組保留上一份完整 JSON。

新增 test_groups.py 使用 unittest，涵蓋四組契約／排序／代表圖、
不完整／重複／額外／錯組／無效欄位、來源頁面及最後一張失敗、
產生器中斷、替換失敗、日期與未知時間、圖片 MIME／HTTP／空內容等。
前端 groups.test.jsx 讀取真實輸出，使用既有 App 路由測試四張卡片與全部 14 個子圖切換。
api.test.js 涵蓋四組的根目錄與子路徑 URL，以及讀取失敗不回退 API。

本階段沒有修改其他未移植產品、沒有設定 Actions／Pages，也沒有 commit 或 push。
