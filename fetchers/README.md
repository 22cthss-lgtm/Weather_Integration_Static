# JMA SST 靜態資料更新

在專案根目錄執行（Python 3.10 以上）：

```powershell
cd C:\Weather_Integration_Static
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r fetchers\requirements.txt
.\.venv\Scripts\python.exe -B fetchers\update_sst.py
```

後續手動更新只需最後一行。入口以自身檔案位置定位輸出，不依賴目前工作目錄。
OceanService 只匯入 `base.py` 與 requests，不載入 `config.py`、Flask 或 SQLite，
也不讀取原始專案。`config.py` 留給尚未移植的服務，本階段未修改。

## 資料流程與契約

JMA 日期腳本 → 原有 OceanService 組合圖片網址並確認 image Content-Type →
ImagePayload → JSON → api.js 的 fetchLatestImage("sst") → Dashboard 與 ImagePage。

輸出：`frontend/public/data/images/sst/latest.json`。
內容為單一物件，直接保留原 API／頁面使用的欄位：
`image_type`、`source`、`title`、`image_url`、`source_url`、`fetched_at`、`image_time`。
不新增資料庫 ID 或 JSON 外層包裝。

- `image_time`：JMA 每日分析的產品日期（YYYY-MM-DD）。來源只提供日期，
  不虛構午夜、觀測時刻或時區，也不以抓取時間替代。
- `fetched_at`：實際抓取 metadata 時間，ISO 8601 UTC，含 `+00:00`。
- 圖片保留原本 JMA 遠端 URL 與 fetched 查詢參數，不下載圖片檔。
- 來源、解析、驗證或寫入失敗時，命令以非零狀態退出並在 stderr 回報；
  不以空資料覆蓋舊檔。成功時先寫同目錄暫存檔，再原子替換 latest.json。

JSON 放在 Vite public 目錄，開發時提供 `/data/images/sst/latest.json`，
Build 時原樣複製到 `dist/data/images/sst/latest.json`。
api.js 使用 `import.meta.env.BASE_URL` 組合 SST 路徑並重新驗證快取，
讀取失敗不回退 Flask。其他產品仍使用原 API，尚不能獨立顯示資料。

## 前端啟動與驗證

```powershell
cd C:\Weather_Integration_Static\frontend
npm install
npm run dev
```

開啟 http://localhost:5173/，點選 JMA SST 卡片；詳細頁為 `/images/sst`。
若 Vite 因連接埠占用選擇其他連接埠，以終端機輸出為準。
更新 JSON 後重新整理頁面即可讀取；正式發佈需在更新 JSON 後重新 Build。

```powershell
cd C:\Weather_Integration_Static
.\.venv\Scripts\python.exe -B -m unittest discover -s fetchers\tests -v
cd frontend
npm test -- --run
npm run build
```

Python 單元測試使用獨立測試目錄；React 整合測試讀取實際產生的 latest.json，
執行前請先成功更新 SST。測試不會將模擬資料放入 public 目錄。

未來部署到 Repository 子路徑時，須另外設定 Vite base 與 React Router basename
及靜態主機的路由策略。本次只讓 SST JSON URL 尊重 base，
沒有建立 GitHub Repository、Actions 或 Pages 設定。

參考：[JMA 產品說明](https://www.data.jma.go.jp/goos/data/pub/JMA-product/him_sst_pac_D/Readme_him_sst_pac_D)、
[Vite public 目錄](https://vite.dev/guide/assets.html#the-public-directory)、
[Vite base](https://vite.dev/guide/build.html#public-base-path)。
