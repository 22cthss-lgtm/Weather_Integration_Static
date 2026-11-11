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

- 三個來源從 **GitHub Actions** 的可達性。需推送臨時 workflow，尚未取得同意，也沒有執行。
- JMA 與 CWA 在**無活躍系統時**的實際回應。目前有活躍系統，無法觀察。
- JMA 接近日本時的加密發布頻率；JTWC 的 TCFA（WTPN21-26）實際檔名。
- CWA 官網路徑圖檔名的完整規則；CWA 官網圖片的使用條款。
- 長時間穩定性（只做了單一時點的實測，未持續觀察）。
