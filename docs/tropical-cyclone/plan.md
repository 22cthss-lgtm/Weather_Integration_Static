# Tropical Cyclone Center — 開發計畫（修訂版 v2）

> 專案：Weather Integration Static（React + Vite／Python Fetchers／GitHub Actions／GitHub Pages）
> 修訂日期：2026-11-11（取代 2026-11-03 的《功能規劃與參考專案研究筆記》，舊筆記存於 `docs/tropical-cyclone/archive/2026-11-03-research-notes.md`）
> 文件性質：**分階段開發計畫。每個「工作階段」設計成一個 chat 可獨立完成。**
> 參考網站：[Pillar's Tropical Cyclone Forecast](https://lkt0713.github.io/Typhoon-Forecast/#/overview)｜[程式碼](https://github.com/lkt0713/Typhoon-Forecast)

## 0. 給每個新 chat 的使用方式

1. 先讀：根目錄 `AGENTS.md` → `HANDOFF.md` 最新一節 → 本文件第 3 節「進度表」→ 本次要做的那一個工作階段。
2. **一個 chat 只做一個工作階段。** 不要提前做下一階段，也不要順手重構無關程式。
3. 做完後更新本文件第 3 節進度表，並在 `HANDOFF.md` 新增一節（做了什麼、驗證了什麼、沒驗證什麼、下一階段要注意什麼）。
4. 若額度快用完而階段未完成：停在可測試的狀態，在 HANDOFF 寫明「已完成／未完成／下一步第一個動作」，下一個 chat 從該處續接。
5. 資訊標記沿用三類：**[已決定]**、**[參考專案已展示]**、**[待驗證]**。[待驗證] 的內容不得當成事實寫進程式。

### 全程固定規則

- 遵守 `AGENTS.md`：每批程式修改後，主代理自行驗證，再交給未參與實作的獨立 Sub-Agent 審查與測試；分開回報雙方結果與未驗證部分。
- 不自行 commit／push／部署／啟用或修改排程；需要時先列出具體清單請使用者確認。
- **在功能分支開發**（建議 `feature/tropical-cyclone`）。發布流程每輪都會 checkout 預設分支並跑完整測試，半成品推上 `main` 會直接影響現有 13 項圖資的發布。
- 不修改既有 13 項圖資的行為、UI、路由、保存政策。
- 不寫入任何密鑰；`CWA_API_KEY` 只由資料產生端從環境讀取。
- 只保存 JSON；圖片一律使用官方網址外連，不歸檔圖片本體（沿用現有政策）。
- Pillar 專案僅供**唯讀參考**：不執行其腳本、不複製其原始碼；借用的概念需註明檔案與函式名稱。

---

## 1. 產品範圍

### 1.1 定位 [已決定]

在既有網站新增獨立的 **Tropical Cyclone Center（熱帶系統專區）**：

1. 活躍熱帶氣旋的總覽。
2. 個別系統的機構分析、官方預報與原始圖資。
3. 傳統 NWP、AI 模式與 Ensemble 路徑的互動比較。
4. 適合靜態網站的更新、來源標示與異常處理。

不是把各國颱風圖堆在同一頁，也不是複製 Pillar。

### 1.2 V1 範圍 [已決定，2026-11-11 修訂]

| 面向 | V1 決定 | 暫不納入 |
|---|---|---|
| 涵蓋範圍 | **西北太平洋**（含南海） | 其他洋區；但資料結構保留 `basin` 欄位，日後擴充不需改契約 |
| 系統門檻 | TD（熱帶性低氣壓）及以上的已識別系統 | Invest、尚未正式分類的發展訊號 |
| 官方來源 | CWA、JMA、JTWC（依階段 1 驗證結果取捨） | NHC／CPHC、IMD、La Réunion、BoM、Fiji 等 |
| 預報 | 官方路徑＋傳統 NWP＋AI 模式＋Ensemble | 自行從原始氣象場追蹤氣旋；Google WeatherNext |
| 歷史 | 只聚焦當前活躍系統，保留近期少量 cycle | 歷史颱風搜尋、長期校驗資料庫 |
| 圖資 | 官方原圖外連；串接既有衛星／CIMSS／TCHP 頁 | 自行繪製 OHC、風切、駛流、侵襲機率等圖 |

頁面名稱建議用「Tropical Cyclone Center（Western North Pacific）」，不對外宣稱全球。

### 1.3 互動預報功能 [已決定：進階互動式]

| 必要功能 | 預期操作 | 資料前提 |
|---|---|---|
| 多路徑比較 | 同圖顯示／隱藏 JMA、JTWC、CWA 官方路徑 | 逐時效座標、來源、預報版本 |
| 多模式比較 | IFS、AIFS、GFS 等各自開關 | 模式識別、預報路徑 |
| 預報時間軸 | 選某個**實際有效時間**看各路徑位置 | valid time；不得只混用各來源的 +24h |
| 起報時間辨識 | 顯示每個來源的 initialization time | initialization 與 valid time 分離 |
| 相同起報時間比較 | 比較 00Z／12Z 等相同 cycle | 短期保留最近數輪 |
| Ensemble Spaghetti | 顯示多個成員，切換全部／單一 | member ID、各成員時序與缺值 |
| 節點細節 | 點選中心位置看時間、經緯度、強度 | 各欄位與單位 |

- **時間軸原則**：預設以有效時間對齊；該時刻沒有節點就不顯示，不默默插值。日後若做插值須標示為網站推算。
- **Ensemble 原則**：Spaghetti 只表示成員分散，不等於官方機率，也不把外包絡當官方預報範圍。
- **強度原則**：JTWC 多為 1 分鐘平均風速，JMA／CWA 多為 10 分鐘平均。不平均、不換算成「共同強度」；每筆保留來源、分析時間、平均期間、單位。

### 1.4 頁面 [已決定]

**A. Overview（總覽）**：活躍系統清單（名稱、各機構編號、位置、強度、最新資料時間）、地圖標記與清單連動、明確的狀態顯示（見 2.5）。

**B. Cyclone Detail（個別系統）**

- Overview：名稱、內部 ID、機構編號、中心、移動、氣壓、風速、來源與時間。
- Forecast：互動地圖、官方／模式路徑、有效時間軸、cycle 選擇、Ensemble。
- Analysis：JMA／JTWC／CWA 分析並列。
- Imagery：官方原圖與相關圖資；來源、圖像有效時間、抓取時間分開顯示。

---

## 2. 與現有系統整合的約束

這一節是 2026-11-11 唯讀檢視專案後整理的，**所有工作階段都必須遵守**。

### 2.1 既有限制需先解除

`HANDOFF.md` 第 2 節寫明「不增加其他圖資功能、颱風專區」。階段 S0 必須由使用者明確解除並記錄，否則後續代理會被舊限制擋住。

### 2.2 快照白名單

`fetchers/src/snapshots.py` 的 `REQUIRED`、`allowed_path`、`validate_resource` 只接受現有路徑與精確欄位。

- 颱風 JSON 必須在此註冊路徑與驗證器，才進得了快照、封裝與網站。
- **颱風資源一律列為「允許但非必要」**，不得加入 `REQUIRED`。否則現有線上快照會因缺檔而無法恢復。
- 連帶要檢查：`pages_package.site_summary`、`content_versions`、`verify_pages_build.py`、`snapshot_runner` 的清除邏輯。

### 2.3 失敗隔離

- 颱風來源全部失敗時，現有 13 項圖資的抓取、保存、部署決策不得受影響。
- 特別注意 `due_refresh.deployment_decision` 的「本輪嘗試來源全失敗則不部署」判斷，颱風任務失敗不可拖累它。
- 發布流程每輪跑完整 Python 與前端測試。颱風相關測試必須**阻網、不依賴當下時間、不依賴當下有無颱風**（11/9 曾因午夜測試假設錯誤擋住多輪發布）。

### 2.4 圖片與相依套件

- 只存 JSON，圖用官方網址。官方圖能否外連（防盜連、憑證、跨域）屬階段 S1 驗證項目。
- Python 目前只有 `requests`、`python-dotenv`。新增套件（尤其 BUFR 解析）要先在設計階段評估：是否純 Python、Actions 安裝時間、授權。
- 前端目前沒有地圖套件。選型時一併決定底圖來源（建議隨站打包的海岸線 GeoJSON，避免依賴外部圖磚服務）與跨 180° 經線的畫法。

### 2.5 狀態模型

| 狀態 | 意義 | 畫面 |
|---|---|---|
| OK_WITH_STORMS | 成功取得且有活躍系統 | 顯示系統 |
| OK_NO_STORMS | 必要來源完整成功後確認無系統 | 「目前無活躍熱帶系統」 |
| PARTIAL | 部分來源成功 | 保留成功資料，標示缺口 |
| UNAVAILABLE | 未發布、存取或解析失敗 | **不得顯示為無系統** |
| STALE | 只剩過期的最後成功資料 | 標示最後有效時間 |

總覽索引檔即使沒有颱風也要產出（內容為 OK_NO_STORMS），讓前端能區分「沒有颱風」與「沒有資料」。

### 2.6 路由

前端用 `BrowserRouter`，`pages-build.mjs` 為每個固定路徑預先產生 `index.html`。個別颱風的網址無法預先產生。

- 建議：固定入口 `/tropical`，個別系統用查詢參數（如 `/tropical?storm=…&tab=forecast`）。只需多產生一個靜態入口。
- 最終方案在 S3 定案，並同步修改 `pages-build.mjs` 與 `verify_pages_build.py`。

### 2.7 更新頻率與成本

- 颱風任務以新的 due 任務加入 `fetchers/policies/due-intervals.json`，沿用現有接力控制器，不新增排程。
- 初步建議 [待 S3 定案]：官方分析／預報 30–60 分鐘檢查一次；模式路徑依各模式發布時間，每 1–3 小時檢查一次。
- 無颱風時應快速結束，不抓模式資料。
- CWA 來源預算目前同批 600 次／240 秒，新增颱風 API 呼叫需計入。

### 2.8 檔案大小與清除

- 現有快照約 15KB，分層保留最多約 26 份。Ensemble 加多個 cycle 會放大很多倍。
- S3 需訂出：單檔上限、每颱風檔案數、保留幾個 cycle、Ensemble 是否進快照或另行處理。
- 系統消散後的資料清除規則需明訂（類似現行「history 只留當日」）。

### 2.9 淡季風險

西北太平洋冬季可能長時間沒有活躍系統。

- S1／S2 驗證時若有活躍系統，**立刻保存真實回應樣本**作為測試資料（僅本機 `.runtime`，是否可入版控依授權決定）。
- 沒有活躍系統時，以官方文件、歷史存檔樣本與手工構造資料開發，並在 HANDOFF 標明「未經真實活躍系統驗證」。

---

## 3. 進度表

每個 chat 結束時更新。狀態：未開始／進行中／完成／受阻。

| 階段 | 名稱 | 改程式 | 狀態 | 完成日期 | 備註 |
|---|---|---|---|---|---|
| S0 | 收尾與解禁 | 否 | 完成 | 2026-11-11 | 限制已解除並記入 HANDOFF；Pillar 無 LICENSE（僅參考概念，不複製程式碼）；分支 `feature/tropical-cyclone`（自 271ac2a）；本檔移至此處，舊筆記存 `archive/`；23 個本機公開 JSON 維持不提交 |
| S1 | 官方來源驗證 | 否 | 完成 | 2026-11-11 | 產出 `source-matrix.md`：CWA 可用；JTWC、JMA 有條件可用。實測時有活躍系統 CEMPAKA（JTWC 31W／JMA TC2638），已保存真實樣本到 `.runtime`。三個來源從 GitHub Actions 的可達性及無系統時的回應仍為 [待驗證]。獨立 Sub-Agent 已重測 JTWC 與 JMA |
| S2 | 模式來源驗證 | 否 | 完成 | 2026-11-11 | `source-matrix.md` 第 5–11 節：NOAA ATCF tracker 可用（識別碼即 JTWC 編號，如 `WP31`）；ECMWF BUFR 有條件可用（需 BUFR 套件；識別碼對不上 JTWC，CEMPAKA 為 `38W`，要用名稱或位置配對）。JTWC 降級方案 (b) 只能取得分析，取不到官方預報。BUFR 套件建議優先評估 `pybufrkit`＋`bitstring<4`。每系統每 cycle 的 JSON 實測約 90 KB、估計上限約 235–590 KB。真實樣本存於 `.runtime/tc-source-verification/s2/`。GitHub Actions 可達性與 `ubuntu-latest` 安裝時間仍為 [待驗證]。獨立 Sub-Agent 已重抓 ATCF 並重算大小 |
| S3 | 資料契約與設計決策 | 否 | 未開始 | | |
| S4 | 後端：活躍系統索引 | 是 | 未開始 | | |
| S5 | 前端：總覽頁 | 是 | 未開始 | | |
| S6 | 後端：官方預報路徑與配對 | 是 | 未開始 | | |
| S7 | 前端：個別系統頁與地圖 | 是 | 未開始 | | |
| S8 | 確定性模式路徑 | 是 | 未開始 | | |
| S9 | 後端：Ensemble | 是 | 未開始 | | |
| S10 | 前端：Spaghetti 與 cycle | 是 | 未開始 | | |
| S11 | Imagery 與站內串接 | 是 | 未開始 | | |
| S12 | 合併、上線與線上驗收 | 是 | 未開始 | | |

**可上線的里程碑**：S5 完成（總覽）、S7 完成（官方路徑）、S8 完成（多模式）、S10 完成（Ensemble）、S11 完成（完整 V1）。每個里程碑都可以單獨走一次 S12 的上線流程。

---

## 4. 工作階段明細

每個階段都有：目標、先讀、工作內容、產出、完成條件、不做的事。

### S0 收尾與解禁（不改程式）

- **目標**：取得乾淨的開發基準。
- **先讀**：`HANDOFF.md` 最後三節、`git status`。
- **工作內容**
  1. 列出本機未提交的修改（含 11/11 的 admission 重讀修正），請使用者決定是否先提交。
  2. 請使用者明確解除 HANDOFF 第 2 節「不增加颱風專區」限制，並寫入 HANDOFF。
  3. 查看 Pillar 專案的 LICENSE 與 README 授權說明，記錄可參考的範圍。
  4. 把本文件放到 `docs/tropical-cyclone/plan.md`（位置由使用者確認），舊筆記保留或移除由使用者決定。
  5. 建立功能分支（經使用者同意）。
- **產出**：更新後的 HANDOFF；授權檢查紀錄。
- **完成條件**：工作目錄狀態明確；限制已解除並有紀錄；分支策略已確認。
- **不做**：任何功能程式。

### S1 官方來源驗證（不改專案程式）

- **目標**：確認 CWA、JMA、JTWC 三個官方來源能否被 GitHub Actions 穩定、合法地自動取得。
- **先讀**：本文件 2.4、2.9；附錄 A.3；`fetchers/src/http_client.py`、`services/cwa_service.py`（了解現有抓取慣例）。
- **工作內容**：逐一實測，結果只寫入 `.runtime/tc-source-verification/`。可寫一次性驗證腳本放 `.runtime`，不放進 `fetchers/`。
  1. **CWA `W-C0034-005`**：欄位、無颱風時的回應、分析與預報是否同一支 API、更新頻率。
  2. **JMA**：是否有結構化資料（JSON／XML 電文）、路徑預報欄位、無颱風時的回應。
  3. **JTWC**：警報文字與圖檔的取得方式、雲端主機能否連線、憑證是否正常、圖檔能否外連。**這是最大風險，優先測。**
- **產出**：`docs/tropical-cyclone/source-matrix.md`，每個來源一列，欄位固定：

  | 欄位 | 說明 |
  |---|---|
  | 網址與格式 | 實際請求的網址、回應格式 |
  | 認證 | 是否需金鑰或帳號 |
  | 可達性 | 本機是否成功；從 GitHub Actions 是否成功（若本階段無法實測則標明） |
  | 頻率與延遲 | 官方發布週期、實測延遲 |
  | 內容 | 分析欄位、預報時效、強度定義與單位 |
  | 識別碼 | 系統編號與名稱的格式 |
  | 無系統時 | 回應長什麼樣 |
  | 圖檔外連 | 能否直接在瀏覽器以官方網址載入 |
  | 授權 | 使用條款、署名要求 |
  | 結論 | 可用／有條件可用／不可用，附理由 |

- **完成條件**：三個來源都有結論；JTWC 若不可用，提出替代來源或降級方案。
- **不做**：寫正式 Service；修改 `fetchers/` 或 `frontend/`。
- **備註**：從 GitHub Actions 實測需要推送一支臨時 workflow，須先取得使用者同意；未實測就標為 [待驗證]。

### S2 模式來源驗證（不改專案程式）

- **目標**：確認模式路徑資料的取得與解析方式。
- **先讀**：附錄 A.2；Pillar 的 `noaa_atcf.py`、`ecmwf_bufr.py`（唯讀，只看做法）。
- **工作內容**
  1. **NOAA ATCF tracker（先做）**：目前路徑、檔名規則、各 cycle 延遲、GFS／GEFS／AIGFS／AIGEFS 的模式代碼、西北太平洋是否涵蓋、系統識別碼格式。純文字，預期不需新套件。
  2. **ECMWF 熱帶氣旋 BUFR**：檔案位置、IFS／AIFS 確定性與 Ensemble 各自的產品、member 編號、識別碼、時效、無系統時的情況。
  3. **BUFR 解析套件評估**：候選套件、是否純 Python、在 `ubuntu-latest` 的安裝方式與時間、授權。
  4. 估算每個颱風每個 cycle 轉成 JSON 後的大小（確定性、各 Ensemble）。
- **產出**：在 `source-matrix.md` 補上模式來源；一份大小估算；套件評估結論。
- **完成條件**：ATCF 與 BUFR 各有「可用／不可用」結論；確認模式的系統識別碼能否直接對上 JTWC 編號。
- **不做**：寫正式解析器。

### S3 資料契約與設計決策（不改程式）

- **目標**：把 S1／S2 的結果變成可以照著實作的設計。
- **先讀**：`source-matrix.md`；本文件第 2 節；`snapshots.py`、`due_refresh.py`、`scheduling.py`、`snapshot_runner.py`、`pages-build.mjs`、`App.jsx`。
- **產出**：`docs/tropical-cyclone/design.md`，至少包含：
  1. **檔案路徑與 JSON 結構**：索引檔、每系統的分析檔、官方預報檔、模式路徑檔、Ensemble 檔；每個檔的精確欄位、時間格式（建議一律 UTC）、單位。
  2. **`cyclone_id` 規則**：內部 ID 的格式；與各機構編號的對應；配對規則（優先用編號，否則時間加位置）；模糊時不合併。
  3. **活躍判定**：哪些來源算「必要來源」；何時判定 OK_NO_STORMS；系統消散的判定與清除時機。
  4. **白名單註冊方式**：如何在 `snapshots.py` 加入非必要路徑與驗證器；舊快照相容性。
  5. **due 任務**：任務名稱、間隔、重試；失敗隔離做法。
  6. **大小與保留**：單檔上限、保留幾個 cycle、Ensemble 是否進快照。
  7. **前端**：路由方案、地圖套件與底圖、跨 180° 處理、按需載入策略。
  8. **新增相依套件清單**與理由。
  9. **測試策略**：測試資料來源、阻網方式、與時間無關的寫法。
- **完成條件**：使用者審閱並確認設計；[待驗證] 項目清楚列出。
- **不做**：實作。

### S4 後端：活躍系統索引

- **目標**：產出總覽所需的 JSON，並安全接進現有流程。
- **先讀**：`design.md`；`services/base.py`、`cwa_service.py`、`publication.py`、`snapshots.py`、`update_runner.py`、`due_refresh.py`。
- **工作內容**
  1. 新增颱風 Service（先接 S1 判定可用的官方來源），沿用 `http_client` 的重試與來源預算。
  2. 正規化成索引 JSON，含 2.5 的狀態。
  3. 在 `snapshots.py` 註冊非必要路徑與嚴格驗證；確認舊快照仍可恢復。
  4. 加入 due 任務與本機更新入口。
  5. 測試：來源成功／無颱風／部分失敗／全失敗／壞格式；舊快照相容；颱風失敗不影響既有部署決策。
- **完成條件**：阻網完整 Python 測試通過；本機隔離執行一次真來源（寫入 `.runtime`）；Sub-Agent 審查通過。
- **不做**：前端；預報路徑；模式。

### S5 前端：總覽頁

- **目標**：第一個可見頁面。
- **先讀**：`design.md` 前端章節；`App.jsx`、`api.js`、`DashboardPage.jsx`、`styles.css`、`pages-build.mjs`、`verify_pages_build.py`。
- **工作內容**
  1. 新增 `/tropical` 路由與靜態入口；更新 `pages-build.mjs`、`verify_pages_build.py` 及其測試。
  2. 總覽清單與五種狀態的畫面；來源與時間標示。
  3. 在 Dashboard 的「Ocean and Typhoon Potential」區塊加入入口。
  4. 地圖可先不做（留到 S7），或只做靜態位置標記。
  5. 元件測試涵蓋五種狀態與讀檔失敗。
- **完成條件**：前端測試與 Pages 建置驗證通過；本機瀏覽器實際看過五種狀態（用測試資料）；Sub-Agent 審查通過。
- **不做**：個別系統頁。
- **里程碑**：可走 S12 上線。

### S6 後端：官方預報路徑與跨機構配對

- **目標**：每個系統有各機構的分析與預報路徑資料。
- **工作內容**
  1. 解析各官方來源的預報路徑（逐時效位置、強度、起報與有效時間）。
  2. 實作 `cyclone_id` 配對；模糊案例不合併並記錄。
  3. 每系統的分析檔與官方預報檔；註冊白名單（動態路徑需用規則比對）。
  4. 消散系統的清除。
  5. 測試：同名不同系統、編號缺漏、跨日、來源時間差、單一機構缺席。
- **完成條件**：同 S4。
- **不做**：模式；前端。

### S7 前端：個別系統頁與地圖

- **目標**：Overview、Analysis 分頁與 Forecast 分頁的官方路徑部分。
- **工作內容**
  1. 加入地圖套件與底圖；跨 180° 處理。
  2. 個別系統頁框架與分頁；總覽清單可點入。
  3. 官方路徑圖層開關；節點點選顯示細節。
  4. 有效時間軸；起報時間標示。
  5. Analysis 並列表（保留各自風速定義）。
- **完成條件**：前端測試通過；本機瀏覽器實際操作過圖層開關、時間軸、節點；Sub-Agent 審查通過。
- **里程碑**：可走 S12 上線。
- **備註**：這是最大的前端階段。若額度不足，切成「頁面框架＋Analysis」與「地圖＋時間軸」兩個 chat。

### S8 確定性模式路徑（後端＋前端）

- **目標**：多模式比較。
- **工作內容**
  1. 後端：ATCF 解析（GFS 及 S2 判定可用的確定性模式）；對上 `cyclone_id`；模式路徑檔；註冊、任務、測試。
  2. 若 S2 判定 ECMWF 確定性產品可用且套件可行，一併加入；否則留到 S9。
  3. 前端：模式圖層開關、圖例、與官方路徑同圖比較；時間軸納入模式節點。
- **完成條件**：後端與前端測試通過；瀏覽器實際驗證；Sub-Agent 審查通過。
- **里程碑**：可走 S12 上線。
- **備註**：額度不足時後端、前端分兩個 chat。

### S9 後端：Ensemble

- **目標**：Ensemble 路徑資料。
- **工作內容**
  1. GEFS（ATCF）成員路徑。
  2. ECMWF IFS ENS、AIFS ENS（BUFR），視 S2 結論。
  3. 依 `design.md` 分檔；保留最近數個 cycle；過期清除。
  4. 大小上限的檢查與測試。
- **完成條件**：同 S4；另需實測快照大小與一輪執行時間仍在現有 20 分鐘 job 上限內有充裕餘裕。
- **不做**：前端。

### S10 前端：Spaghetti 與 cycle 選擇

- **目標**：完成互動預報方案。
- **工作內容**
  1. Ensemble 檔按需載入（選了才抓）。
  2. Spaghetti 圖層；全部／單一成員切換；成員點選。
  3. cycle 選擇器；相同起報時間比較。
  4. 效能：成員數多時的繪製方式。
  5. 明確的說明文字：分散程度不等於官方機率。
- **完成條件**：同 S7。
- **里程碑**：可走 S12 上線。

### S11 Imagery 與站內串接

- **目標**：完成 V1。
- **工作內容**
  1. Imagery 分頁：官方原圖外連，來源／圖像有效時間／抓取時間分開顯示；圖片失效提示沿用 `SourceImage.jsx` 的做法。
  2. 連到既有的衛星、CIMSS 風切與駛流、TCHP、SST 頁。
  3. 來源與授權署名區塊。
- **完成條件**：同 S7。

### S12 合併、上線與線上驗收（每個里程碑各做一次）

- **目標**：安全上線。
- **先讀**：`docs/data-flow.md` 第 9、13 節；`docs/manual-refresh-pages.md`。
- **工作內容**
  1. 列出將合併的提交與檔案清單，請使用者確認。
  2. 合併前確認：完整 Python 與前端測試通過；舊快照可恢復；颱風來源全失敗時既有流程照常。
  3. 合併後觀察至少兩輪自動發布：既有 13 項正常、颱風 JSON 出現在網站、`deployment.json` 正確。
  4. 更新 `docs/data-flow.md`（新來源、新任務、新路徑）、`fetchers/README.md`、HANDOFF。
  5. 準備回復方案：出問題時如何讓颱風任務停用而不影響其他項目。
- **完成條件**：線上實際驗證紀錄（含 run 編號）寫入 HANDOFF；未自然發生的情境列為待驗證。

---

## 5. V1 之後（不在本計畫階段內）

- 其他洋區與官方中心（NHC／CPHC、IMD、La Réunion、BoM、Fiji），以及全球衛星來源（GOES、Meteosat）。
- Google WeatherNext 等其他 AI 模式（下載條件待查）。
- 自行計算的圖表：OHC／TCHP 剖線、垂直風切、駛流場、侵襲比例、強度分布。
- Genesis（生成潛勢）、Verification（校驗）、Archive（歷史）。
- 路徑演變動畫、不同 cycle 的修正趨勢。

---

## 6. 每個 chat 的開場提示範本

把 `S?` 換成本次階段：

```text
請在 C:\Weather_Integration_Static 進行 Tropical Cyclone Center 的工作階段 S?。

開始前請依序閱讀：
1. AGENTS.md
2. HANDOFF.md 最新一節
3. docs/tropical-cyclone/plan.md 的第 0、2、3 節，以及 S? 的明細
4. （S4 之後）docs/tropical-cyclone/design.md 與 source-matrix.md

規則：
- 只做 S? 的範圍，不提前做其他階段，不修改既有 13 項圖資的行為。
- 不自行 commit、push、部署或更動排程；需要時先列清單讓我確認。
- 依 AGENTS.md 完成獨立 Sub-Agent 審查與測試。
- 結束前更新 plan.md 第 3 節進度表，並在 HANDOFF.md 新增一節。
- 如果額度快用完，停在可測試的狀態，並在 HANDOFF 寫明下一步的第一個動作。

先告訴我你讀完後對 S? 的理解與預計步驟，等我確認再開始。
```

---

# 附錄 A：參考專案 Pillar 研究摘要

> 以下保留自 2026-11-03 研究筆記，內容來自 Pillar 網站與 README 的公開資訊，**不等於本專案已實測**。Pillar 以西北太平洋為主、用 Python 直接產生網站；我們保留 React + Vite 前端，Python 只產 JSON。

## A.1 參考網站 Pillar's Tropical Cyclone Forecast：定位與做法

### A.1.1 參考網站的定位 [README／網站已展示]

Pillar 主要為**西北太平洋熱帶氣旋深度分析網站**：將官方預報、AI 與傳統系集模式、衛星、海洋和大氣環境場放在一起，並提供路徑、侵襲、強度與校驗圖表。

與我們的差異：Pillar 偏向**單一洋區／深度分析**；我們偏向**全球活躍系統／多來源整合與互動比較**。因此可參考其資料取得與圖表概念，不應假設其抓取範圍直接等於全球。

### A.1.2 大致運作流程 [README 已確認]

1. GitHub Actions 定期或接續觸發更新。
2. `forecast.py` 與專用模組下載及處理氣象、海洋、衛星和模式資料，配對系統、計算統計並產出圖表。
3. `generate_forecast_website.py` 產生 `docs/` 下的網站靜態內容。
4. GitHub Pages 提供瀏覽；README 表示整體網站約每 10–15 分鐘刷新，**不是全部上游產品每 10–15 分鐘起報**。
5. 使用快取、資料可用性檢查與更新工作流避免重複抓取、處理資料尚未發布等狀況；實際細節以最新 Workflow 與程式為準。

### A.1.3 重要程式檔案及用途

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

## A.2–A.3 參考網站使用的資料來源、產品與目的

### A.2 傳統數值與 AI 預報模式 [README 已列出；部分格式／端點待逐項測試]

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

### A.3 官方機構：分析與路徑預報

| 機構／中心 | 主要洋區角色 | 用途／顯示內容 | 取得方式與待確認事項 |
|---|---|---|---|
| JMA／RSMC Tokyo | 西北太平洋 | 位置、強度、官方預報路徑；與其他機構比較 | Pillar `official.py`；正式可用資料介面及完整欄位需測試 |
| JTWC | 多個太平洋、印度洋區域提供預報 | 分析與預報路徑、1 分鐘平均風速、官方警報圖 | Pillar 有展示；自動下載可用性及使用條件需驗證 |
| CWA | 臺灣及西北太平洋熱帶系統資訊 | 位置、強度與官方預報 | CWA Open Data `W-C0034-005`；通常須 API Key |
| NHC／CPHC | 北大西洋、東／中北太平洋 | 供我們未來全球涵蓋使用的官方路徑與地理資料 | **Pillar 不是以這些洋區為主**；我們應自行評估 NHC GIS／ATCF |
| IMD、La Réunion、BoM、BMKG、Fiji Met 等 | 北印度洋、南印度洋、澳洲／南太平洋 | 我們所需全球官方覆蓋 | **本專案待研究，不應說成 Pillar 已全面整合** |

**強度比較規則**：JTWC 常採用 **1 分鐘平均風速**；JMA、CWA 常採用 **10 分鐘平均風速**。資料不應直接平均或當成相同標準；每筆資料保留來源、分析時間、平均期間和單位。

### A.3b 衛星、海洋與環境場資料

| 資料來源 | 產品／欄位 | Pillar 呈現 | 資料的氣象意義 | 我們的建議 |
|---|---|---|---|---|
| Himawari-9（NOAA Open Data 在 AWS 的鏡像） | B13 10.4µm 紅外線亮溫 | 最近 3 小時衛星動畫（約每 10 分鐘一幀）、彩色強化／黑白 | 看雲頂溫度、對流與眼牆結構 | 可利用既有 Satellite 功能概念；全球須有其他衛星來源 |
| Copernicus Marine（CMEMS） | 海水溫度垂直剖面 | OHC／TCHP 地圖、沿 JTWC 路徑的 OHC 變化 | 了解海洋上層熱能與潛在增強環境 | V1 後續擴充；可能需帳號與金鑰 |
| HYCOM | 海洋溫度分析 | CMEMS 失敗時的 OHC 備援 | 類似上項 | 備援路線待驗證 |
| ECMWF AIFS-single | 500 hPa 高度、風速／方向 | 駛流場、流線、5880 gpm 等高線、預報路徑 | 協助解釋副高與導引氣流 | V1 後續擴充 |
| ECMWF AIFS-single | 200、850 hPa 風 | 200–850 hPa 垂直風切與沿路徑曲線 | 評估強度發展的環境條件 | V1 後續擴充 |

## A.4 參考網站呈現了哪些「圖檔／圖表／互動產品」，各自要回答什麼問題？

以下分類區分 **原始機構圖**、**網站加工生成圖**、**前端互動資料圖層**；不應把所有可見影像都稱為從機構直接下載的原圖。

| 功能分頁 | 圖檔、圖表或資料產品 | 類型 | 目的／使用者想知道的事 | V1（西北太平洋） |
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

## A.5 參考連結

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
