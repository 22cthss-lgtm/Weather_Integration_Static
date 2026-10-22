# 氣象圖資靜態資料更新

Python Fetcher → 原有 Services → ImagePayload → 靜態 JSON → React。
不需要 Flask、SQLite 或原始後端專案。圖片流程不需 API Key；雨量排行需執行端的 CWA_API_KEY。

## 安裝與執行

在專案根目錄執行（Python 3.10 以上）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r fetchers\requirements.txt

# 更新全部已移植資源（含本階段三種當日圖資與雨量排行）
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

api.js 的十二種 latest-image 類型讀取各自靜態路徑，尊重 Vite BASE_URL，
使用 cache: "no-cache"，失敗不回退 Flask。Dashboard、ImagePage、CimssPage、SeaIcePage、CSS 與路由均不變；雷達、衛星、雨量頁按第六階段調整。
雷達、衛星、雨量頁的最新圖、當日時次、雨量單日圖與排行皆讀取靜態資料；沒有網頁回補 API 呼叫。

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
整合測試直接使用 public 中真實 Fetcher 輸出，請先成功更新各測試所需的圖資與本階段當日／排行 JSON；
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


## 第六階段：雷達、衛星、雨量當日資料

在 C:\Weather_Integration_Static 執行（已安裝 requirements.txt）：

```powershell
python -B fetchers/update_images.py radar satellite rainfall rainfall_rankings
```

這次開發已實際執行，不需立即重跑；此命令供日後更新。
只指定以上四項時不更新其他圖資。全部作業會繼續嘗試，即使其中一項失敗。
不需要也不會啟動 Flask／SQLite。本階段不設定排程或發布作業、不 commit/push。

### 機密設定

專案根目錄 `.env`（已被 Git 忽略）：

```text
CWA_API_KEY=你的授權碼
```

也可在執行環境設定 CWA_API_KEY。既有環境變數優先於 .env。
由 python-dotenv 讀取根目錄檔案，不使用會載入 SQLite 的 src.config。
請勿改用 VITE_ 變數，不要把 Key 放進 public、分享網址或提交 Git。
缺少 Key、來源失敗或格式異常時保留前次成功排行。
公開內容只包含固定的排行欄位，不寫入原始回應、請求授權參數或來源例外。

### 當日時次

| type | 台北當日起點 | 間隔 |
| --- | --- | --- |
| radar | 00:00 | 10 分鐘 |
| satellite | 00:00 | 10 分鐘 |
| rainfall | 00:30 | 30 分鐘 |

Fetcher 先確認最新有效圖片，再以原 CWAService 時次產生器與網址建構器蒐集
起點至該圖片時刻。這是資料產生端的工作，網頁重新整理不會向 CWA 執行回補。
最多六個獨立 URL 同時驗證，只讀取少量圖片 bytes，不將圖片保存到 public。
404／410 記為 missing；網路、HTTP 或驗證異常記為 failed。
官方圖片網址未必永久有效；既有歷史 metadata 不是圖片歸檔。

| 輸出路徑（相對 frontend/public） | 結構 |
| --- | --- |
| data/images/{type}/latest.json | 原七欄位圖片物件 |
| data/images/{type}/history/YYYY-MM-DD.json | image_type、date、timezone、updated_at、range_start/end、expected_count、complete、missing[]、failed[]、items[] |
| data/images/rainfall/daily/latest.json | date、timezone、fetched_at、items[]（三張官方單日圖） |
| data/rainfall/rankings/latest.json | source、dataset_id、fetched_at、rankings（各期間） |

history.items 每筆保留七個圖片欄位，依 image_time 升冪排列。
相同日期重跑以時刻去重並合併，只新增已驗證資料，先前成功紀錄不因缺圖消失。
全部候選都失敗／不存在時不覆蓋舊日期檔。部分成功可以累積，但 complete=false
及 missing/failed 清單明示缺漏；有 failed 時命令非零退出。
沒有任意跨日查詢 UI；不自動刪除舊檔，也不承諾官方 URL 的長期可用性。

最新圖片時刻帶 +08:00，抓取／寫入時間是 UTC。
來源最新時刻倒退時保留較新的成功 latest；未來時間與不合時次的資料拒絕發布。
跨午夜尚無當日圖時保留舊圖，頁面明示日期且不把前一日時次塞進今日選單。
雨量 00:00 圖屬於已結束的單日累積，不能作為當日 00:30 起的時次。

每份 JSON 沿用 src/publication.py 的同目錄暫存檔／fsync／原子替換。
latest、history、daily、ranking 是獨立成功資源，並非跨多檔交易；例如最新圖成功
但歷史掃描失敗，會保留成功最新圖及先前歷史，並回報未完成項目，不誤稱全部失敗。

### 官方三張單日雨量圖

讀取官方 RainfallImg_Day.js 正常配色 Tab0 中 Day0、Day1、Day2 的首筆，
這與官方頁面切換單日圖使用的索引相同，不自行選取某日最後一張代替結算圖。
今日圖是今日 00:00 至圖資時刻；昨日圖是昨日 00:00 至今日 00:00；
前日圖是前日 00:00 至昨日 00:00。

每筆保留圖片七欄位，加 label、represented_date、accumulation_start、accumulation_end。
represented_date 僅有日期；image_time 可以是該日期隔日的午夜終點。
三張圖、日期與結算邊界全數通過驗證後才一次替換 daily JSON。
只要任一張缺失／日期不一致，就保留前次三張，頁面依實際日期提示尚未更新。
daily 抓取與顯示不依賴 latest/history 成功。

### 雨量排行與頁面

沿用 RainfallObservationService 取得 O-A0002-001、既有解析與期間映射。
資料庫儲存匯入只留在未使用的舊 refresh_observations 方法內，靜態流程完全不載入。
一次來源回應產生整份快照；同站重複資料取較新觀測，排除缺值、特殊碼、
非有限值及負雨量，零雨量有效。各期間降冪、站名與站碼穩定排序，最多前10筆。
保留原8個頁籤；JSON 另保留原服務支援的 today 期間，不新增頁籤。
每筆含 rank、station_id/name、county、town、rainfall、observed_at、fetched_at。
觀測時刻與抓取時刻分開，頁面顯示時轉台北時間。
排行是最近一次產生並發布的快照，切換頁籤不會觸發來源 API。

三頁移除 Backfill 按鈕，保留版面、CSS 與路由。共用小型 useCurrentImage
處理時次、午夜與局部失敗；SourceImage 在官方圖失效時顯示來源連結，
不悄悄改看另一個時刻。歷史、單日圖、排行的錯誤分區顯示。
所有新靜態 URL 尊重 Vite BASE_URL；正式更新需在抓取後重新 build／發布。

測試使用 unittest 與 Vitest，包含真實 public 輸出整合測試。
不會把測試模擬資料寫入 public。新輸出需先以 Fetcher 成功產生。
