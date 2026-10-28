# Fetcher 資料保護與快照（第一階段）

## 保存方式與階段界線

獨立資料分支 `weather-data` 僅為候選方案，資料保存方式與各圖資保存期限尚未定案。
本階段沒有建立任何遠端分支、Actions、Pages、排程或自動 Git 操作，也不綁定
任何分支。從指定位置恢復的快照資料夾使用下列儲存格式：

```text
manifest.json
data/images/{type}/latest.json
data/images/{radar|satellite|rainfall}/history/YYYY-MM-DD.json
data/images/rainfall/daily/latest.json
data/rainfall/rankings/latest.json
```

保留已有歷史 JSON，不新增自動刪除或保存天數政策。manifest 含 schema_version、
snapshot_id 與每個公開 JSON 的 SHA-256；只接受既有圖資契約、群組數量／順序／
代表圖、歷史時次、雨量累積區間及排行契約。未知欄位、非允許路徑與 URL 中的
Authorization/API Key 等認證欄位會拒絕，不能把私人原始回應混入快照。

本機存放於 `.runtime/snapshots/`（Git 忽略）：

- `snapshots/{run_id}/`：不可覆寫的有效快照，內含上述 manifest/data。
- `current.json`：目前有效快照的指標。
- `reports/{run_id}.json`：私人執行報告，與公開快照分離。
- 鎖及暫存候選目錄：不應上傳。

只保存 JSON 與官方圖片網址，**不等於保存圖片本體**。官方圖片可能失效或固定
網址內容改變；校驗值驗證的是 JSON，不保證遠端圖片永久可取。

## 本機操作

在專案根目錄執行（需要 `CWA_API_KEY` 時仍僅讀取根目錄 .env／環境變數）：

```powershell
python -B fetchers/update_snapshot.py
```

第一次以 `frontend/public/data` 為 seed，先逐份驗證，損壞資源不作有效備援；
後續從 store/current.json 選取快照，驗證 manifest、檔案集合、hash 與資料契約
後恢復到全新候選目錄。如果已選快照損壞，立即停止，不靜默退回舊版 repo JSON。

可指定第一次的 seed 或明確指定另一份有效快照復原：

```powershell
python -B fetchers/update_snapshot.py --seed-data .runtime/bootstrap/data
python -B fetchers/update_snapshot.py --previous-snapshot .runtime/backup/snapshot
python -B fetchers/update_snapshot.py radar satellite --store .runtime/test-snapshots
```

有 current 指標時，預設優先恢復它；`--seed-data` 只用於尚無快照的 bootstrap。
指定的 seed 與 store 不可重疊；恢復目標也不能位於來源快照內。此命令不修改 frontend/public，不會
讓目前開啟的本機網站自動切換快照，也不啟動常駐程式。

原有 update_images.py、update_sst.py、watch_images.py 保持直接更新本機網站 JSON
的用途；它們也共用 HTTP 政策，但不建立 manifest 快照或新版資源報告。
未來 Actions 的保護入口應使用 update_snapshot.py；不要以直接更新指令代替。

## 重試與來源預算

所有 Services 經同一個 HTTP wrapper，不另加 Service／圖資／整批多層重試。
每輪批次所有產品共用來源額度，歷史掃描工作執行緒也共用。

| 項目 | 政策 |
| --- | --- |
| 嘗試次數 | 最多 3 次，含首次 |
| 重試原因 | 連線／逾時、HTTP 408/429/500/502/503/504 |
| 等待 | 2 秒、5 秒，各加 0～0.5 秒隨機延遲 |
| Retry-After | 支援秒數／HTTP 日期；超過本輪 30 秒等待上限就停止該來源 |
| 404/410、401/403 | 不重試；404/410 可作歷史缺圖，授權失敗回報錯誤 |
| CWA | 每輪最多 600 次 HTTP 請求／自第一次請求起 240 秒，共用官方與 opendata 額度 |
| JMA/KMA/CIMSS/NSIDC | 每來源每輪最多 80 次／90 秒，KMA 兩個官方網域共用 |
| 重新導向 | 最多 5 次，每次計費額度，僅允許同來源 HTTPS |
| 連續暫時性失敗 | 同請求 3 次失敗後停止本輪該來源後續候選探查 |

來源失敗後其他來源仍繼續。回應資料契約／解析錯誤不盲目重試整組。
Service 原有時次備援仍保留，但不可繞過來源額度。

時間上限為合作式 deadline：在請求、等待、實體回應及非串流 body 分段讀取時
檢查，並縮短連線／讀取 timeout；不是 OS 強制中止程序的硬截止。
已進行中的阻塞讀取仍受 socket timeout 影響，極端持續慢速傳輸可能延後下一個
deadline 檢查點。一般非串流回應另限制 16 MiB；串流圖片沿用 Service 的最小
圖片回應驗證，不下載圖片存檔。HTTP 層不記錄帶密鑰的請求 URL 或原始例外。

## 資源結果與資料保護

私人 report 分開記錄本次 started_at/finished_at、產品結果，以及逐資源的：

- `updated`：實際產生與舊檔不同且通過驗證的資料。
- `retained`：保留有效舊資料；attempted/error_code 說明本輪是否嘗試與失敗。
- `no_data`：沒有有效新資料也沒有有效備援，不建立空 JSON。
- `incomplete_history`：官方有缺圖／失敗，或歷史範圍落後於最新圖。

每筆另有 updated 布林值，區分不完整歷史是否實際更新。舊檔未被修改時，不能
因整個產品成功而算作更新。成功的 latest、history、daily 等子資源獨立保留；
產品失敗不會把已通過驗證的子資源全部撤回。

候選輸出若損壞，恢復先前驗證過的原始 bytes，並記 invalid_output；被刪除的
有效舊資源也恢復。失敗不更改舊 image_time/fetched_at；報告的嘗試時間與這些
欄位分離。歷史既有時次沿用原本成功 metadata。報告不序列化來源例外或密鑰。

完整候選需包含 12 張 Dashboard latest、雨量每日圖、排行，以及各 CWA latest
日期對應的歷史清單。歷史可以不完整但須明確揭露；缺少必要資源則禁止 promotion。

只有候選完整有效且至少一份資源實際更新，才建立快照並原子替換 current 指標。
全部失敗或沒有內容更新時保留指標；候選／快照／報告保存失敗也不先動指標。
本機鎖涵蓋 restore/update/promotion，避免同 store 的兩個命令交錯。
Windows 暫時拒絕目錄 promotion 時最多嘗試 4 次，等待 20/40/80 毫秒；仍失敗
就停止本次保存，不先替換舊指標。

退出碼 0 表示產生可發布快照且沒有已知失敗／不完整歷史；1 包括部分失敗，
**退出碼 1 不等於沒有可用新快照**，需同時讀 report.publishable/snapshot_id。

Dashboard JSON 請求失敗、資料基本格式無效或 15 秒內未完成，結束 Loading 並
顯示「目前無有效資料，請稍後重新整理。」；其他成功卡片仍顯示並保留路由。

## 第二階段待串接的規則

- 資料排程：publishable 才保存／發布；部分失敗列出摘要，全部未更新則跳過。
- 程式發布：可恢復完整有效舊快照後直接 build/test，不必重新抓來源。
- 遠端分支需比較基底版本、序列化更新及拒絕過期候選；本機鎖不能取代跨 runner 保護。
- 資料保存成功、部署失敗：資料快照保留；下輪從已保存快照恢復，可重試部署同版本。
- 資料保存失敗：不得以未保存候選部署；下輪從原有效快照重新開始。
- 網站部署版本與資料 snapshot ID 分別記錄；不能以「最後整個 workflow 成功」
  當作唯一恢復依據，也不能把保存成功當成部署成功。
- 以上雲端步驟尚未實作，本階段沒有改動線上網站。
