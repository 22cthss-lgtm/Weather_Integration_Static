# Tropical Cyclone Center — 官方來源驗證矩陣（S1）

> 實測日期：2026-11-11（來源探測約 10:47–10:51 UTC，臺灣時間 18:47–18:51；條款擷取約 10:53–10:58Z；獨立審查重測約 10:55–11:05Z；以各節標示為準）
> 實測環境：本機 Windows（Python 3.13 + requests，TLS 驗證開啟）；圖檔外連用桌面版內建瀏覽器，從第三方來源 `https://example.com` 載入。
> 原始回應與驗證腳本放在 `.runtime/tc-source-verification/`（不入版控）。
> 標記：**[實測]** 為本次親自取得；**[官方文件]** 為官方網頁說明；**[待驗證]** 為尚未實測，不得當成事實寫進程式。
> 實測時有活躍系統：**JTWC 31W／JMA TC2638（第 2632 號）／CWA 第 31 號颱風，國際名 CEMPAKA（中文：查帕卡）**，正在變性為溫帶氣旋。三個來源的真實樣本都已保存。

## 1. 總表

| 欄位 | JTWC | JMA | CWA W-C0034-005 |
|---|---|---|---|
| 網址與格式 | RSS `https://www.metoc.navy.mil/jtwc/rss/jtwc.rss`（RSS 2.0，內含當前產品連結）；產品 `…/jtwc/products/{basin}{nn}{yy}web.txt`（警報純文字）、`…{yy}.tcw`（警報資料檔：ATCF 樣式的 `T000/T012…` 行加全文；Content-Type 為 `binary/octet-stream`，需自行以文字解碼）、`…prog.txt`、`…fix.txt`、`…{yy}.gif`（警報圖）、`.kmz`、`{nn}{B}_{ddhh00}sair.jpg`；展望 `abpwweb.txt`（ABPW10） | (a) 官方 XML 電文（PULL 型 Atom）：`https://www.data.jma.go.jp/developer/xml/feed/extra.xml` → `…/xml/data/{時間戳}_0_VPTW60_010000.xml`（台風解析・予報情報 5 日予報）；(b) 非文件化 JSON：`https://www.jma.go.jp/bosai/typhoon/data/targetTc.json`、`…/data/{TCid}/forecast.json`、`specifications.json` | `https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005?Authorization=…&format=JSON`（JSON）；另有檔案型 `…/fileapi/v1/opendataapi/W-C0034-005?…&format=JSON\|XML`，會 302 轉址到 `https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Warning/W-C0034-005.json` |
| 認證 | 不需要 [實測] | 不需要 [實測] | 需要 `Authorization`（CWA 會員 API 授權碼）；不帶金鑰回 401 [實測]。轉址後的 S3 網址不帶金鑰也能取得 [實測]，但這是未公開的實作細節，**不採用** |
| 可達性 | 本機：全部 200，TLS 1.3，憑證有效（Amazon RSA 2048 M01，到期日 2027-03-19），由 S3＋CloudFront 提供 [實測]。**HTML 頁面有 CloudFront 阻擋**：獨立審查以自訂 UA 取得 `jtwc.html`、`html/notices.html`、`html/faq.html`，皆回 403「Request blocked」；同一自訂 UA 取得 RSS 與各產品都是 200；requests 預設 UA 只測了 RSS 與 `wp3126web.txt`，兩者都是 200 [實測，審查代理]。主代理用 `Mozilla/5.0 (compatible; …)` UA 取得 `jtwc.html` 為 200 [實測]。GitHub Actions：**[待驗證]** | 本機：200，TLS 驗證正常 [實測]。GitHub Actions：**[待驗證]** | 本機：200，TLS 驗證正常（verify=True 即成功）[實測]。GitHub Actions：**[待驗證]**（現有 CWA 抓取已在 Actions 運作，可推測可達，但未對這支 API 實測） |
| 頻率與延遲 | 西北太平洋警報在系統活躍時於每日 03／09／15／21Z 發布 [官方文件]；依發布制度，警報時刻比位置時刻晚 3 小時（警報 #21：位置時刻 06Z，09:00:16Z 上架，文中寫明下一報 15Z）[實測]；ABPW10 每日 06Z [官方文件，實測一致] | VPTW60 實測 00:40、03:40、06:40、09:41Z 各一則（每 3 小時一則，對應分析時刻 + 約 40 分鐘）[實測]；接近日本時的加密發布 **[待驗證]** | 官方：「6 小時（有熱帶氣旋活動時才即時更新）」[官方文件]；實測分析時刻 06Z（臺灣時間 14 時），S3 檔 07:26Z 更新（約 1.5 小時）[實測] |
| 內容 | 分析：位置、移動、1 分鐘平均最大風與陣風（kt）、34／50／64 kt 四象限半徑（nm）；預報：12h／24h…（一般最長 120h，本例因消散只到 24h）；中心氣壓與浪高在 REMARKS 文字中 [實測] | XML：階級、中心（度／度分）、移向移速、中心氣壓 hPa、10 分鐘最大風與陣風（kt 與 m/s）、暴風域／強風域半徑、預報圓 70% 半徑、最長 120h [實測＋官方文件]。JSON：同上，另有過去路徑點陣列（**只有 [lat, lon]，沒有時間戳**）與暴風警戒域幾何 [實測]。`extra.xml`（高頻度 feed）官方只保證保留最近 10 分鐘 [官方文件]；本次觀察到約 10 小時的條目（116 筆）[實測，審查代理]，但不能依賴這個數字。長期 feed `extra_l.xml`（官方說保留數日）可作補抓來源 [官方文件；網址未實測] | 分析：完整過去路徑（本例 22 點，從熱帶性低氣壓起算）、MaxWindSpeed／MaxGustSpeed（m/s）、hPa、移速 km/h、七級／十級風半徑與四象限 km；預報：InitialTime＋ForecastHour、70% 機率半徑、StateTransfer（如變性為溫帶氣旋）[實測] |
| 識別碼 | `31W`、檔名 `wp3126`（盆地＋序號＋年份）；ATCF 行 `2026111106 31W CEMPAKA` [實測] | `EventID`／`tropicalCyclone` = `TC2638`（含熱帶低壓的內部序號）、`typhoonNumber` = `2632`（命名後的颱風號）、英文名 `Cempaka` [實測] | `CwaTyNo` = `31`、`CwaTdNo` = `35`、`TyphoonName` = `CEMPAKA`、`CwaTyphoonName` = `查帕卡`、`Year` [實測] |
| 無系統時 | RSS 分區項目顯示「No Current Tropical Cyclone Warnings.」[實測，南半球分區]；ABPW10 的各分項沒有系統時寫「NONE」（本次只在 DISTURBANCE、SUBTROPICAL 分項與南太平洋分區看到），整個西北太平洋都沒有系統時的寫法 **[待驗證]**；不存在的產品網址回 **403**（S3 AccessDenied），不是 404 [實測] | `targetTc.json` 預期回空陣列 **[待驗證]**；XML feed 不會有 VPTW60 條目 [推論，待驗證] | 回應長相 **[待驗證]**。官方說只在有熱帶氣旋時才即時更新，S3 檔案可能保留舊內容，**不可只用「檔案存在」判斷有無颱風** |
| 圖檔外連 | `wp3126.gif`（1705×1060）、`31W_…sair.jpg`、`abpwsair.jpg` 從 `https://example.com` 以 `<img>` 載入皆成功 [實測，含畫面確認]；伺服器帶自訂 Referer 也回 200 [實測]；回應標頭有 `X-Frame-Options: SAMEORIGIN`，**不能用 iframe 嵌入**，`<img>` 不受影響。requests 取得的回應沒有 `Access-Control-Allow-Origin` 標頭，文字資料一律由後端抓取，不依賴瀏覽器端 fetch | 沒有靜態路徑圖；官網路徑圖由前端以 JSON 即時繪製 [實測]。不適用 | `https://www.cwa.gov.tw/Data/typhoon/TY_NEWS/PTA_{yyyymmddhhmm}-{hh}_{NAME}_zhtw.png` 等路徑圖從第三方來源載入成功 [實測]；檔名含分析時刻與預報時效，需由 `Data/js/typhoon/TY_NEWS-Data.js` 或 API 時間推算（規則 **[待驗證]**） |
| 授權 | [官方文件，瀏覽器擷取，原文存於 `.runtime/tc-source-verification/terms/`] 官方「Products and Services Notice」：網站資訊屬公開資訊，可自由散布或複製；但不得修改內容後宣稱為受著作權保護的作品；依 17 U.S.C. §403，以 JTWC 資料為主的作品需註明含 JTWC 資料且不受著作權保護。另說明產品**主要供美國政府機關使用**，一般使用者應以本國氣象機關與 RSMC 為準；FAQ 說明不提供訂閱服務 | 氣象庁ホームページ：適用公共データ利用規約（第 1.0 版，與 CC BY 4.0 相容）；需標示出典「出典：気象庁ホームページ（URL）」；加工時另註明「…を加工して作成」，且不得讓人誤以為是國家所作。XML PULL：單一 IP 每日下載超過 10GB 會被封鎖；氣象庁不保證送達。氣象業務法第 17 條（予報業務許可）對自行發布預報有限制 | 氣象資料開放平臺使用規範（依政府資料開放授權條款，與 CC BY 4.0 相容）：可不限目的利用及改作；需依附件「顯名聲明」標示「提供機關／交通部中央氣象署 [資料名稱]」及授權條款。CWA 官網圖片（非開放平臺資料）的條款**未個別查證**，沿用現有 13 項圖資的外連做法 |
| 結論 | **有條件可用**（理由見 2.1） | **有條件可用**（理由見 2.2） | **可用**（理由見 2.3） |

授權出處：
JTWC <https://www.metoc.navy.mil/jtwc/jtwc.html?notices>、<https://www.metoc.navy.mil/jtwc/jtwc.html?faq>；
JMA <https://www.jma.go.jp/jma/kishou/info/coment.html>、<https://xml.kishou.go.jp/xmlpull.html>、<https://www.jma.go.jp/jma/kishou/info/ml-17.html>；
CWA <https://opendata.cwa.gov.tw/dataset/warning/W-C0034-005>、<https://opendata.cwa.gov.tw/about/rules>。
三個來源條款的擷取原文與時間記錄於 `.runtime/tc-source-verification/terms/terms-evidence-20261111.md`。JTWC 條款頁由 JS 載入；審查代理以自訂 UA 用 requests 取得時被擋（403），所以條款原文改由瀏覽器擷取。審查代理只能確認矩陣與證據檔一致，無法獨立確認證據檔與原站一致。

### 驗證分工

- **主代理**：用 `scripts/probe.py` 實測三個來源；用內建瀏覽器做圖檔外連（含畫面確認）並讀取條款。
- **獨立 Sub-Agent**：2026-11-11 約 10:55–11:05Z 自行重測 JTWC 與 JMA（腳本與回應在 `.runtime/tc-source-verification/audit/`），未測 CWA，也未重做瀏覽器外連。結果：JTWC 與 JMA 的實測主張大致一致，另提出兩項阻擋問題（反爬蟲描述有誤、授權缺少證據），本文已修正。複查（只讀文件，未重新發出請求）確認兩項都已解決，另提出四項輕微用語修正，也已納入。

## 2. 各來源結論與理由

### 2.1 JTWC — 有條件可用

- **可用的理由**：本機可連線，憑證正常；RSS 與產品檔用兩種自訂 UA 都回 200，requests 預設 UA 抽測 RSS 與一個產品也是 200（HTML 頁面則會被 CloudFront 擋，見條件 6）；有機器可讀的 RSS 索引與 `.tcw`（ATCF 樣式行格式，比解析純文字警報穩定）；圖檔可以用 `<img>` 外連；資料屬公開資訊。
- **條件**
  1. GitHub Actions 能否連線 **[待驗證]**。主機在 CloudFront 上，本機經由台北節點，但美國海軍網站可能限制雲端 IP。實測需推送臨時 workflow，須另取同意。
  2. 頁面需註明含 JTWC 資料且不受著作權保護（17 U.S.C. §403），並說明 JTWC 產品主要供美國政府使用，臺灣以 CWA 為準。
  3. 「找不到」回 403 而不是 404，403 不能當成「沒有颱風」；有無系統應以 RSS 判斷。
  4. 產品網址依序號與年份組成（`wp3126`），以 RSS 連結為準，不自行猜測檔名。
  5. RSS 的 `link` 指向 `s3.amazonaws.com/www.metoc.navy.mil/...`，產品連結則是 `www.metoc.navy.mil`。若沿用 `http_client` 的「不跨網域轉址」規則，S4 要把網域納入 `source_name`。
  6. JTWC 的 HTML 頁面會依 UA 等條件被 CloudFront 擋下。正式程式只抓 RSS 與產品檔，不抓 HTML，並固定使用一個誠實標示身分的 UA，記錄在設計文件中。Actions 實測時要一併確認 RSS 與產品沒有被同一機制擋下。**不得以變換 UA 等方式繞過阻擋。**
- **降級方案**（若 Actions 實測無法連線）：
  - (a) 只用 JMA＋CWA 的官方路徑，不顯示 JTWC；
  - (b) 改用 NOAA／NRL 鏡像的 ATCF 資料（屬 S2 範圍，需另行驗證）；
  - (c) 只外連 JTWC 圖檔（由瀏覽器直接載入，不經 Actions），不解析其資料。
  - 無論哪種，頁面都要能在缺 JTWC 時顯示 PARTIAL，而不是 UNAVAILABLE。

### 2.2 JMA — 有條件可用

- **建議主要來源**：防災情報 XML（VPTW60）。它有官方規格文件與運用指針，欄位完整，含 10 分鐘平均風、hPa、預報圓，以及 120h 預報。
- **bosai JSON**：只作輔助。它方便取得完整過去路徑，回應也帶 `Access-Control-Allow-Origin: *`，但沒有官方文件，格式可能無預警改變，且 `pastTrack.json` 回 404，代表路徑檔名要靠實測得知。
- **條件**
  1. 只抓 Atom feed 新增的電文，避免重複下載，遠低於每日 10GB 的上限。
  2. 出典標示「出典：気象庁ホームページ」加 URL；轉換成我方路徑圖時，另註明是加工作成。
  3. 只轉載 JMA 的預報，不以 JMA 名義產生預報，避免觸及予報業務許可的限制。模式路徑（S8 以後）是否涉及此問題，留待 S3 評估。
  4. 無系統時的回應形式 **[待驗證]**。
  5. GitHub Actions 可達性 **[待驗證]**。

### 2.3 CWA W-C0034-005 — 可用

- **可用的理由**：
  - 分析與預報在同一支 API，同一份回應同時有 `AnalysisData` 與 `ForecastData`。
  - 欄位結構化，單位明確（m/s、hPa、km），並含中文名稱與臺灣颱風編號。
  - 授權明確，與 CC BY 4.0 相容。
  - 現有專案已持有 `CWA_API_KEY`，抓取流程也已在 Actions 中運作。
- **注意**
  1. 金鑰放在查詢參數；log、錯誤訊息、快照都必須遮蔽，現有 `rainfall_observation_service` 也是同樣做法。
  2. datastore API 是直接回應；fileapi 會轉址到 S3，但 `http_client` 禁止跨網域轉址，**S4 請用 datastore**。
  3. 依 `http_client` 的設定，CWA 的請求預算是 600 次／240 秒，新呼叫要計入。
  4. 無颱風時的回應 **[待驗證]**。官方說只在有颱風時即時更新，判斷有無颱風必須看 `TropicalCyclone` 陣列內容與時間，不能看檔案是否存在。
  5. 頁面需依附件放上「顯名聲明」。

## 3. 跨機構配對與強度比較（給 S3）

| 項目 | JTWC | JMA | CWA |
|---|---|---|---|
| 本例分析時刻 | 06Z（警報 #21） | 09Z | 06Z |
| 最大風 | 65 kt（1 分鐘平均） | 60 kt／30 m/s（10 分鐘平均） | 30 m/s（10 分鐘平均，依 CWA 慣例 [待驗證]） |
| 中心氣壓 | 983 hPa（06Z，REMARKS） | 985 hPa | 975 hPa |
| 分類 | Typhoon | STS（台風） | 輕度颱風 |

- 三家的分析時刻、平均期間和分類都不同，不能平均，也不能直接比大小（呼應附錄 A.3）。
- **配對鍵**：三家共有的只有**國際名稱（CEMPAKA）**加年份。命名前的熱帶性低氣壓沒有共通鍵：JTWC 有 `31W`、JMA 有 `TC2638`、CWA 有 `CwaTdNo 35`。S3 需決定命名前的配對規則，例如位置與時間最接近者，以及配對失敗時的呈現方式。
- **時間**：JTWC 用 Z（UTC），JMA XML 用 JST（+09:00），CWA 用 +08:00。正式程式一律轉成帶時區的 ISO 時間。

## 4. 尚未驗證（S1 結束時）

> 2026-11-12 更新：三個來源從 GitHub Actions 的可達性已補測，都是 200，見 10a。第 1、2 節中的「GitHub Actions：[待驗證]」以 10a 為準。

- 三個來源從 **GitHub Actions** 的可達性。需推送臨時 workflow，尚未取得同意，也沒有執行。
- JMA 與 CWA 在**無活躍系統時**的實際回應。目前有活躍系統，無法觀察。
- JMA 接近日本時的加密發布頻率；JTWC 的 TCFA（WTPN21-26）實際檔名。
- CWA 官網路徑圖檔名的完整規則；CWA 官網圖片的使用條款。
- 長時間穩定性（只做了單一時點的實測，未持續觀察）。

---

# 模式來源驗證（S2）

> 實測日期：2026-11-11（約 11:23–11:50 UTC，臺灣時間 19:23–19:50）
> 實測環境：本機 Windows（Python 3.13 + requests，TLS 驗證開啟，固定 UA，請求間隔 1 秒）。
> 原始回應、一次性腳本與輸出放在 `.runtime/tc-source-verification/s2/`（`raw/`、`scripts/`、`out/`、`venv/`，不入版控）。
> 實測時的系統：**CEMPAKA（JTWC 31W）**，正在變性；另有中太平洋的 **PENA（04C）**，預報路徑會越過換日線進入西北太平洋。兩者的真實樣本都已保存。
> 標記沿用 S1：**[實測]**、**[官方文件]**、**[待驗證]**。

## 5. 模式來源總表

| 欄位 | NOAA NCEP ens_tracker（ATCF） | ECMWF Open Data 熱帶氣旋路徑（BUFR） |
|---|---|---|
| 網址與格式 | `https://nomads.ncep.noaa.gov/pub/data/nccf/com/ens_tracker/prod/{system}.{YYYYMMDD}/{HH}/tctrack/{code}.t{HH}z.cyclone.trackatcfunix`；`system` 為 `gfs`、`gefs`、`aigfs`、`aigefs`。純文字 ATCF a-deck 行格式（逗號分隔）[實測]。同層另有 `genesis/` 目錄（未下載內容） | `https://data.ecmwf.int/forecasts/{YYYYMMDD}/{HH}z/{model}/0p25/{stream}/{YYYYMMDDHH}0000-{step}h-{stream}-tf.bufr`；`model/stream` 為 `ifs/oper`、`ifs/enfo`、`aifs-single/oper`、`aifs-ens/enfo`。BUFR edition 4，序列 3 16 082 [實測] |
| 認證 | 不需要 [實測] | 不需要 [實測] |
| 可達性 | 本機：200，TLS 驗證正常 [實測]。GitHub Actions：**[待驗證]** | 本機：200，TLS 驗證正常 [實測]。GitHub Actions：**[待驗證]** |
| 頻率與延遲 | 每日 00／06／12／18Z。檔案時間減 cycle 時刻（主代理 5–6 個 cycle，審查代理重抓 7 個 cycle）：GFS +4.7 至 +4.8h、AIGFS +4.0 至 +4.1h、GEFS +5.5 至 +5.6h、AIGEFS +4.6 至 +5.3h [實測]。樣本少，排程的等待時間應以上緣再加餘裕。只保留兩個日期目錄（當日與前一日）[實測]；每日最後一個 cycle 的實際可取得時間可能只略多於一天，舊目錄的刪除時點 **[待驗證]** | 每日 00／06／12／18Z。檔案時間減 cycle 時刻：IFS 確定性 +6.9h（00／12Z）、+6.2h（06／18Z）；AIFS 確定性 +7.1h（00／12Z）、+6.5h（18Z）；IFS 與 AIFS Ensemble +7.7h（00／12Z）、+7.3h（18Z）[實測，3–6 個 cycle]。保留最近 12 個 run [官方文件；主代理實測最舊可取得為 11/08 06Z，11/08 00Z 回 404，與此一致；審查代理稍後看到 13 個 run 同時存在，清除可能有延遲，程式不要假設恰好 12 個] |
| 內容 | 每個系統每 6 小時一點：緯度、經度（0.1°）、最大風（kt）、中心氣壓（hPa）、34／50／64 kt 四象限半徑（nm，每個門檻一行）。追蹤器追丟就結束，各成員長度不一。本次看到的最長時效：GFS 192h、GEFS 192h、AIGFS 150h、AIGEFS 240h，會隨 cycle 變動；**各模式的時效上限 [待驗證]** | 每個系統一個 BUFR message，Ensemble 每個成員一個 subset。每 6 小時一步：中心位置、中心氣壓（Pa）、10 m 最大風（m/s）及其位置、18／26／33 m/s 四象限半徑（m）。檔名時效：IFS 00／12Z 為 360h，06／18Z 為 144h [實測＋官方文件]；AIFS 四個 cycle 都是 360h [實測；06Z 由審查代理以 HEAD 確認] |
| 模式代碼／成員 | GFS：`avno`（另有 `avnop` 加熱力欄位、`avnx`）。GEFS：`ac00`＋`ap01`–`ap30`，另有 `aemn`（平均）。AIGFS：`agfs`（另有 `agfsp`）。AIGEFS：`a000`–`a030`，另有 `a000p`–`a030p` 與 `aimn`（平均）。檔內第 5 欄的代碼是檔名代碼的大寫；但 `p` 檔的第 5 欄不含 `P`（`avnop` 檔內是 `AVNO`），同目錄混讀會與主檔撞代碼 [實測]。`ac00`、`a000` 是否為控制成員 **[待驗證]**（依命名慣例推測是） | IFS Ensemble：成員 1–51；1–50 的 `ensembleForecastType` 為 4，51 為 0。IFS 確定性：成員編號 51、類型 0。AIFS Ensemble：成員 1–52；1–50 為 4，51 為 1，52 為 0。AIFS 確定性：成員編號 52、類型 0 [實測]。官方文件稱 IFS Ensemble 有 50 個擾動成員 [官方文件]；類型代碼的正式意義與 AIFS 第 51、52 號成員的身分 **[待驗證]** |
| 識別碼 | 前兩欄為盆地與序號，如 `WP, 31`、`CP, 04`、`SI, 03`，**與 JTWC／NHC 編號相同** [實測：WP31、CP04]。檔內沒有名稱 | `stormIdentifier` 如 `38W`、`04C`，`longStormName` 如 `CEMPAKA`、`PENA` [實測]。**CEMPAKA 是 `38W`，不是 JTWC 的 31W**；PENA 的 `04C` 則與 NHC 相同。編號 70 以上（`70W`、`71W`…）的名稱欄與編號相同，分析位置為缺值，看起來是模式自行生成的系統 [實測；70 這個界線的官方定義 **[待驗證]**] |
| 西北太平洋涵蓋 | 是。全球各盆地在同一個檔案 [實測：WP、CP、SI] | 是。全球各盆地在同一個檔案 [實測] |
| 無系統時 | 當日尚未發布的 cycle 與未來日期的目錄回 **403**（兩種不同的回應本體）；已過期的日期目錄、以及已發布目錄內不存在的檔名回 404 [實測]。不要依回應本體判斷狀態。全球都沒有系統時檔案是否存在、是否為空檔 **[待驗證]** | cycle 尚未發布回 404 [實測]。官方文件稱 tf 產品「只在有氣旋活動時」產出 [官方文件]。本次每個檔案都含 70 號以上的系統（單檔 5–55 個），所以**檔案存在不代表有已命名系統** [實測]。完全沒有檔案的情況 **[待驗證]** |
| 圖檔外連 | 不適用 | 不適用 |
| 授權 | NWS 網頁資訊屬公有領域，可用於任何合法用途；不得宣稱為自己的著作、不得暗示 NOAA／NWS 背書、修改後不得當成官方資料呈現；以其內容為主的著作需依 17 U.S.C. §403 註明含 NWS 資料且不受著作權保護 [官方文件]。NOMADS 首頁未找到明文的請求頻率上限 **[待驗證]** | CC BY 4.0 加 ECMWF 使用條款：需顯著標示來源，並包含指定文字「…based on data and products of the European Centre for Medium-Range Weather Forecasts (ECMWF)」、著作權聲明、授權聲明、免責聲明，以及是否經過修改；ECMWF 要求時須移除署名 [官方文件]。入口同時連線數限制為 500–2000 [官方文件] |
| 結論 | **可用**（見 6.1） | **有條件可用**（見 6.2） |

條款出處：
NOAA <https://www.weather.gov/disclaimer>；
ECMWF <https://www.ecmwf.int/en/forecasts/datasets/open-data>、<https://apps.ecmwf.int/datasets/licences/general/>、<https://confluence.ecmwf.int/display/DAC/ECMWF+open+data%3A+real-time+forecasts+from+IFS+and+AIFS>。
擷取的原始頁面在 `.runtime/tc-source-verification/s2/raw/terms/`，轉出的文字在 `s2/out/terms/`。

## 6. 各來源結論與理由

### 6.1 NOAA ATCF tracker — 可用

- **理由**：純文字，不需新套件；四個系統的檔名與代碼規則一致；識別碼就是 JTWC 編號；7 個 cycle 的延遲變動在 0.1–0.7 小時內；資料屬公有領域。
- **位置核對**：GFS 06Z 的 `WP31` 起始點是 28.8N 149.8E，JTWC 31W 06Z 警報是 29.1N 150.2E，相距約 50 km [實測]。
- **注意**
  1. 沒有名稱。名稱可由同一主機的 tcvitals 取得（見 7）。
  2. 未發布的目錄回 403，過期的回 404；兩者都不能當成「沒有颱風」。
  3. 只保留兩個日期目錄，不是 48 小時。每日 18Z 的 cycle 約 22–23.5Z 才發布，若前一日目錄在換日前後被刪，可補抓的時間可能只有約 25–30 小時（刪除時點 [待驗證]）。S3 的補抓設計應以「約一天」為準。
  4. Ensemble 是每個成員一個檔案：GEFS 31 個、AIGEFS 31 個。每個 cycle 兩個 Ensemble 約 62 次請求，S3 要計入請求預算並設定間隔。
  5. 同一個時效每個風速門檻一行，要合併成一點。
  6. 檔案含全球系統，要依盆地篩選。**中太平洋的系統可能越過換日線進入西北太平洋，但編號維持 `CP`**（本次 PENA 的預報路徑即是）；只取 `WP` 會漏掉這類系統，S3 需決定如何處理。
  7. 有現成的平均檔（`aemn`、`aimn`），可評估是否直接取用；但平均檔只有 34 kt 門檻的行，風圈資訊不完整 [實測，審查代理]。
  8. GitHub Actions 可達性與正式的請求頻率上限 **[待驗證]**。

### 6.2 ECMWF 熱帶氣旋 BUFR — 有條件可用

- **理由**：四個產品都能取得並解碼；授權明確；確定性檔約 9.6–37 KB，Ensemble 檔約 0.3–1.1 MB。
- **條件**
  1. **需要 BUFR 解析套件**，會新增相依套件（見 8）。
  2. **識別碼不能直接對上 JTWC**（38W 對 31W），而且同一系統的編號會跨 cycle 改變（11/11 12Z 起變成 31W，見 10a）。本次可用名稱配對；命名前的系統只能用位置配對。ECMWF 00Z 的分析位置是 27.7N 146.6E，GEFS 同時刻的 `WP31` 是 27.7N 146.8E [實測]。配對規則由 S3 決定。
  3. 要濾掉 70 號以上的系統，否則資料量會大很多（見 9）。
  4. 已命名系統**不一定每個 cycle 都出現**：PENA 在 11/10 12Z 與 11/11 00Z 的四個檔案中都有，在 11/10 18Z 的四個檔案中都沒有 [實測]。原因 **[待驗證]**；程式不能把單一 cycle 缺少某系統當成它已消散。
  5. 官方文件的產品表只列出 IFS 的 tf 產品，沒有列出 AIFS 的 tf 產品；AIFS 的檔案是實測存在 [實測]。AIFS tf 是否為正式支援的產品 **[待驗證]**。
  6. 延遲比 NOAA 長約 2 小時。
  7. 頁面需依條款放上指定的署名文字與授權聲明。
  8. GitHub Actions 可達性 **[待驗證]**。

## 7. JTWC a-deck／b-deck（S1 降級方案 (b) 的前提）

| 來源 | 結果 |
|---|---|
| `https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{YYYYMMDD}/{HH}/atmos/gfs.t{HH}z.syndata.tcvitals.tm00` | 200。內含 `JTWC 31W CEMPAKA 20261111 0600 291N 1502E …` 與 `NHC 04C PENA …`，位置與 JTWC 06Z 警報相同；06Z 檔的時間是 08:41Z [實測]。**同時提供 JTWC 編號、名稱與分析位置** |
| UCAR RAL TCGP `https://hurricanes.ral.ucar.edu/repository/data/bdecks_open/2026/bwp312026.dat` | 200。最佳路徑分析（`BEST`），最後一筆是 06Z，檔案時間 09:17Z [實測] |
| UCAR RAL TCGP `…/repository/data/adecks_open/awp312026.dat` | 200，3.4 MB，87 種代碼 [實測]。**沒有 JTWC 官方預報**（第 5 欄沒有 `JTWC`、`WRNG`、`OFCL` 代碼），只有 `CARQ`（分析，行內註明來自 `NCEP_TCVITALS`）和各模式的路徑 |
| NHC `https://ftp.nhc.noaa.gov/atcf/aid_public/`、`…/atcf/btk/` | 200，但只有 AL、EP、CP，沒有 WP [實測] |
| NRL `https://www.nrlmry.navy.mil/atcf_web/docs/tracks/2026/` | **403 Access Denied** [實測]，未嘗試繞過 |
| `www.ssd.noaa.gov` | DNS 解析失敗 [實測] |

- **結論**：降級方案 (b) **只能取得 JTWC 的分析（現在位置與強度），取不到 JTWC 的官方預報路徑**。若 Actions 連不上 JTWC，官方預報路徑只能靠 JMA 與 CWA。
- UCAR 說明 JTWC 的資料多數不公開，TCGP 是取得許可後才公開散布 JTWC 的即時分析 [官方文件]。我方再利用這份資料的條件 **[待驗證]**，較穩妥的做法是只用 NOAA 主機上的 tcvitals。

## 8. BUFR 解析套件評估

| 項目 | `eccodes`（可另加 `pdbufr`） | `pybufrkit` |
|---|---|---|
| 版本 | eccodes 2.50.0；pdbufr 0.16.0 | 0.2.25 |
| 是否純 Python | 否。Windows 的 wheel 內含 C 函式庫；Linux 的 `eccodes` wheel 不含函式庫，另外相依 `eccodeslib` 的二進位 wheel [實測：wheel 中繼資料] | 是。但只有 sdist，沒有 wheel；必須搭配 `bitstring<4`（實測 3.1.9）。搭配 bitstring 5.0.0 會在解碼時出錯 [實測] |
| 連帶相依 | numpy、cffi、attrs、findlibs；加 pdbufr 再多 pandas、pint 等 | bitstring、six |
| 授權 | Apache 2.0 | MIT（bitstring 也是 MIT）|
| 本機安裝 | eccodes＋pdbufr 共 84 秒，venv 204 MB [實測，Windows，含下載] | 41 秒，venv 33 MB [實測，Windows] |
| Linux 下載量 | `eccodes` 與相依 wheel 約 17 MB（其中 numpy 16.7 MB），`eccodeslib` 另 9 MB [實測：`pip download` 指定 manylinux／cp313]。`eccodeslib` 是否還有其他相依 **[待驗證]** | sdist 7.3 MB 加 bitstring 0.2 MB [實測] |
| `ubuntu-latest` 安裝時間 | **[待驗證]** | **[待驗證]** |
| 解碼真實樣本 | 成功。Ensemble 檔（約 1 MB，48–56 個 message）約 1.6–1.7 秒 [實測] | 成功。同一個檔約 6.5–7 秒 [實測] |
| 結果一致性 | 兩個套件對 11/11 00Z 四個檔案中 `38W` 的成員編號範圍與第 1 個 subset 的前 6 個緯度值相同 [實測] | 同左 |
| 注意 | Ensemble 檔是 compressed BUFR，要用 `#n#key` 逐一取值；`extractSubset` 對這個模板會報 Internal error [實測] | 要鎖定 bitstring 版本；套件的維護狀況未查證 |

- **結論**：兩者都能用。**建議 S3 優先評估 `pybufrkit`＋`bitstring<4`**：純 Python、下載量小、不引入 numpy，解碼時間每檔約 7 秒可接受。`eccodes` 作為備案，解碼較快但相依較重。
- 不建議用 `pdbufr`：它是 `eccodes` 上的包裝，還多帶 pandas。本次沒有用 `pdbufr` 實際解碼。
- `ubuntu-latest` 的實測安裝時間已補（見 10a）：兩者都只要 4–5 秒，結論不變。

## 9. 大小估算

**方法**（腳本 `s2/scripts/size_estimate.py`，輸出 `s2/out/size_estimate.txt`）：把真實樣本轉成假設的精簡 JSON（minified），再量位元組數與 gzip -9 後的大小。JSON 形狀只是估算用，正式契約由 S3 決定。

- 形狀：`{"model","cycle","storm","name","members":[{"m":成員,"t":[[時效,緯度,經度,氣壓,風速],…]}]}`
- 變體 A：每點 5 個數值。變體 B：每點再加 12 個風圈半徑。
- 沒有中心位置的點不輸出。
- ECMWF 時效 0 的點取 significance=1 的中心位置，各成員相同；各成員自己的擾動分析位置沒有輸出。
- 變體 B 的缺值寫法兩個來源不同：ATCF 缺少的門檻補 `0`，BUFR 缺值寫 `null`。兩種來源的 B 每點大小不能直接比較。

**每點大小** [實測]：Ensemble 的變體 A 約 25–28 bytes，變體 B 約 50–66 bytes。確定性檔點數少，固定開銷占比高，每點 28–57 bytes（A，不計只有 1 點的檔案）。

**實測大小（每個系統、每個 cycle）**

| 產品 | 系統 | 成員 | 點數 | A：JSON／gzip | B：JSON／gzip |
|---|---|---|---|---|---|
| IFS Ensemble 11/10 12Z | PENA（長路徑） | 51 | 1250 | 31.5 KB／9.0 KB | 65.5 KB／14.8 KB |
| IFS Ensemble 11/10 12Z | CEMPAKA（消散中） | 51 | 349 | 8.8 KB／2.5 KB | 22.2 KB／7.9 KB |
| AIFS Ensemble 11/10 12Z | PENA | 52 | 963 | 24.4 KB／6.2 KB | 48.0 KB／7.4 KB |
| GEFS 11/11 00Z | PENA（`CP04`） | 31 | 650 | 16.5 KB／4.4 KB | 32.4 KB／5.2 KB |
| AIGEFS 11/11 06Z | PENA（`CP04`） | 31 | 668 | 16.8 KB／4.2 KB | 33.0 KB／4.8 KB |
| GFS 11/10 00Z | PENA（`CP04`） | 1 | 33 | 0.9 KB／0.4 KB | 1.7 KB／0.5 KB |
| IFS 確定性 11/10 12Z | PENA | 1 | 13 | 0.4 KB／0.2 KB | 0.7 KB／0.3 KB |

**估計上限**（每個成員都追到最長時效；A 取 26 bytes／點，B 取 65 bytes／點，兩者是樣本的典型值，不是最壞情況）

| 產品 | 成員 × 點數 | A | B |
|---|---|---|---|
| IFS Ensemble（360h，61 點） | 51 × 61 = 3111 | 約 81 KB | 約 202 KB |
| AIFS Ensemble（360h，61 點） | 52 × 61 = 3172 | 約 82 KB | 約 206 KB |
| GEFS、AIGEFS（假設 240h，41 點；上限 [待驗證]） | 31 × 41 = 1271 | 各約 33 KB | 各約 83 KB |
| 單一確定性（61 點） | 61 | 約 2 KB | 約 4 KB |

- **每個系統每個 cycle 合計**（四個 Ensemble 加四個確定性）：實測的長路徑系統約 **90 KB（A）／183 KB（B）**；估計上限約 **235 KB（A）／590 KB（B）**。實測的合計取自不同 cycle 的 PENA 樣本。Ensemble 樣本 gzip 後約為原大小的 15–36%。
- 最壞情況（每點數值都取最長寫法：A 約 28 bytes、B 約 75 bytes）約 255 KB（A）／680 KB（B）[審查代理估算]，量級相同。
- 對照：現有快照整份約 15 KB（引自 plan 2.8，本次未重量）。**單一系統單一 cycle 的合計是它的 6 倍（實測 A）到 12 倍（實測 B）；估計上限是 16 倍（A）到 39 倍（B）**。多個系統加多個 cycle 會再倍增。S3 必須決定 Ensemble 是否進快照、保留幾個 cycle、是否只保留變體 A。
- 70 號以上的系統若不濾掉：單一 Ensemble 檔的這類路徑合計約 137–339 KB（A）[實測]。
- **限制**：樣本只有兩個系統、三個 cycle。CEMPAKA 正在消散，路徑很短；PENA 的 IFS Ensemble 點數是估計上限的 40%。生命期長的強颱可能更接近上限。

## 10. 尚未驗證（S2 結束時）

- ~~各來源從 GitHub Actions 的可達性、BUFR 套件在 `ubuntu-latest` 的安裝時間~~：已於 11/12 補測，見 10a。仍未驗證的是：NOMADS 目錄清單在 Actions 上失敗的原因、JTWC 個別系統產品從 Actions 的可達性、Ensemble 檔在 Actions 上的解碼時間、長期穩定性。本節以上各表中的「GitHub Actions：[待驗證]」以 10a 為準。
- 全球都沒有系統時，ATCF 檔與 ECMWF tf 檔的實際狀況。
- 各 NOAA 模式追蹤器的時效上限；`ac00`、`a000` 是否為控制成員。
- ECMWF `ensembleForecastType` 代碼的正式意義、AIFS 第 51／52 號成員的身分、70 號界線的官方定義、AIFS tf 是否為正式產品。
- NOMADS 舊日期目錄的實際刪除時點（需跨日觀察）；兩種 403 回應本體各在什麼情況出現。
- PENA 在 18Z 檔案中缺席的原因。
- NOMADS 的正式請求頻率上限。Pillar 的 `noaa_atcf.py` 模組說明提到每分鐘約 120 次，這不是官方來源，未採信。
- UCAR TCGP 資料的再利用條件。
- `genesis/` 目錄的內容與用途。
- 長時間穩定性（只做了單日實測）。

## 10a. GitHub Actions 實測（2026-11-12 10:18Z，S2 補測）

> 方式：經使用者同意，推送一支臨時 workflow 到 `feature/tropical-cyclone`（`bba4a17`），由 push 觸發執行一次（run 43199226792，`ubuntu-latest`，Python 3.13.18），隨即刪除（`50618f4`）。每個網址用 curl 請求一次，固定 UA，不重試，只記錄狀態碼、位元組數、耗時。
> 結果由使用者從執行摘要頁貼回；主代理無法登入讀取 log，**沒有獨立 Sub-Agent 複核**。草稿保存在 `.runtime/tc-source-verification/s2/actions-draft/`。
> 這是**單次**測試，只能證明當下可達，不能保證長期穩定。

### 可達性 [實測，Actions]

| 來源 | 結果 |
|---|---|
| JTWC | RSS、`abpwweb.txt`、`abpwsair.jpg` 都是 200 |
| JMA | `extra.xml`、`targetTc.json` 都是 200 |
| CWA W-C0034-005 | 不帶金鑰 401，帶金鑰 200（11,347 bytes）|
| NOAA NOMADS 檔案 | `avno`、`ac00`、`agfs`、`a000`、tcvitals 都是 200（11/12 00Z）|
| NOAA NOMADS **目錄清單** | `ens_tracker/prod/` 與 `gfs…/tctrack/` 兩個目錄頁都失敗，curl 結束碼 16（HTTP/2 層錯誤），沒有取得 HTTP 狀態碼 |
| ECMWF | 四個 tf 產品都是 200（11/12 00Z）|
| UCAR | `bdecks_open/` 目錄 200 |

- **結論**：五個來源的資料檔從 GitHub Actions 都連得上。**S1 的 JTWC 降級方案目前不需要啟用**，但設計上仍應允許 JTWC 缺席（單次測試不保證長期）。
- **NOMADS 目錄清單不可依賴**：同一次執行中檔案請求全部成功，只有目錄頁失敗。原因未查明；改用 HTTP/1.1（例如 Python requests）是否成功 **[待驗證]**。正式程式應**直接以已知檔名請求檔案**，不要先列目錄。GEFS 與 AIGEFS 的成員檔名是固定的，可以這樣做。
- JTWC 的個別系統產品（`.tcw` 等）這次沒有測，因為需要先解析 RSS 取得當前系統；只測了 RSS 與展望產品。

### BUFR 套件 [實測，Actions]

| 項目 | 現有 `fetchers/requirements.txt`（基準）| `pybufrkit`＋`bitstring<4` | `eccodes` |
|---|---|---|---|
| 安裝時間（`--no-cache-dir`）| 1.1 秒 | 4.0 秒 | 4.6 秒 |
| venv 大小 | 未量 | 30 MB | 391 MB |
| 安裝的套件 | — | pybufrkit 0.2.25、bitstring 3.1.9、six | eccodes 2.50.1、eccodeslib、**eckitlib**、numpy、cffi、attrs、findlibs、pycparser |
| 解碼 IFS 確定性檔（17.7 KB，8 個 message）| — | 成功，0.16 秒 | 成功，0.36 秒（含載入函式庫）|

- 兩者在 Linux 上都能用 pip 直接安裝，不需要 apt。安裝時間都只有幾秒，**不會拖慢排程**。
- 兩者解出的 8 個識別碼完全相同。
- `eccodes` 在 Linux 佔 391 MB（多了 `eckitlib`，第 8 節未列出），`pybufrkit` 只有 30 MB。
- **建議維持第 8 節的結論**：優先用 `pybufrkit`＋`bitstring<4`。Ensemble 檔的解碼時間這次沒有在 Actions 上量（本機約 7 秒）。

### 新發現：ECMWF 的識別碼會跨 cycle 改變 [實測]

Actions 解出的識別碼是 `31W`，不是先前的 `38W`。主代理於 11/12 補抓 IFS 確定性檔核對：

| cycle | CEMPAKA 的 `stormIdentifier` | 分析位置 |
|---|---|---|
| 11/10 12Z – 11/11 06Z | `38W` | — |
| 11/11 12Z | `31W` | 30.2N 154.1E |
| 11/11 18Z | `31W` | 30.9N 156.0E |
| 11/12 00Z | `31W` | 30.9N 156.0E（與 18Z 相同，沒有預報步）|

- **同一個系統的 ECMWF 編號不穩定**：名稱（`CEMPAKA`）沒變，編號從 `38W` 變成與 JTWC 相同的 `31W`。配對不能用 ECMWF 編號當鍵，也不能假設它等於或不等於 JTWC 編號。已命名系統用名稱加年份；命名前用位置。
- 11/12 00Z 的分析位置與前一個 cycle 完全相同且沒有預報步，看起來是系統消散後殘留的舊分析 **[推測，待驗證]**。程式要檢查分析時間與預報步數，不能只看系統是否出現在檔案裡。
- PENA 在 11/11 06Z 與 18Z 的檔案中都有出現，所以先前「11/10 18Z 缺席」不是 06／18Z 的固定規律，原因仍不明。

### S2 驗證分工

- **主代理**（11/11 約 11:23–11:50Z）：第 5–9 節所有 [實測] 項目，除另外註明「審查代理」者。
- **獨立 Sub-Agent**（11/11 約 17:59–18:02Z 發出請求，共 61 次；腳本與下載檔在 `s2/audit/`）
  - **獨立重抓並確認**：ATCF 目錄與檔名規則、四個系統的代碼與成員數（7 個 cycle）、延遲、`WP31` 對 JTWC 31W（約 51 km）、403／404 行為、tcvitals 內容、UCAR a-deck 沒有 JTWC 官方預報。
  - **獨立重算並確認**：用自己寫的 ATCF 解析與 pybufrkit 逐描述符走訪，重算 ATCF 全部 5 組樣本與 11/10 12Z 的 4 個 BUFR 檔，位元組數與主代理完全相同；估計上限的乘法與合計也相同。BUFR 重算用的是主代理下載的檔案。
  - **部分抽查**：ECMWF 的 `38W`、成員編號與類型（用主代理下載的 11/10 12Z 四個檔）；06Z 檔名時效與 13 個 run（自己的 HEAD 請求）。
  - **提出**：2 項建議修正（保留期的可補抓時間、延遲範圍）與 10 項輕微問題，本文已全部納入。修正後已交回複查一次（只重讀文件，未再發請求），12 項均確認已處理。
  - **沒有驗證**：第 8 節套件評估全部；條款與授權敘述；NHC、NRL、`ssd.noaa.gov`、UCAR b-deck 的重新請求；11/10 18Z 與 11/11 00Z 的 BUFR 大小列；「PENA 在 18Z 缺席」；ECMWF 00Z 的分析位置。這些只有主代理的結果。另有三項只看了主代理的檔案、沒有獨立重抓：PENA 越過換日線後仍是 `CP`、GEFS 00Z 的 `WP31` 位置、UCAR b-deck 最後一筆。

## 11. 向 Pillar 借用的概念（只讀，未複製程式碼、未執行）

- `noaa_atcf.py`：`_dir_url`、`_file_name`（目錄與檔名規則的線索）、`parse_atcf`（a-deck 欄位位置與「同一時效多行」的處理）、`latest_cycle`（未發布目錄回 403 的提示）。
- `ecmwf_bufr.py`：`_url`、`forecast_range_hours`（檔名與 IFS／AIFS 時效差異的線索）、`_decode`（compressed 模板的讀法提示）、`_match_track_ids`（ECMWF 編號不可信、改用位置配對的想法）。
- 以上都只當作待查線索，本文件的結論全部來自自行實測或官方文件。
