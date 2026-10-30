# 按到期項目更新：設計、操作與驗收

本批只準備本機程式與測試。現有 workflow 仍只有 workflow_dispatch，沒有 schedule、
push 觸發、自動 commit JSON 或資料分支。GitHub 操作須另經使用者確認。

## 已確認政策

`fetchers/policies/due-intervals.json` 集中定義全部十三項間隔與退避：

|項目|正常間隔|
|---|---|
|radar / satellite / rainfall_rankings|10 分鐘|
|rainfall|30 分鐘|
|temperature|1 小時|
|weather_chart / 850hpa|6 小時|
|cimss_wind_analysis / cimss_steering_flow|3 小時|
|sst / tchp / seaice_arctic / seaice_antarctic|1 天|

這是檢查策略，不代表官方發布週期。快速組明確為 radar、satellite、rainfall、
rainfall_rankings，跨輪失敗依序等待 10、20、40 分鐘，之後每 60 分鐘；其餘等待
30、60、120、240 分鐘，之後每 6 小時。HTTP 仍沿用共用有限重試與來源預算，
不把整個 Service 或整批再重跑。成功檢查即使內容未變，也重設失敗次數並更新到期時間。

`fetchers/policies/due-runtime.json` 記錄使用者確認的初期政策：資料 artifact、
排程狀態 artifact、新 ZIP 皆 7 天；固定時刻最久補昨天；歷史補查每 60 分鐘、
每時次初查後最多三次補查、每圖資每輪最多十二個歷史時次，只處理當日。
七天僅為本次線上測試設定，不是永久保存政策；後續須經使用者確認才調整。

## 固定時刻能力

目前十三項全用 interval，沒有新增未開發的任務。未來可配置：

```json
{"mode":"fixed","timezone":"Asia/Taipei","time":"14:00",
 "retry_delays_seconds":[1800,3600,7200,14400,21600]}
```

每輪最多選最近一個已到時刻：今天 14:00 尚未到時可補昨天；今天時刻已到後只選
今天，略過昨天及更早日期。成功記錄 completed_occurrence，避免重複執行。
同一時刻失敗依退避重試；新時刻不被昨天的重試時間阻擋，重新計算失敗序列。
長期停跑不會逐日補跑所有歷史。所有排程 instant 用 UTC 儲存，日界以 Asia/Taipei 計算。
若兩份狀態都遺失或無效，完成紀錄也無法恢復，最近一次到期工作可能重做；
此機制不保證狀態遺失時仍只執行一次。

## 內容版本與檢查狀態

內容版本 ID 是整站語意內容的 SHA-256，獨立於傳輸 ZIP 的 SHA-256。忽略 fetched_at、
歷史 updated_at 等執行欄位及程式自行加的防快取參數；保留實際圖片／觀測時間、
排行、群組子圖順序、歷史新增時次、缺漏變化與必要圖片內容雜湊。

固定網址、圖片時間未知，以及 CIMSS／Sea Ice 等可覆寫網址，使用圖片 bytes 的
SHA-256；不保存圖片本體。內容真的改變時以 `_wi_content` 雜湊參數更新圖片網址，
保留官方 URL，避免只靠相同 URL 或不可靠的 Last-Modified 推斷。沒有解析到的
image_time 仍為 null，不用檢查時間冒充圖片時間。

成功但未變時，還原原 JSON bytes，不新增資料 ZIP、不部署，僅保存小型狀態。
fetched_at 表示目前這份公開資料取得的時間；last_successful_check_at 表示最近
確認來源有效的時間。它們用途不同。第一次由未保存圖片雜湊的舊格式遷移時，需要
建立初次雜湊基準，可能產生一次新的資料版本；不能據此宣稱舊圖片本體已被保存。

`weather-scheduler-state` 只有一份 scheduler-state.json：

```text
schema_version / content_id / scheduler / history
scheduler: schema_version / content_id / saved_at / tasks
tasks: last_attempt_at / last_successful_check_at / next_due_at /
       next_retry_at / consecutive_failures / completed_occurrence /
       retry_occurrence / error_code
history: kind / date / HH:MM / classification / attempts /
         last_attempt_at / next_retry_at
```

狀態綁定特定 content_id。缺失、過期、損壞、身分不符時，保留已驗證資料，將所有
檢查重設為到期，記錄安全警告；不依舊 fetched_at 猜測檢查成功。重試與正常到期時間
由事實時間和配置重算，拒絕損壞的遠未來快取時間。狀態重新保存不代表重新抓取成功。

狀態只保留當日詳細資料及昨日未成功時次的 stopped 狀態；更早操作狀態移除。
這不刪除任何公開歷史 JSON。狀態不含 API Key、原始回應、私人錯誤、程序或本機路徑。
公開儲存庫的 artifact 不是私密儲存空間，故只允許上述安全欄位。

## 歷史缺圖與故障

最新圖成功與歷史完整度分開。歷史缺圖、補查失敗、每日雨量代表圖失敗不會讓
已成功的最新圖進入來源故障退避；摘要另外列出問題。
反過來，最新雨量圖失敗時，仍可保留同輪通過驗證的每日代表圖更新；
最新圖沿用舊檔與原時間並進入重試，無效每日資料則不得保留。
Service 的成功回報不能取代 JSON 驗證；最新資料無效或遺失仍視為失敗。

- 已驗證成功的歷史時次不重新探查；最新圖已驗證，不重複請求。
- 尚未初查的歷史時次標示 pending，分批消化十二次預算，不偽裝為來源 404。
- 404／410 不重試同一 HTTP 請求，記錄 missing，仍可探其他有效候選。
- 只有官方明確列出的衛星 10:40、22:40 缺測時段標為 official_missing，停止反覆探查。
  依據：[CWA 雲圖說明](https://opendata.cwa.gov.tw/opendatadoc/Observation/O-B0028_B0032.pdf)。
- timeout、連線錯誤、429／5xx 及無效內容，與缺圖分開統計，停止無意義的大量候選探測。
- 成功但尚無新產品為 checked_unchanged；不單憑 404 推斷永久缺測或官方尚未發布。
- 歷史補查最多初查加三次，每次至少隔 60 分鐘；跨日停止。已停止缺漏繼續存在
  原歷史 JSON 中，不自動刪除、不跨日掃描。雨量昨日／前日代表圖仍依官方清單更新。
  等待時間由 last_attempt_at 與政策重算，不信任可能損壞的 next_retry_at 快取。

## 自動快照恢復與滑動保存

auto 模式不需手填 run ID／SHA，搜尋同儲存庫、同受信任 workflow、預設分支、
workflow_dispatch 或 schedule 產生的有效 artifact。只接受已完成來源執行，但
不只挑綠勾：部署失敗前已保存的有效快照也可恢復。候選巡覽及失敗回退都有上限。

可信 GitHub API 的 artifact digest 校驗外 ZIP，再驗內 ZIP、manifest、逐檔雜湊、
資料契約及七天有效期。登入憑證只送 GitHub API，signed artifact 下載不轉送憑證。
權限錯誤直接報錯；暫時性網路錯誤有限等待重試。全部候選不可用就停止，不回退到
checkout 的未驗證 JSON，也不自動從零重建。

版本按首次內容建立時間排序、content_id 去重，不按重傳上傳時間。publish 相同
content_id 沿用資料 artifact，不新增資料備援名額、不重新抓取來源。

保存最近五個不同整站版本，另外保護目前線上版本，不重複計算，正常清理完成後
最多六個不同版本。快照上傳後必須重新下載驗證，部署後再以站點 deployment.json
核對 content_id／程式版本／run。無法確認保護資訊時跳過資料清理；刪除失敗時可能
暫時超過六份，保留資料安全優先，待後續成功執行或平台到期清理。

僅清理受信任且重新驗證的 weather-snapshot 附件；另保留最近兩個有效排程狀態。
不刪 Release、不刪 workflow run、不刪 Pages 產物或內部歷史 JSON。清理權限限定
獨立 cleanup job 的 actions:write，build 保持讀取權限。

三個期限分別是：

1. 主動按版本數清理：新資料保存、讀回及部署確認後才刪多餘附件；重複版本只占一格。
2. GitHub artifact 七天到期：即使沒有新版本，也由平台刪除。
3. ZIP 包內七天有效期：即使已自行下載保存，期限後仍拒絕自動恢復。到期不等於檔案損壞。

所以停止更新七天後可能沒有可自動恢復的備援。線上靜態站點不會因 artifact 到期
被刪除，但新的更新工作將停止，需人工提供新的、完整且經確認的有效快照。
本批不自動替舊 ZIP 續期；長期備份與從零重建仍未採用。歷史 JSON 保存天數亦未定案。

本機驗證副本約 26 KB／ZIP，六份約 156 KB；初始狀態約 4 KB，累積當日缺圖
紀錄後會增大，測試的完整兩日網格仍低於 200 KB。另保留兩份狀態；這只是目前
資料量估算，資料 ZIP 會隨累積歷史成長。Pages 建置 artifact（目前一日）與 CI
logs／cache 另計。

## 本機與首次手動線上驗證

本機離線驗證使用 unittest 與模擬 GitHub metadata／外 ZIP，不冒稱真實跨次雲端操作。
完整 Python suite：`python -B -m unittest discover -s fetchers/tests -v`；需先安裝
fetchers/requirements-dev.txt。前端用有效快照的隔離副本執行 npm test -- --run 及
npm run build:pages，再執行 verify_pages_build.py 比對原 manifest。

待使用者另行授權提交／推送後，手動 Run workflow：snapshot_source=auto、mode=refresh、
snapshot_retention_days=7；run ID、Release 與 SHA 欄留空。核對第一次狀態初始化及資料
雜湊基準建立，之後立即再跑一次，核對正常未到期項目略過、狀態保存與資料不重複部署。
若仍有當日待初查歷史時次，第二輪可以執行有界 history_recheck，不能宣稱零來源請求。
最後 mode=publish 驗證同 content_id 不新增資料 ZIP，並核對線上部署標記。

此版會在雲端新增 weather-scheduler-state artifact、deployment.json、上傳讀回驗證，
以及限定的附件清理。首次線上驗證必須明確列出這些 GitHub 操作再請使用者確認。
本次尚未啟用任何定時排程。

線上測試不得刪除唯一有效備援或刻意製造大量版本。若附件不足以觸發版本上限，
只核對清理範圍與保護條件，將實際超額刪除列為尚未線上驗證。先核對可信來源、
外／內 ZIP、逐檔校驗、有效期及可恢復性，再進行到期更新與部署；找不到有效
快照時停止並提出恢復方案，不放寬校驗或替換線上網站。
