# 第一版：手動發布指定快照到 GitHub Pages

> 本文保留第一次部署的背景與打包方式。現行 workflow 已加入可選的手動抓取模式、
> 前次 Actions artifact 恢復與必填保存天數；目前操作請見 [手動更新與發布](manual-refresh-pages.md)。

## 本版界線

只有 `workflow_dispatch` 手動觸發，不含 schedule、push、自動抓取、自動 commit、
資料分支或 API Key。程式碼與快照分開指定；本機 `.runtime` 不會被 Actions 讀取。
本次僅準備檔案與本機驗證，尚未在 GitHub 設定／執行／發布。

## 第一次如何把本機快照交給 Actions

1. 在本機打包指定的有效快照，**不要上傳整個 .runtime**：

   ```powershell
   cd C:\Weather_Integration_Static
   python -B fetchers/prepare_pages.py pack --snapshot .runtime/snapshots/snapshots/ffa7630cef7f46869e9b73d752206f81 --output .runtime/pages-manual/weather-snapshot-ffa7630c.zip
   ```

   此範例檔名若已存在，工具會拒絕覆寫；再次打包請換新檔名。輸出含 archive、
   snapshot_id、SHA-256、expires_at。打包前驗證 manifest/hash/資料契約與網站必要
   資源，再以 Actions 使用的 reader 自行還原檢查。原始快照與歷史資料不會被改動。

2. 待使用者確認並自行或另行授權 commit/push 程式後，在同一個 Repository
   手動建立一個 **Release**（建議例如 `pages-input-20261028`，可設為 pre-release），
   在附件區只上傳此 ZIP。這是人工傳輸輸入，不是資料分支或自動 commit JSON。

3. ZIP 根目錄只有 transport.json、manifest.json、data/。不包含 .env、私人報告、
   lock、來源原始回應或圖片本體。公開 repo 的 Release asset 亦公開，請只使用
   工具生成的包；官方圖片仍可能失效，JSON 不等於保存圖片本體。

4. 手動 Run workflow 填入：

   - `snapshot_release`：上述確切 Release tag。
   - `snapshot_asset`：確切 ZIP 檔名，不接受 wildcard。
   - `snapshot_sha256`：打包輸出的 64 字元小寫 SHA-256。

   Actions 使用只讀 GITHUB_TOKEN 從同一 repo 下載此附件，沒有外部 URL／latest
   快照猜測。附件不存在、無權限、外層 SHA 不符、內層校驗不符、契約無效或過期
   均會失敗停止；不回退到 checkout 內可能較舊的 JSON。

## 保存與過期

- 輸入包的**邏輯有效期預設 7 天**，從打包時刻起算，寫入 transport.json。
  `pack --valid-days` 可明確指定 1～30 天。有效期不是圖資／歷史保存天數，
  也不是圖片新鮮度保證；本版不決定或清理各圖資歷史保存期限。
- GitHub Release 附件本身**沒有本流程的自動刪除期限**，直到使用者刪除；
  包過期後即使還可下載也拒絕部署。過期可重新打包同一份仍有效的資料快照，
  換新附件／SHA；只更新傳輸期限，不改 image_time/fetched_at。
- Pages build artifact 明確保存 **1 天**，僅供該次部署傳遞，不當永久資料備份。
  若 artifact 過期，重新手動執行整條驗證／建置流程；輸入包仍須在有效期內。
- Release 附件刪除／不存在或過期時，禁止部署；目前已部署網站不會被本流程
  空資料取代。檔案存放方式與各圖資期限仍可在後續另行決定。

## GitHub 需要設定的項目（本次未操作）

1. 確認 repo 的 Pages 方案可用，Settings → Pages → Source 選 **GitHub Actions**。
2. `.github/workflows/pages-manual.yml` 必須進入預設分支後，Actions 頁才會有手動入口。
   本版也檢查執行 ref 必須是預設分支。
3. Settings → Actions 允許 workflow 與所使用的 GitHub 官方 actions。
4. `github-pages` environment 僅允許預設分支；可再設定 required reviewers 作人工
   發布批准（依帳號方案可用性）。部署 job 要求 pages:write / id-token:write，
   build 只有 contents:read / pages:read。若組織政策拒絕，先調整政策再手動重跑。
5. 上傳前述 Release ZIP。**不需要設定 CWA_API_KEY，也不需要額外 PAT**。

## 失敗閘門與版本

下載 → 過期／封包／SHA／完整性驗證 → Python unittest → npm ci / 前端測試 →
Pages build → 對照所選 manifest 的 20（或該包實際數量）份 JSON hashes／12 頁入口／
Hero 資產 → upload → deploy。任何上游失敗都不執行部署，不使用 continue-on-error。

歷史已知缺圖會列入摘要，但只要契約與必要檔案齊全即可發布；最新圖超前歷史
範圍也會列為警告。快照時間較舊不自動當成抓取失敗，因本版只發布指定既有資料。
摘要記錄 code SHA、snapshot ID、輸入 ZIP SHA。資料已上傳但部署失敗，可手動
重跑，使用同一指定輸入；不需要再抓來源。過期則重新提供有效輸入包。

workflow concurrency 序列化同一發布流程；GitHub 不保證 pending 執行 FIFO。
部署前額外拒絕在較新成功 run 之後執行的較舊 run number，避免舊佇列覆蓋。
這不是完整資料更新排程版本協定；後續刷新資料流程仍須另外設計。

## Base URL 與詳細頁刷新

configure-pages 提供實際 base_path；`npm run build:pages` 使用 PAGES_BASE_PATH，
同時編譯 BASE_URL、Router basename、Hero 與 JSON 路徑。支援 `/` 與 `/repo/`。

保留原本 BrowserRouter 與 `/images/{type}` 路由，不改成 HashRouter。
build 為 12 種圖資生成 `images/{type}/index.html`，內容與主入口一致。
Pages 對目錄 URL 可能加上結尾 `/`；有無結尾斜線都由同一路由顯示。
已知詳細頁直接開啟／重新整理不需要服務端 SPA fallback 或自訂 404 回導。
未知網址仍可正常 404；新增圖資時需同步共用的 image-types 與頁面契約。

## 本機驗證方式

```powershell
python -m pip install -r fetchers/requirements-dev.txt
python -B -m unittest discover -s fetchers/tests -v
```

前端測試與 build 應使用隔離工作目錄，將指定包恢復為該工作目錄 public/data，
避免本機常駐更新程式正在修改 fixtures。主專案 public 不需要覆寫。

```powershell
$snapshotSha = '請替換成打包輸出的64字元SHA256'
$isolatedData = 'C:\Weather_Integration_Static\.runtime\your-new-workspace\public\data'
python -B fetchers/prepare_pages.py restore --archive .runtime/pages-manual/weather-snapshot-ffa7630c.zip --sha256 "$snapshotSha" --destination "$isolatedData"
# 在隔離前端目錄：
npm ci
npm test -- --run
$env:PAGES_BASE_PATH = '/weather-test/'
npm run build:pages
```

verify_pages_build.py 另以 `--manifest` 指定原始 manifest 或 restore 輸出 JSON，
核對所有 JSON bytes／routes／Hero。瀏覽器驗證應用純靜態伺服器測試，不能以
Vite 開發伺服器的 SPA fallback 當作 Pages 刷新成功的證據。

## 本次準備提交的範圍

- .github/workflows/pages-manual.yml
- frontend/src/main.jsx、pages/DashboardPage.jsx、api.js、image-types.js
- frontend/scripts/pages-build.mjs、frontend/package.json
- frontend/src/pages-routing.test.jsx、pages-build.test.js
- fetchers/prepare_pages.py、verify_pages_build.py、src/pages_package.py
- fetchers/requirements-dev.txt、tests/test_pages_package.py、test_pages_workflow.py、test_verify_pages_build.py
- fetchers/README.md、docs/manual-pages.md、docs/superpowers/plans/2026-10-28-manual-pages.md

以上依賴前階段尚未提交的共用快照與 HTTP 等變更；不能只提交上述清單卻漏掉
fetchers/src/snapshots.py 等相依檔案。上次改動與 public JSON 的提交範圍應另行核對。
AGENTS.md 與 .runtime/ 已在本機忽略，不加入提交。這裡沒有執行任何 git add/commit/push。
