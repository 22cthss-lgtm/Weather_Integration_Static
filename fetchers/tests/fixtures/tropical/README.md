# 熱帶系統測試樣本

真實回應，取自 `.runtime/tc-source-verification/`（S1、S3 的本機實測，2026-11-11 至 11-12）。實測時的系統是 CEMPAKA（JTWC 31W／JMA TC2638／CWA 第 31 號）與中太平洋的 PENA（04C）。

放入前逐檔檢查：不含 CWA 金鑰、不含請求網址、不含請求端 IP（2026-11-16 以搜尋確認）。NOMADS 的 403 回應本體含請求端 IP，**不得放入本目錄**。

| 檔案 | 來源網址 | 取得時間（UTC）| 是否裁剪 |
|---|---|---|---|
| `cwa_datastore_cempaka.json` | `https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005`（金鑰以參數傳入，未保存）| 2026-11-11 10:50 | 否 |
| `jma_extra_feed_cropped.xml` | `https://www.data.jma.go.jp/developer/xml/feed/extra.xml` | 2026-11-11 10:48 | **是**：148 筆條目只保留 6 筆（4 筆 VPTW60、前後各 1 筆其他電文），feed 標頭原樣 |
| `jma_vptw60_tc2638_serial52.xml` | `https://www.data.jma.go.jp/developer/xml/data/20261111094118_0_VPTW60_010000.xml` | 2026-11-11 約 11:00（獨立審查代理取得）| 否 |
| `jma_vptw60_tc2638_final.xml` | `https://www.data.jma.go.jp/developer/xml/data/20261111124152_0_VPTW60_010000.xml` | 2026-11-12 約 11:00 | 否 |
| `jma_targetTc_active.json` | `https://www.jma.go.jp/bosai/typhoon/data/targetTc.json` | 2026-11-11 10:48 | 否 |
| `jma_targetTc_low.json` | 同上 | 2026-11-12 10:54 | 否 |
| `jtwc_rss_active.xml` | `https://www.metoc.navy.mil/jtwc/rss/jtwc.rss` | 2026-11-11 約 11:00（獨立審查代理取得）| 否 |
| `jtwc_rss_final.xml` | 同上 | 2026-11-12 10:54 | 否 |
| `jtwc_wp3126_warning21.tcw` | `https://www.metoc.navy.mil/jtwc/products/wp3126.tcw` | 2026-11-11 約 11:00 | 否 |
| `jtwc_wp3126_final.tcw` | 同上（警報 #22，最終報）| 2026-11-12 約 11:05 | 否 |
| `jtwc_cp0426_warning23.tcw` | `https://www.metoc.navy.mil/jtwc/products/cp0426.tcw` | 2026-11-12 約 11:05 | 否 |
| `jtwc_rss_no_wp_systems_20261115.xml` | `https://www.metoc.navy.mil/jtwc/rss/jtwc.rss` | 2026-11-15 17:43（S4 真來源測試）| 否。西北太平洋與中／東太平洋項目都寫 `No Current Tropical Cyclone Warnings.`；南半球項目列有 04P |
| `jma_targetTc_empty_20261115.json` | `https://www.jma.go.jp/bosai/typhoon/data/targetTc.json` | 2026-11-15 17:43 | 否（內容為 `[]`）|
| `jma_extra_feed_no_vptw_cropped_20261115.xml` | `https://www.data.jma.go.jp/developer/xml/feed/extra.xml` | 2026-11-15 17:43 | **是**：241 筆條目只保留前 2 筆與最後 1 筆；原檔沒有任何 VPTW60 |

CWA 在 2026-11-15 17:43 的無系統回應與 `cwa_datastore_cempaka.json` **逐位元相同**（CEMPAKA 消散四天後仍原樣提供），所以沒有另存一份。

## 人工構造的資料

以下情境在撰寫測試時**沒有真實回應**，測試用的本體是依真實格式手寫的，放在 `fetchers/tests/tropical_testing.py`（名稱以 `SYNTHETIC_` 或 `synthetic_` 開頭）與 `test_tropical_sources.py` 的 `feed()`、`bulletin()`：

- 名稱含 `synthetic` 的「沒有任何系統」回應（CWA **空陣列**、JMA 沒有 VPTW60 的 feed 與空的 `targetTc.json`、JTWC 的無警報句子）。2026-11-15 之後 JMA 與 JTWC 已有真實樣本（上表），兩者與人工構造的長相一致；**CWA 空陣列的回應從未實際觀察到**，實測到的是保留舊系統的回應。
- 未命名的熱帶低氣壓、兩個同時存在的系統、越過 180° 的中太平洋系統、北印度洋系統、訓練與取消電文。
- 測試中把 `20261111064050` 那則 JMA 電文也對應到 `jma_vptw60_tc2638_serial52.xml` 的內容（實際是第 51 報，沒有保存）。

## 署名

- **CWA**：提供機關／交通部中央氣象署，資料名稱「熱帶氣旋路徑」（W-C0034-005），依政府資料開放授權條款第 1 版。
- **JMA**：出典：気象庁ホームページ（<https://www.jma.go.jp/>）。防災情報 XML 電文與 bosai JSON，依公共データ利用規約（第 1.0 版）。裁剪過的檔案為「気象庁の資料を加工して作成」。
- **JTWC**：含美國海軍 Joint Typhoon Warning Center 的資料；依 17 U.S.C. §403 屬公有領域，不受著作權保護。RSS 內含官方公開的聯絡信箱，原樣保留。
