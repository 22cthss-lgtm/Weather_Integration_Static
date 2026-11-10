# 備援保留與歷史保存調整方案（2026-11-10）

> 狀態：**使用者已於 2026-11-10 確認，實作中**。依 AGENTS.md，每階段實作後由主代理驗證並交獨立 Sub-Agent 審查與測試；commit／push 及 commit message 需另行向使用者說明並確認。

## 已確認決定（2026-11-10）

| # | 項目 | 決定 |
|---|---|---|
| 1 | 分層保留 | 最近 6 個版本／48 小時內每 6 小時一份／14 天內每天一份（台北時間） |
| 2 | 資料快照 artifact 與 ZIP 期限 | 15 天（scheduler state 維持 7 天、2 份） |
| 3 | 舊日期 history | 不保留，只留台北當日；跨日後 10～30 分鐘可能顯示「當日資料尚未取得」，使用者接受 |
| 4 | 刪除快照內既有舊日期 history | 使用者同意（取代 HANDOFF「不擅自清除既有歷史資料」原則）；每日錨點快照仍含當日完整 history，最多 14 天 |
| 5 | 停擺通知 | 不做 |
| 6 | 部署前測試範圍 | 維持完整測試 |

階段一、二分兩批實作與審查。

## 0. 背景與現況（以 2026-11-10 09:26Z 線上實況為準）

| 物件 | 內容 | 大小 | 現行保留 | 實際效果 |
|---|---|---|---|---|
| `weather-snapshot` | 整站 JSON（13 任務 latest、排行、當日與舊日期 history、雨量每日圖） | 約 72 KB | 最近 5 個不同 content 版本＋線上版本（`artifact_store.cleanup_plan`，`[:5]`）；artifact 與 ZIP 包內各 7 天 | 雷達／衛星約每 10 分鐘產生新版本 → 線上 5 份為 08:44～09:26，**只能回溯約 40 分鐘**；7 天期限正常運作時用不到 |
| `weather-scheduler-state` | 各任務到期／重試／歷史探查狀態 | 約 2 KB | 最近 2 份；7 天；`cloud_snapshots.TTL_SECONDS=604800` 寫死 | 遺失只會全部重設為到期，不丟資料 |
| `github-pages` | 部署用建置產物 | 約 177 KB | 1 天 | 無備援價值 |

其他已確認事實：

- 自動恢復（`recover_snapshot`）只看最新 12 個 artifact，並選 **content 建立時間最新** 的有效版本；較舊版本只能經 `snapshot_source=explicit`＋`snapshot_run_id` 人工指定恢復。
- 每輪 cleanup 會下載並校驗最多 100 份 snapshot 才決定刪除（`cloud_snapshots.cleanup`）。
- ZIP 包內有效期上限為 30 天（`pages_package.py:100`）；artifact 期限由 `RETENTION_DAYS` 決定，`refresh_pages.py` 要求與 policy `artifact_retention_days` 相同，控制器（`chain_controller.py:214`、`:290`）寫死 `'7'`。
- 前端只讀**當日** history（`useCurrentImage.js:38`）；雨量每日圖讀 `daily/latest.json`，不讀舊 history。舊日期 history 每輪原樣帶入快照與網站，沒有清理機制，只含官方圖片網址。

## 1. 目標

1. 備援能涵蓋「錯誤但格式合法的資料延遲數小時才被發現」的情況。
2. 系統停擺的可自動接續期間，配合使用者實際能處理的時間。
3. 歷史保存與畫面實際用途一致，快照不無限成長。
4. 不改變既有安全原則：只用可信同 repo artifact、完整校驗、失敗不覆蓋線上、未知保護時不清理、不續期舊 ZIP、不放寬過期拒絕。

## 2. 階段一：快照改「分層時間保留」（建議優先）

### 規則（建議預設值，待確認）

保留以下集合的聯集（以 content 建立時間 `content_created_at` 判定，時區 Asia/Taipei）：

| 層 | 規則 | 數量上限 | 用途 |
|---|---|---|---|
| 近期 | 最新 **6** 個不同版本 | 6 | 約 1 小時內的快速回退（現行 5 → 6） |
| 6 小時錨點 | 過去 **48 小時**內，每個 00／06／12／18 時區間保留**最後一個**版本 | 8 | 錯誤延遲半天～兩天才發現 |
| 每日錨點 | 過去 **N 天**內，每個台北日期保留**最後一個**版本 | N（建議 14） | 長時間後回查／恢復 |
| 線上保護 | 目前線上 content 與本輪剛存版本 | 1～2 | 沿用 |

上限約 6＋8＋14＋2＝30 份 × 72 KB ≈ 2.2 MB（公開 repo 免費）。版本去重規則沿用：同 content 只留一份。

### 期限連動

- 每日錨點要保留 N 天，artifact 與 ZIP 包內期限必須大於 N 天。建議 **artifact／ZIP 期限 = 15 天**（N=14，留 1 天餘裕；ZIP 上限 30 天內）。
- `weather-scheduler-state` 維持 7 天與 2 份（狀態只需最新，延長無益）；`TTL_SECONDS` 不動。
- `github-pages` 維持 1 天。

### 需修改（實作時再精確核對）

- `fetchers/src/artifact_store.py` `cleanup_plan`：以上述分層取代 `[:5]`；保留既有「未知／不完整保護即不刪」與 saved 版本必須保留的檢查。
- `fetchers/policies/due-runtime.json`：`artifact_retention_days` 7 → 15。
- `.github/workflows/pages-manual.yml`：`snapshot_retention_days` 預設 7 → 15、說明文字移除「online test setting only」。
- `fetchers/chain_controller.py`：寫死的 `'7'`（admission 驗證與派發 inputs）改為讀同一 policy 值或常數 `15`。
- 測試：`test_artifact_store`（分層選取、跨時區邊界、同 content 去重、錨點與線上保護重疊、保護未知不刪）、`test_cloud_snapshots`、`test_chain_controller`、`test_pages_workflow`／`test_schedule_events`（新預設值）。
- 文件：`docs/data-flow.md`、`docs/due-refresh.md`、本機 HANDOFF。

### 影響與風險

- 每輪 cleanup 下載校驗份數由約 6 增至約 30（約 2 MB、增加數十秒）；仍在 cleanup job 10 分鐘上限內，實作時實測。若過慢，可改為只對「可能被刪」與錨點候選做完整校驗，但不得未校驗即刪除。
- 自動恢復行為不變（仍選最新有效版本）；錨點只供人工 `explicit` 恢復。需在操作文件寫明「如何從某天的錨點恢復」。
- 已存在的 7 天 ZIP 不改期限、不續期；新規則上線後，新產生的快照才會有 15 天。上線初期錨點會逐步累積，不是立即有 14 天。

### 需要你決定

1. 近期版本數（建議 6）、6 小時錨點範圍（建議 48 小時）、每日錨點天數 N（建議 14）。
2. artifact／ZIP 期限（建議 15 天；最長可到 30 天）。這同時決定「接力停擺多久後仍可自動接續」。

## 3. 階段二：舊日期 history 保存期限

### 建議

- 快照與網站只保留 **今天＋前 2 天（台北日期）** 的 `images/{radar,satellite,rainfall}/history/YYYY-MM-DD.json`；更早的在候選建立時移除。
- 理由：前端只讀當日；雨量畫面最多到「前日」；只存官方網址、不存圖片本體，舊連結價值有限。
- 舊日期檔仍會保留在每日錨點快照中（最長 N 天），需要時可人工從錨點取回。
- 本機 `frontend/public/data` 未提交的舊 history 檔不受影響（CI 以 artifact 為基底，不讀本機公開資料）。

### 需修改（實作時再精確核對）

- 候選建立／prepare 流程（`current_day.py` 或 `snapshot_runner.py` 的候選組裝處）加入有界、只限 history 路徑樣式的移除；同步更新 manifest／content_id 計算；`snapshots.validate_resource` 不需放寬。
- 跨日當輪會產生一次內容變更（正常發布）。
- 測試：台北跨日邊界（23:59／00:00、UTC 16:00）、只刪符合樣式的舊日期、不碰 latest／daily／rankings、刪除後 manifest 與 SHA 一致、恢復舊 ZIP（含較多舊檔）仍可通過。

### 待查證（實作前唯讀）

- CWA 雷達／衛星／雨量官方圖片網址實際保留多久（抽查數天前 history 裡的網址是否仍 HTTP 200）。若官方保留很久，可考慮放寬天數；若很短，可縮至只留今天＋前 1 天。

### 需要你決定

3. 保留天數（建議今天＋前 2 天）。
4. 這會刪除快照內既有的舊日期 history。HANDOFF 原則是「不擅自清除既有歷史資料」，因此需要你明確同意此政策改變。

## 4. 階段三（可選）：停擺通知

- 目前接力若中斷（例如 11/9 18:10Z 的 GitHub 端啟動失敗），只能等稀疏 cron 補回，沒有人會被通知。
- 選項：GitHub 帳號的 Actions 失敗通知（使用者設定，不需改程式）；或在 relay 失敗時建立／更新一個固定 Issue（需 `issues: write` 權限，屬權限擴張，需另外確認）。
- 建議先用 GitHub 內建通知設定，不擴張 workflow 權限。

## 5. 階段四（可選，之後再談）：部署前測試範圍

- 現況：每 10 分鐘完整跑 286 項 Python＋91 項前端測試；這週 11 次失敗中 6 次是測試本身時間假設（已修）。
- 選項 A（維持）：保留完整測試作安全閘門，持續把依賴真實資料或時間的測試改成決定性。
- 選項 B：若 `head_sha` 與上一次成功發布相同（程式未變），只跑資料契約校驗＋建置，略過程式單元測試；程式有變更的第一輪仍跑完整測試。
- 建議先維持 A；觀察一週沒有新的時間型失敗再評估 B。

## 6. 實作順序與驗收

1. 階段一（分層保留＋15 天）→ 主代理測試＋獨立 Sub-Agent 審查 → 你確認 commit／push → 上線後觀察：cleanup 耗時、artifact 清單出現 6 小時／每日錨點、自動恢復仍選最新、刪除名單符合規則。
2. 階段二（history 期限）→ 同上；上線後核對跨日當輪只刪預期舊檔、網站 JSON 與快照 SHA 一致。
3. 階段三、四依你決定。

每階段都不修改既有已上傳 ZIP、不續期、不放寬校驗；任何真實 workflow 派發或線上驗證操作需另行確認。

## 7. 決定清單（回覆即可）

| # | 項目 | 建議預設 |
|---|---|---|
| 1 | 近期版本數／6 小時錨點範圍／每日錨點天數 | 6／48 小時／14 天 |
| 2 | 資料快照 artifact 與 ZIP 期限 | 15 天 |
| 3 | 舊日期 history 保留 | 今天＋前 2 天 |
| 4 | 同意刪除快照內更早的 history（政策改變） | 需明確同意 |
| 5 | 停擺通知方式 | 先用 GitHub 內建通知 |
| 6 | 部署前測試範圍 | 先維持完整測試 |
