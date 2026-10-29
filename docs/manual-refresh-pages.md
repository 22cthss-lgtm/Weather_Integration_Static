# 手動抓取最新資料，再發布 GitHub Pages

本功能延用 `.github/workflows/pages-manual.yml`。只有 Run workflow，沒有排程、push
觸發、自動 commit JSON 或資料分支。本次只完成本機實作；尚未執行新版線上流程。

## 操作與輸入

原本的 `publish` 模式繼續提供「只發布指定有效資料與新版程式」；新增 `refresh`
模式在恢復有效資料後，呼叫原有 13 項 Fetcher（12 種圖資與雨量排行）。兩者都先
驗證輸入 SHA-256、有效期限、manifest、各 JSON 契約及網站必要資料。

每次明確選擇一種快照來源，不猜測 latest，不回退到 checkout 的 JSON：

- 首次接入：留空 `snapshot_run_id`，填原本三欄 `snapshot_release`、`snapshot_asset`、
  `snapshot_sha256`。沿用已上傳的 Release ZIP，前提是仍未過期。
- 後續：`snapshot_run_id` 填前次 Actions 網址 `/actions/runs/` 後的數字；留空
  Release tag/name。`snapshot_sha256` 填該次摘要中的**輸出快照 SHA-256**。
  程式只接受本儲存庫、預設分支、同一手動 workflow、已完成執行的
  `weather-snapshot` artifact。部署失敗但已保存有效快照的 run 也可選用。
- `snapshot_retention_days` 是每次必填的保存天數，支援整數 1–30，沒有預設值。
  範圍是既有 ZIP 格式的技術限制，並非替專案決定保存政策；首次執行前需由使用者決定。

同一 run 的整批 rerun 可能遇到不可變的同名 artifact 而停止，請以新的 Run workflow
重試；若只有 deploy 失敗，可重跑 failed job。不要為了重試而刪除有效快照。

## 跨次保存與期限

資料通過 Python 測試、前端測試、Pages 建置與逐檔 manifest 驗證後，先上傳
`weather-snapshot` Actions artifact，再上傳網站產物與部署。artifact 內只有
`weather-snapshot.zip`，其內容仍只有 `manifest.json`、`transport.json`、經驗證的
`data/**/*.json`。私人錯誤報告、原始觀測回應、.env、API Key 不上傳。

artifact 保存天數使用當次明確選擇值，也受 Repository 的上限設定限制。新抓取
快照的 ZIP 邏輯期限使用同一天數；`publish` 不重打包或延長舊 ZIP 的期限，故有效
恢復窗口是 artifact 可下載期限與 ZIP 有效期的較早者。上傳舊包不會讓資料永不過期。
Actions artifact 是有限期傳輸與復原媒介，不是永久備份。

artifact 過期、遭刪除、不存在、下載失敗、SHA 不符、JSON 損壞或 ZIP 過期，均停止
本次流程，保持現有網站。沒有隱藏回退，也不把這些情形當成首次空資料抓取。
可重新選擇另一份經確認仍有效的快照，或在本機用受保護流程產生／驗證新的完整快照，
人工打包上傳 Release。原始資料未變時重新打包只代表重新確認與傳輸，**不代表已抓新資料**。
不自動刪除既有 Release 或歷史 JSON；Release 檔案本身不因 ZIP 邏輯期限而自動消失。

目前使用者需選擇最新且適合的有效快照；尚未加入自動搜尋、永久「最後成功版本」指標
或永久儲存。選擇較舊快照會讓後續累積以那份資料為起點，應先核對 run 與摘要。

## 成功與失敗

- 個別來源仍沿用共用 HTTP 重試、等待、請求數與時間上限，不加第二層重試。
- 部分失敗：保留該資源通過驗證的舊 bytes、圖片／觀測時間、成功抓取時間；
  本次錯誤另列摘要。群組及子資料契約仍由原本驗證器檢查。
- 發布條件：至少一個產品成功、至少一項資源成功產生變更、所有網站必要資源及
  latest 對應日期歷史清單均存在且驗證成功。歷史缺時次可帶警告發布，不偽裝完整。
- 全部來源失敗（即使某失敗產品曾部分寫入）、或沒有資源變更：摘要顯示
  `no_successful_update`，跳過快照保存、測試／建置與部署，線上版本不變。
- 有變更但必要資料缺漏：摘要標示 `no_data`，流程失敗，禁止保存候選或部署。
- 摘要逐產品列 success/failed，逐資源列 updated/retained/no_data/incomplete_history，
  另列 changed 與 error_code。歷史不完整與有成功新增時次可以同時成立。
- 還原或下載失敗時無法得知每項來源狀態，不會捏造資源成功／失敗結果；Actions 的
  失敗步驟即為停止原因。所有來源失敗的正常跳過可能仍顯示 workflow 綠勾，需看摘要。
- 快照上傳失敗：禁止部署，舊線上版本及舊 artifact 不變；下次重新選擇舊有效輸入。
- 保存成功但建站產物上傳或部署失敗：已保存快照可從此 run 恢復，選 publish 重試，
  再次跑完整驗證；不需要重新抓所有來源。摘要的候選快照不等於已部署快照。
- 延用整個 workflow 的互斥、預設分支要求、舊 run 次序保護；新 run 的成功仍不保證
  GitHub 排隊 FIFO。測試或建置失敗不會上傳有效資料 artifact 或部署。

JSON 保存官方圖片網址，**不等於保存圖片本體**；來源可改寫圖片或讓網址失效。

## GitHub 設定

新增 Repository secret `CWA_API_KEY`：Settings → Secrets and variables → Actions →
New repository secret。只供 refresh 的資料產生步驟使用；publish 不需要它。
不要設為前端 VITE 變數，不填入 workflow input，不貼在對話或 Release 附件。

保留 Pages Source = GitHub Actions 與 github-pages environment。GITHUB_TOKEN 自動提供，
不需個人 PAT。build 使用 contents:read、actions:read、pages:read；deploy 使用
contents:read、actions:read、pages:write、id-token:write。artifact upload 使用 Actions
提供的上傳權限，不需要 contents:write。若組織限制官方 Actions 或 artifact 保存上限，
需先確認允許並在上限內選擇天數。

## 尚待確認的保存政策

1. 每次快照 artifact 的實際保存天數（本次未設定預設值）。
2. 是否需要超過 30 天／永久的外部快照備份，以及遺失時是否允許空起點重建。
3. 各圖資歷史 JSON 保存天數與清理方式；本次不清理、不截短任何既有歷史。
4. 人工 Release 備份保存多久、由誰清理；本次不自動刪除。

上述均不影響先完成本機驗證，但尚未決定保存天數前不要觸發新版線上更新。
