# Tropical Cyclone Center — 功能規劃與參考專案研究筆記

> 專案：Weather Integration Static（React + Vite／Python Fetchers／GitHub Actions／GitHub Pages）  
> 整理日期：2026-11-03  
> 文件性質：**需求與資料來源研究筆記，非最終技術規格；目前不進行實作。**  
> 參考網站：[Pillar's Tropical Cyclone Forecast](https://lkt0713.github.io/Typhoon-Forecast/#/overview)  
> 參考程式碼：[lkt0713/Typhoon-Forecast](https://github.com/lkt0713/Typhoon-Forecast)

## 0. 閱讀方式與驗證界線

本文件刻意分開三類資訊：

- **[已決定]**：Weather Integration 的產品需求，來自目前的規劃討論。
- **[參考專案已展示／README 說明]**：Pillar 網站及 GitHub 公開資訊中實際列出或呈現的內容；不等於本專案已實測成功。
- **[待驗證]**：是否可以持續、合法、穩定地由 GitHub Actions 下載與解析，或是否能擴充至全球洋區；不得直接視為已完成。

本文件不含第三方原始碼，不表示已對其所有程式逐行審查；若日後 Codex 實際開發，仍應對照當時的 GitHub 版本、官方資料文件和授權條件。網站畫面中的即時颱風資料會隨時間變動，以下主要記錄**功能與資料產品種類**。

---

## 1. 我們的 Tropical Cyclone Center：目標與範圍

### 1.1 產品定位 [已決定]

在既有 Weather Integration Static 網站中新增獨立的 **Tropical Cyclone Center（熱帶系統專區）**，結合：

1. 全球活躍熱帶氣旋的總覽及篩選。
2. 個別熱帶系統的機構分析、官方預報及原始圖資。
3. 傳統 NWP、AI 預報模式以及 Ensemble 系集路徑的互動比較。
4. 適合靜態網站的資料更新、來源標示與異常處理。

**不是**單純把各國颱風圖片堆到同一頁，也**不是**直接複製 Pillar 的西北太平洋專案。

### 1.2 V1 已確定的四項範圍

| 面向 | V1 決定 | 暫不納入 |
|---|---|---|
| 涵蓋範圍 | 全球主要熱帶氣旋洋區 | 不能只涵蓋西北太平洋就稱全球完成 |
| 系統門檻 | Tropical Depression（TD，熱帶性低氣壓）及更強的已識別系統 | Invest、尚未形成／尚未正式分類的發展訊號 |
| 預報 | 官方路徑 + 傳統 NWP + AI 模式 | 自行從原始全球氣象場開發氣旋偵測演算法（非首選） |
| 歷史資料 | 聚焦當前活躍系統 | 歷史颱風搜尋、長期預報校驗資料庫 |

備註：各洋區對 TD／氣旋分類與編號的規則可能不同；V1 仍需制定「是否屬於活躍系統」的跨來源判定規則。

### 1.3 互動預報方案 [已決定：B 進階互動式預報]

| 必要功能 | 預期操作 | 資料前提 |
|---|---|---|
| 多路徑比較 | 同圖顯示／隱藏 JMA、JTWC、CWA、NHC 等官方路徑（依洋區有無而定） | 逐時效座標、來源、預報版本 |
| 多模式比較 | IFS、AIFS、GFS 等各自開關 | 模式識別、預報路徑 |
| 預報時間軸 | 選某個**實際有效時間**查看路徑位置 | forecast valid time；不得只混用各來源 +24h |
| 起報時間辨識 | 顯示每個來源的 initialization/cycle time | initialization time 與 valid time 分離 |
| 相同起報時間比較 | 研究性比較 00Z／12Z 等相同 cycle | 短期保留最近數輪預報 |
| Ensemble Spaghetti Plot | 顯示多個 member，切換全部／單一成員 | member ID、各成員時序與缺值 |
| 路徑節點細節 | 點選中心位置，查時間、經緯度及可用強度 | 各時效資料欄位與單位 |

**時間軸原則**：預設以「預報有效時間」對齊；不同模式起報時間可能不同，必須清楚標記。若時刻沒有對應節點，不可默默當作真實預測位置；插值若日後實作，應註明是網站推算。

**Ensemble 原則**：Spaghetti 表示不同系集成員的預測分散，不等同官方機率，也不應直接將所有路徑外包絡視為官方預報範圍。

### 1.4 預計頁面

**A. Global Overview（全球總覽）**

- 全球主要洋區的活躍系統清單、位置、名稱、各機構編號、分析強度與最新資料時間。
- 互動式全球地圖：位置標記與清單連動；點選進入個別系統頁。
- 依洋區篩選：西北太平洋、東北／中北太平洋、北大西洋、北印度洋、西南印度洋、澳洲周邊及南太平洋等。
- 明確區分：**有活躍系統／確認無系統／部分來源失敗／全來源失敗／資料過期**。

**B. Cyclone Detail（個別系統詳細頁）**

- **Overview**：名稱、內部 ID、機構編號、中心座標、移動、氣壓、風速、來源與觀測時間。
- **Forecast**：互動地圖、多官方／模式路徑、有效時間軸、cycle 選擇、Ensemble。
- **Imagery**：各來源原始預報圖、衛星與其他相關圖資；來源、圖像有效時間及抓取時間分開顯示。
- **Analysis**：JMA／JTWC／CWA 等分析並列；保留不同風速平均時間與分類標準，不硬算「共同強度」。

---

## 2. 參考網站 Pillar's Tropical Cyclone Forecast：定位與做法

### 2.1 參考網站的定位 [README／網站已展示]

Pillar 主要為**西北太平洋熱帶氣旋深度分析網站**：將官方預報、AI 與傳統系集模式、衛星、海洋和大氣環境場放在一起，並提供路徑、侵襲、強度與校驗圖表。

與我們的差異：Pillar 偏向**單一洋區／深度分析**；我們偏向**全球活躍系統／多來源整合與互動比較**。因此可參考其資料取得與圖表概念，不應假設其抓取範圍直接等於全球。

### 2.2 大致運作流程 [README 已確認]

1. GitHub Actions 定期或接續觸發更新。
2. `forecast.py` 與專用模組下載及處理氣象、海洋、衛星和模式資料，配對系統、計算統計並產出圖表。
3. `generate_forecast_website.py` 產生 `docs/` 下的網站靜態內容。
4. GitHub Pages 提供瀏覽；README 表示整體網站約每 10–15 分鐘刷新，**不是全部上游產品每 10–15 分鐘起報**。
5. 使用快取、資料可用性檢查與更新工作流避免重複抓取、處理資料尚未發布等狀況；實際細節以最新 Workflow 與程式為準。

### 2.3 重要程式檔案及用途

| 檔案 | 參考用途 |
|---|---|
| [`forecast.py`](https://github.com/lkt0713/Typhoon-Forecast/blob/main/forecast.py) | 主要預報資料整合、系統配對、計算、出圖與驗證 |
| [`generate_forecast_website.py`](https://github.com/lkt0713/Typhoon-Forecast/blob/main/generate_forecast_website.py) | 組裝靜態網站及展示資源 |
| [`ecmwf_bufr.py`](https://github.com/lkt0713/Typhoon-Forecast/blob/main/ecmwf_bufr.py) | ECMWF 熱帶氣旋 BUFR 軌跡解析、模式與成員處理；值得深入研究 |
| [`noaa_atcf.py`](https://github.com/lkt0713/Typhoon-Forecast/blob/main/noaa_atcf.py) | NOAA ATCF／NOMADS 路徑資料下載與解析；值得深入研究 |
| [`official.py`](https://github.com/lkt0713/Typhoon-Forecast/blob/main/official.py) | JMA、CWA 官方路徑預報處理 |
| [`satellite.py`](https://github.com/lkt0713/Typhoon-Forecast/blob/main/satellite.py) | Himawari-9 衛星紅外線資料 |
| [`ohc.py`](https://github.com/lkt0713/Typhoon-Forecast/blob/main/ohc.py) | CMEMS／HYCOM 水溫剖面與海洋熱含量 |
| [`ecmwf_steering.py`](https://github.com/lkt0713/Typhoon-Forecast/blob/main/ecmwf_steering.py) | AIFS 500 hPa 駛流場 |
| [`ecmwf_shear.py`](https://github.com/lkt0713/Typhoon-Forecast/blob/main/ecmwf_shear.py) | AIFS 200–850 hPa 垂直風切 |
| [`.github/workflows/`](https://github.com/lkt0713/Typhoon-Forecast/tree/main/.github/workflows) | 排程、接續更新、監測與部署 |

**架構差異**：Pillar 使用 Python 產生網站與靜態成果；我們保留 React + Vite 前端，Python 更新靜態 JSON／必要圖資，再由 GitHub Pages 提供，不直接移植他的前端生成方式。

---

## 3. 參考網站使用的資料來源、產品與目的

### 3.1 傳統數值與 AI 預報模式 [README 已列出；部分格式／端點待逐項測試]

| 提供者 | 模式／產品 | 類型 | 在 Pillar 的用途 | 對本專案的價值 |
|---|---|---|---|---|
| Google DeepMind | WeatherNext WN3-C、WN2-C r2、WN2-C r1、WN2-C 1000、GENC | AI 預報／系集產品 | 路徑系集、模式比較、生成潛勢等 | 可作後續 AI 模式擴充；**下載條件、產品差異待查** |
| ECMWF Open Data | AIFS-ENS | AI 系集 | Ensemble 軌跡與分散 | **V1 高優先**：Spaghetti |
| ECMWF Open Data | AIFS-single | AI 確定性 | 路徑、500 hPa 駛流、200／850 hPa 風切 | **V1 高優先**：AI 單一路徑；環境場可後續 |
| ECMWF Open Data | IFS ENS | 傳統物理系集 | 路徑與系集比較 | **V1 高優先**：Spaghetti |
| ECMWF Open Data | HRES／IFS 確定性相關產品 | 傳統物理確定性 | 單一路徑比較 | 型號、當前發布命名與產品對應須按官方文件複查 |
| NOAA / NCEP | GFS | 傳統物理確定性 | 路徑比較 | **V1 高優先研究** |
| NOAA / NCEP | GEFS | 傳統物理系集 | 系集路徑、侵襲統計 | **V1 高優先研究** |
| NOAA / NCEP | AIGFS | AI 確定性 | AI 路徑比較 | 視可用性納入 |
| NOAA / NCEP | AIGEFS | AI 系集 | AI Ensemble | 視可用性納入 |

**核心發現**：參考程式以 ECMWF 熱帶氣旋路徑 BUFR 與 NOAA/NOMADS ATCF `ens_tracker` 等已處理的氣旋軌跡產品為切入點，不必為了畫路徑重新實作全球 GRIB 場的氣旋追蹤；但是否涵蓋所有洋區和系統，仍須驗證。

### 3.2 官方機構：分析與路徑預報

| 機構／中心 | 主要洋區角色 | 用途／顯示內容 | 取得方式與待確認事項 |
|---|---|---|---|
| JMA／RSMC Tokyo | 西北太平洋 | 位置、強度、官方預報路徑；與其他機構比較 | Pillar `official.py`；正式可用資料介面及完整欄位需測試 |
| JTWC | 多個太平洋、印度洋區域提供預報 | 分析與預報路徑、1 分鐘平均風速、官方警報圖 | Pillar 有展示；自動下載可用性及使用條件需驗證 |
| CWA | 臺灣及西北太平洋熱帶系統資訊 | 位置、強度與官方預報 | CWA Open Data `W-C0034-005`；通常須 API Key |
| NHC／CPHC | 北大西洋、東／中北太平洋 | 供我們未來全球涵蓋使用的官方路徑與地理資料 | **Pillar 不是以這些洋區為主**；我們應自行評估 NHC GIS／ATCF |
| IMD、La Réunion、BoM、BMKG、Fiji Met 等 | 北印度洋、南印度洋、澳洲／南太平洋 | 我們所需全球官方覆蓋 | **本專案待研究，不應說成 Pillar 已全面整合** |

**強度比較規則**：JTWC 常採用 **1 分鐘平均風速**；JMA、CWA 常採用 **10 分鐘平均風速**。資料不應直接平均或當成相同標準；每筆資料保留來源、分析時間、平均期間和單位。

### 3.3 衛星、海洋與環境場資料

| 資料來源 | 產品／欄位 | Pillow/Pillar 呈現 | 資料的氣象意義 | 我們的建議 |
|---|---|---|---|---|
| Himawari-9（NOAA Open Data 在 AWS 的鏡像） | B13 10.4µm 紅外線亮溫 | 最近 3 小時衛星動畫（約每 10 分鐘一幀）、彩色強化／黑白 | 看雲頂溫度、對流與眼牆結構 | 可利用既有 Satellite 功能概念；全球須有其他衛星來源 |
| Copernicus Marine（CMEMS） | 海水溫度垂直剖面 | OHC／TCHP 地圖、沿 JTWC 路徑的 OHC 變化 | 了解海洋上層熱能與潛在增強環境 | V1 後續擴充；可能需帳號與金鑰 |
| HYCOM | 海洋溫度分析 | CMEMS 失敗時的 OHC 備援 | 類似上項 | 備援路線待驗證 |
| ECMWF AIFS-single | 500 hPa 高度、風速／方向 | 駛流場、流線、5880 gpm 等高線、預報路徑 | 協助解釋副高與導引氣流 | V1 後續擴充 |
| ECMWF AIFS-single | 200、850 hPa 風 | 200–850 hPa 垂直風切與沿路徑曲線 | 評估強度發展的環境條件 | V1 後續擴充 |

---

## 4. 參考網站呈現了哪些「圖檔／圖表／互動產品」，各自要回答什麼問題？

以下分類區分 **原始機構圖**、**網站加工生成圖**、**前端互動資料圖層**；不應把所有可見影像都稱為從機構直接下載的原圖。

| 功能分頁 | 圖檔、圖表或資料產品 | 類型 | 目的／使用者想知道的事 | 我們 V1 |
|---|---|---|---|---|
| Summary | Himawari-9 B13 IR 衛星動畫（強化色／灰階） | 由原始衛星資料加工 | 最新雲系結構、對流、眼牆及變化 | 可串聯既有衛星頁；全球擴充另議 |
| Summary | OHC／TCHP 地圖 | 計算與繪製 | 颱風周圍海洋熱含量分布 | 後續 |
| Summary | 沿 JTWC 路徑 OHC 剖線圖 | 取樣／計算圖 | 預測路徑可能經過多少海洋熱能 | 後續 |
| Summary | 沿 AIFS 路徑垂直風切曲線圖 | 計算圖 | 大氣垂直風切未來增減及可能影響 | 後續 |
| Summary | 500 hPa 駛流／高度場圖（多時效） | 模式場加工圖 | 副熱帶高壓、導引氣流如何影響路徑 | 後續 |
| Summary | JTWC Official Forecast Graphic | **機構原始圖** | 查閱 JTWC 官方預報路徑與風圈等 | **必要：依來源可用性** |
| Summary | JTWC／JMA／CWA 官方路徑比較圖、逐時效表 | 整合比較圖＋表格 | 比較各機構位置、強度、時間差異 | **必要** |
| Summary | 臺灣登陸與城市侵襲比例表 | 系集統計 | 成員中有多少比例符合指定距離／登陸條件 | 後續，不稱正式風險機率 |
| Track | Multi-Model Comparison 多模式路徑疊圖 | 整合繪圖 | 不同模式的大方向是否一致 | **必要** |
| Track | Ensemble Track Forecast／Spaghetti | 系集線圖 | 同一模式成員分散程度 | **必要** |
| Track | 可切換起報時間的系集圖 | 多 cycle 圖資 | 看不同輪預報路徑怎麼改變 | **必要：先保留少量近期 cycle** |
| Track | Track Evolution Animation | 序列影格／動畫 | 預報時間往前走，路徑如何演變 | V1 可先用互動時間軸，不一定先產動畫圖 |
| Track | Interactive Track Map | 前端互動地圖 | 點選單一成員、路徑節點與時間 | **必要** |
| Track | Forecast Trend | 不同 cycle 的路徑比較 | 預報是否持續東修／西修 | 後續可擴充 |
| Strike | Strike Probability 地圖 | 系集統計網格圖 | 成員路徑有多少比例接近網格 | 後續；需明確定義距離門檻 |
| Strike | 分時段、34 kt 風圈分析圖 | 系集統計圖 | 模式中不同時間與風場可能涵蓋的範圍 | 後續；不能混同官方 7 級風圈 |
| Intensity | 模式強度預報及區間圖 | 統計曲線 | 不同模式預估增強或減弱的趨勢 | 後續 |
| Verification | 路徑／強度誤差校驗圖 | 歷史統計圖 | 不同模式預報表現如何 | V1 不做歷史查詢，暫緩 |
| Genesis | Genesis Potential 生成潛勢圖 | AI／系集訊號分析 | 未來可能在哪生成系統 | V1 Invest／潛在系統暫緩 |
| Archive | 歷史颱風、模式表現與路徑 | 歷史資料 | 回顧與長期校驗 | V1 暫緩 |

### 圖資管理應保存的描述欄位 [我們的設計原則]

- `source`／`source_url`：原始提供者與產品頁。
- `product_type`：官方圖、模式圖、衛星圖、網站運算圖等。
- `observed_at`／`analysis_time`：觀測或分析時間（如適用）。
- `initialization_time`：模式起報時間（如適用）。
- `valid_time`：該節點／圖層有效時間（如適用）。
- `fetched_at`、`generated_at`：取得與生成時間，和上面的氣象時間分開。
- `cyclone_id`、`agency_ids`、`basin`：系統關聯，避免混用不同機構名稱。
- `license`／`attribution`：授權與署名要求，待實際研究。

---

## 5. 可參考的技術觀念與需要特別小心的事

### 5.1 先取得已追蹤好的路徑產品，不先自行追蹤全球氣象場

- ECMWF **BUFR 熱帶氣旋軌跡產品**：先研究 `ecmwf_bufr.py` 如何取得路徑、member ID、cycle 與時間序列。
- NOAA **ATCF／NOMADS tracker 輸出**：研究 `noaa_atcf.py` 的 GFS／GEFS／AI 模式指引，不能假設所有 ATCF mode code 都代表同一模式版本。
- JMA／JTWC／CWA 等官方路徑：先研究可機器讀取的電文、API 或地理資料；可用原圖作展示補充。
- **[待驗證]**：這些產品全球是否完整、資料延遲與下載穩定性、跨洋區代碼映射、是否存在預測生成但尚未分類的系統。

### 5.2 活躍系統識別、跨機構配對

規劃內部持久的 `cyclone_id`，另存每個來源的 ID／名稱／洋區／時間。對應不能只靠同名或同編號；需要結合時間與位置，並為模糊案例設計保守處理（不強行合併）。跨日期變更、跨洋區遷移及機構分類時間差都要納入。

**重要：** 一個模式預測「可能形成的氣旋」不等於官方已確認的 TD。V1 的活躍系統清單僅收正式符合門檻者，模型生成訊號可留待 Genesis 功能。

### 5.3 更新狀態與資料可靠性

至少區分：

| 狀態 | 意義 | UI 建議 |
|---|---|---|
| OK_WITH_STORMS | 成功取得有效資料且有活躍系統 | 顯示系統 |
| OK_NO_STORMS | 有效且完整取得後確認無系統 | 顯示「目前無活躍熱帶系統」 |
| PARTIAL | 有些來源／洋區成功、有些失敗 | 保留成功資料，清楚標示覆蓋缺口 |
| UNAVAILABLE | 來源未發布、存取失敗或解析失敗 | 不得視為無系統 |
| STALE | 只剩過期的最後成功資料 | 標示最後有效分析與取得時間 |

對於全世界「目前沒有系統」的宣告，要確定所有**必要洋區**的來源狀態足夠完整。工作流頻率、資料公布頻率、資料有效時間和前端載入時間不同。

### 5.4 靜態架構設計方向（僅概念，不是檔案定案）

```text
Global official agencies / model tracks / imagery
                 |
                 v
       Python Fetchers (GitHub Actions)
                 |
                 v
   Normalize / Cyclone Matching / Validate
                 |
                 v
     Static JSON + Images + Source Status
                 |
                 v
        React + Vite / GitHub Pages
          |                  |
     Global Overview     Cyclone Detail
                        (Forecast / Analysis / Imagery)
```

如果未來要保留相同起報時間供比較，可只保存近期少量 cycle，**不等於**要做完整歷史颱風資料庫。大量 Ensemble 需要分檔、按需下載，避免單一 JSON 過大。

### 5.5 參考他人的程式與授權

- 可以研究資料來源、演算法思路、資料欄位與流程，但**不要因公開可讀就直接假設可以複製原始碼**。
- 正式使用前，檢查 GitHub 當前 LICENSE、第三方服務條款、圖片重發布／快取／署名限制。
- 使用 Codex 時，先指定參考專案**唯讀**、不執行未審查腳本、不修改我們已運行功能；重要發現附檔案路徑與函式名稱。

---

## 6. V1 與 Pillar 的借鏡優先級

| 優先 | 要研究／建立的能力 | 對照 Pillar | 為何優先 |
|---|---|---|---|
| P0 | 全球活躍系統來源、洋區覆蓋與身份配對 | `forecast.py` 的系統配對流程可參考，**但全球仍需補足其他官方中心** | 所有詳細頁與模式配對的基礎 |
| P0 | 官方機構路徑及分析 | `official.py` + JTWC 相關處理 | 使總覽與詳細頁有可靠基線 |
| P1 | ECMWF IFS／AIFS BUFR 解析 | `ecmwf_bufr.py` | 先驗證 AI 與傳統 Ensemble 資料 |
| P1 | NOAA GFS／GEFS／AI ATCF 解析 | `noaa_atcf.py` | 模式比較來源擴充 |
| P1 | 互動地圖、時間軸、cycle 與 member 顯示 | Track 分頁的展示方式 | 滿足已選 B 方案 |
| P1 | 原始官方圖資與來源時間管理 | JTWC 原圖、官方比較圖 | 保留原始分析依據 |
| P2 | 衛星與海洋／大氣環境圖 | `satellite.py`／`ohc.py`／`ecmwf_steering.py`／`ecmwf_shear.py` | 強化「為什麼這樣預報」的解讀 |
| P2 | 侵襲比例／強度分布／Genesis／Verification／Archive | Strike／Intensity／Genesis／Verification／Archive | V1 明確不是主要範圍 |

---

## 7. 下一步研究問題（不是立刻開發）

1. **全球活躍 TD 以上**：各洋區最可信的官方清單從哪裡取得？哪些有結構化且可自動取用的資料？不同機構可能只報某一強度以上，怎麼補足？
2. **ECMWF BUFR**：現有檔案、欄位、member 編號、storm identifier、時效及無資料情況；我們可以否直接在 GitHub Actions 解析？
3. **NOAA ATCF**：NOMADS `ens_tracker` 目前路徑、cycle 延遲、GFS／GEFS／AIGFS／AIGEFS 代碼與各洋區覆蓋。
4. **JMA／JTWC／CWA**：可機器讀取的座標與官方圖資是否可同時取得？遇到不同強度與不同起報時間如何呈現？
5. **全球圖資**：Himawari 僅涵蓋部分洋區，若要全球衛星影像，需補充 GOES、Meteosat 等來源，依授權與覆蓋研究。
6. **運作成本與限制**：GitHub Actions 時數、執行頻率、Git 大型圖資／JSON 成長、API key、服務流量限制、錯誤回退與授權。
7. **正式 Codex 研究**：對 `forecast.py`、`ecmwf_bufr.py`、`noaa_atcf.py`、`official.py` 做針對性的函式層分析，附原始碼定位；研究階段不改任何檔案。

---

## 8. 參考連結（留給 Codex／後續研究）

**主要參考專案**

- 網站 Overview：<https://lkt0713.github.io/Typhoon-Forecast/#/overview>
- GitHub：<https://github.com/lkt0713/Typhoon-Forecast>
- README：<https://github.com/lkt0713/Typhoon-Forecast/blob/main/README.md>
- ECMWF 解析：<https://github.com/lkt0713/Typhoon-Forecast/blob/main/ecmwf_bufr.py>
- NOAA ATCF 解析：<https://github.com/lkt0713/Typhoon-Forecast/blob/main/noaa_atcf.py>
- 官方預報處理：<https://github.com/lkt0713/Typhoon-Forecast/blob/main/official.py>
- Actions：<https://github.com/lkt0713/Typhoon-Forecast/tree/main/.github/workflows>

**官方資料入口（存取條件仍需逐項驗證）**

- ECMWF Open Data：<https://www.ecmwf.int/en/forecasts/datasets/open-data>
- CWA 氣象開放資料：<https://opendata.cwa.gov.tw/dist/opendata-swagger.html>
- JMA RSMC Tokyo：<https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/RSMC_HP.html>
- JTWC：<https://www.metoc.navy.mil/jtwc/jtwc.html>
- NHC GIS：<https://www.nhc.noaa.gov/gis/>
- WMO Severe Weather Information Centre：<https://severeweather.wmo.int/>

---

## 9. 一句話總結

**我們要建立的是「全球 TD 以上活躍熱帶氣旋的整合與互動預報平台」；Pillar 提供值得學習的「多模式路徑與系集解析、跨來源配對、原始與加工氣象圖表、自動更新」範例。先把全球辨識與結構化路徑資料驗證清楚，再逐步實作 React 地圖、時間軸、官方／模式比較與圖資展示。**
