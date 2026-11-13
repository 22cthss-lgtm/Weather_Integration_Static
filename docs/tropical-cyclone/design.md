# Tropical Cyclone Center — 資料契約與設計決策（S3）

> 狀態：**已確認**。使用者於 2026-11-13 確認整份設計，並確認第 13 節 A–K 全部採用建議方案。S3 完成；後續階段以本文件為準，要更動契約須先修改本文件並取得使用者同意。
> 撰寫日期：2026-11-12｜分支 `feature/tropical-cyclone`（基準 `444fdf3`）
> 依據：`plan.md`（v2）、`source-matrix.md`（S1／S2／10a）、2026-11-12 唯讀檢視的現有程式、以及 S3 補測（見第 0.3 節）。
> 本文件不含任何實作程式。文中出現的「S4 要改」是給後續階段的指示，S3 沒有改動 `fetchers/`、`frontend/`、`.github/`。

## 0. 閱讀指引

### 0.1 標記

- **[實測]**、**[官方文件]**、**[待驗證]**：沿用 `source-matrix.md`。
- **[實測 S3]**：本階段補測取得，原始回應在 `.runtime/tc-source-verification/s3/raw/`。
- **[已決定]**：使用者於 2026-11-12 確認。
- **[建議]**：本文件的建議，尚待使用者確認（集中於第 13 節）。
- **[假設]**：設計依賴、但尚未驗證的前提。每一項在第 12 節都有「不成立時的退路」。
- **[初值]**：需要在實作階段用測試資料校正的數值。

### 0.2 使用者已確認的十項（2026-11-12）

| # | 決定 |
|---|---|
| 1 | Ensemble 進快照，只存路徑（位置、氣壓、風速），不存風圈 |
| 2 | 確定性模式保留 4 個 cycle（24 小時），Ensemble 保留 2 個 |
| 3 | 模式不存風圈；官方風圈照存 |
| 4 | 判定「無颱風」的必要來源是 CWA 與 JMA；JTWC 不列必要 |
| 5 | 中太平洋越線系統：以分析位置是否落在西北太平洋範圍為準，不看編號前綴 |
| 6 | 命名前系統配對不上時，各機構分開列，不合併 |
| 7 | 路由 `/tropical?storm=…&tab=…` |
| 8 | 地圖用 Leaflet 加隨站打包的 Natural Earth 海岸線，不用外部圖磚 |
| 9 | 允許 S8／S9 在 `http_client` 為 NOAA、ECMWF 新增專屬請求上限，不動現有來源的數值 |
| 10 | 允許 S3 對 JTWC、JMA 補測系統消散後的回應 |

### 0.3 S3 補測結果（2026-11-12 10:54–11:10Z，本機，共 14 次請求）

CEMPAKA 已於 11/11 消散，PENA 仍在換日線以東。固定 UA、間隔 1.2 秒、不重試、不跟隨轉址。**只有主代理執行，沒有獨立複核。**

| 觀察 | 結果 |
|---|---|
| JTWC RSS，最終報之後約 20 小時 | 西北太平洋項目**仍列出** `Typhoon 31W (Cempaka) Warning #22 Final Warning`，產品連結仍在 [實測 S3]。有無系統不能只看 RSS 是否列出，要看是否標示 Final Warning |
| JTWC RSS，中太平洋項目 | `Tropical Depression 04C (Pena) Warning #23`，產品檔名 `cp0426…`，與西北太平洋相同格式 [實測 S3] |
| JTWC `.tcw` 最終報 | 標頭行 `2026111112 31W CEMPAKA 022 …`；`AMP` 區塊寫 `DISSIPATING AS A SIGNIFICANT TROPICAL CYCLONE`；預報點仍有 T012、T024 [實測 S3] |
| JTWC `cp0426.tcw` | 預報點 `T036 102N 1800E`，預報越過 180° [實測 S3] |
| JTWC ABPW10（12/0600Z） | 西北太平洋仍寫已發最終報的 31W，再寫 `NO OTHER TROPICAL CYCLONES`；南太平洋分區寫 `TROPICAL CYCLONE SUMMARY: NONE.` [實測 S3]。整個西北太平洋都沒有系統時的寫法仍是 **[待驗證]** |
| JMA `targetTc.json`，消散後約 22 小時 | **不是空陣列**：`[{"tropicalCyclone":"TC2638","typhoonNumber":"2632","category":"LOW","issue":"2026-11-11T21:45:00+09:00"}]` [實測 S3]。完全沒有系統時是否為空陣列仍是 **[待驗證]** |
| JMA 最後一則 VPTW60（11/11 12:41Z） | `Remark` 為 `台風消滅（温帯低気圧化）`，`TyphoonClass` 為 `温帯低気圧(LOW)`，沒有預報區段 [實測 S3] |
| JMA `extra.xml` | 125 筆，涵蓋約 10 小時，其中 VPTW60 為 0 筆（最後一則之後沒有再發）[實測 S3] |
| JMA 長期 feed `extra_l.xml` | 網址存在，200，**2.73 MB**，4717 筆，涵蓋約 7 天；含 VPTW60 與 VPTW61 兩種 [實測 S3]。VPTW61 的內容 **[待驗證]** |
| NOAA tcvitals | 11/11 18Z 檔仍有 CEMPAKA，但該行時間是 12Z（比檔案 cycle 舊）；11/12 00Z 檔只剩 PENA [實測 S3] |
| NOAA `avno` | 11/11 18Z 有 `WP31` 與 `CP04`；11/12 00Z 只剩 `CP04` [實測 S3] |
| 轉址 | JTWC、JMA、NOMADS 的檔案在不跟隨轉址下都直接回 200；ECMWF 確定性檔的 HEAD 也直接回 200，沒有 `Location` [實測 S3] |

---

## 1. 檔案路徑與 JSON 結構

### 1.1 總覽

所有路徑相對於公開資料根目錄（`frontend/public/data/`，網站上為 `{base}data/`）。

| 路徑 | 寫入任務 | 內容 | 何時存在 |
|---|---|---|---|
| `tropical/official/index.json` | `tropical_official` | 索引：整體狀態、來源狀態、系統清單 | 任務第一次成功後永遠存在，沒有颱風也存在 |
| `tropical/official/storms/{cyclone_id}/analysis.json` | 同上 | 各機構的最新分析與過去路徑 | 系統在索引中時 |
| `tropical/official/storms/{cyclone_id}/forecast.json` | 同上 | 各機構的最新官方預報路徑 | 同上 |
| `tropical/models/index.json` | `tropical_models` | 每個系統有哪些 cycle、每個 cycle 有哪些確定性模式 | 任務第一次成功後永遠存在 |
| `tropical/models/storms/{cyclone_id}/{cycle}.json` | 同上 | 該 cycle 的所有確定性模式路徑（GFS、AIGFS、IFS、AIFS 同一檔） | 有資料時 |
| `tropical/ensemble/index.json` | `tropical_ensemble` | 每個系統有哪些 cycle、每個 cycle 有哪些 Ensemble | 任務第一次成功後永遠存在 |
| `tropical/ensemble/storms/{cyclone_id}/{cycle}/{model}.json` | 同上 | 單一 Ensemble 的所有成員路徑 | 有資料時 |

- `{cyclone_id}`：見第 2 節，格式 `[0-9]{4}-(jma|jtwc|cwa)-[a-z0-9]{1,8}`。
- `{cycle}`：模式起報時間，`YYYYMMDDHH`（UTC），`HH` 只能是 `00`、`06`、`12`、`18`。
- `{model}`（Ensemble）：`gefs`、`aigefs`、`ifs-ens`、`aifs-ens`。

**為什麼分成三個目錄（選項與取捨）**

| 選項 | 說明 | 取捨 |
|---|---|---|
| A（建議）三個任務、三個互不重疊的前綴 | `tropical/official/`、`tropical/models/`、`tropical/ensemble/` | 現有 `due_refresh` 以「任務＝一個路徑前綴＋一個必存檔」運作（失敗時整個前綴回復舊檔）。三個前綴可以直接沿用：NOAA 失敗只回復模式檔，不會回復官方資料。各任務有自己的間隔與重試 |
| B 單一任務、單一前綴 `tropical/` | 任務內部自己決定要抓什麼 | 少改排程，但任一來源的例外都會回復整個前綴；間隔只能取最短的；失敗隔離要全部自己實作 |
| C 以系統為第一層（`tropical/storms/{id}/official…`） | 檔案結構較直覺 | 三個任務會共用同一前綴，`belongs` 無法用前綴判斷歸屬，回復範圍會互相覆蓋 |

每個任務的 `index.json` 就是 `due_refresh.checked_update` 所需的「必存檔」（相當於現有的 `latest.json`）。

### 1.2 共通規則

**時間**
- 一律 UTC，格式固定為 `YYYY-MM-DDTHH:MM:SSZ`（秒精度、結尾 `Z`）。驗證器以正規表示式加 `datetime.fromisoformat` 檢查，拒絕其他寫法。
- 來源的 JST（JMA）、+08:00（CWA）、Z（JTWC、NOAA、ECMWF）在解析時轉成 UTC，不保存原始時區字串。
- 抓取時間的欄位名**只能是 `fetched_at`**。`content_versions.EXECUTION_FIELDS` 會把 `fetched_at`、`updated_at`、`checked_at`、`attempted_at` 排除在內容識別之外；用其他名稱會讓每次檢查都被當成內容變更。
- 氣象時間一律是語意欄位：`analysis_time`（分析時刻）、`issued_at`（機構發布時刻）、`init_time`（預報起報時刻）、`valid_time`（節點有效時刻）、`last_ok_at`（見 1.3）。

**座標**
- `lat`：北緯為正，-90 至 90。`lon`：東經為正，**-180（含）至 180（不含）**，西經為負。小數 1 位（來源精度都是 0.1°；JMA 度分另轉成十進位後四捨五入到 0.1）。
- **剛好 180° 的點一律寫成 `-180.0`**，不論來源寫 `1800E` 或 `1800W`。真實樣本 `cp0426.tcw` 就有 `T036 102N 1800E` [實測 S3]；解析時不做這個轉換，整個檔會被驗證器拒絕。
- 跨 180° 的展開只在前端繪圖時做（第 7.3 節），資料檔不存 0–360。

**數值與缺值**
- 缺值一律 `null`，不用 `0`、`-999` 或空字串。ATCF 以 `0` 表示沒有該風速門檻的半徑、tcvitals 以 `-999` 表示缺值，解析時轉成 `null`。
- 數值必須是有限的 `int` 或 `float`（`allow_nan=False`）。

**風速（強度不可直接比較）**
- 官方資料的風速物件：`{"kt": 數值或 null, "ms": 數值或 null, "averaging_min": 1 或 10}`。
  - 只填機構**實際提供**的單位：JTWC 只有 `kt`、`averaging_min: 1`；CWA 只有 `ms`、`averaging_min: 10`；JMA 兩者都有、`averaging_min: 10`。
  - 後端**不做**單位換算，也不做 1 分鐘／10 分鐘的換算。前端若顯示換算單位（kt↔m/s 是純單位換算），必須標示「換算」；不得把不同 `averaging_min` 的值排序、平均或標成同一欄。
  - CWA 的平均期間是「依慣例 10 分鐘」**[待驗證]**（`source-matrix.md` 第 3 節）；`averaging_min` 仍填 10，並在署名區註明依據。
- 模式資料的風速是模式輸出的 10 m 最大風，沒有平均期間的概念：以檔案層級的 `wind_unit`（`"kt"` 或 `"m/s"`）標示，不寫 `averaging_min`。
- 氣壓一律 `hPa`（ECMWF 的 Pa 除以 100，屬單位換算）。

**保留欄位名（不得使用）**
- `image_url`：`content_versions.images_in` 會把任何含這個鍵的物件當成圖片；沒有 `image_time` 時會去下載圖檔計算雜湊。
- `source_url`：`content_versions._semantic` 會對這個鍵的值做網址正規化；值若是 `null`，正規化會產生 bytes，之後計算內容識別的 `json.dumps` 會失敗 [審查代理以 Python 3.13 重現]。
- 颱風檔案的連結一律用 `product_url`（機構產品檔）與 `graphic_url`（外連圖檔）。

**網址欄位**
- 只允許 `https`，主機必須在固定清單內：`www.metoc.navy.mil`、`www.data.jma.go.jp`、`www.jma.go.jp`、`opendata.cwa.gov.tw`、`www.cwa.gov.tw`、`nomads.ncep.noaa.gov`、`data.ecmwf.int`。
- 不得含帳號密碼，查詢參數不得含 `authorization`、`api_key`、`key`、`token`（沿用 `snapshots.image` 的檢查）。
- CWA 只保存資料集頁面 `https://opendata.cwa.gov.tw/dataset/warning/W-C0034-005`，**絕不保存實際請求網址**。

**格式**
- 三個 `index.json`、`analysis.json`、`forecast.json`：沿用 `atomic_write_json`（縮排 2）。
- `tropical/models/storms/**`、`tropical/ensemble/storms/**`：**必須精簡輸出**（`separators=(',', ':')`，無縮排）。`atomic_write_json` 固定縮排 2，五個數值的節點會各佔一行，大小約為精簡格式的 3 倍以上；第 6 節的大小估算以精簡格式為前提。S8 需新增精簡寫入函式（或為 `atomic_write_json` 加參數，預設行為不變）。
- 每個檔案最上層都有 `schema_version`（整數，目前為 `1`）。驗證器只接受已知版本與精確的欄位集合（沿用 `snapshots.exact`）。

### 1.3 `tropical/official/index.json`

```json
{
  "schema_version": 1,
  "basin": "WP",
  "status": "PARTIAL",
  "fetched_at": "2026-11-11T10:33:07Z",
  "sources": {
    "cwa":  {"required": true,  "state": "ok",     "error_code": null,         "last_ok_at": "2026-11-11T10:33:00Z", "active_count": 1},
    "jma":  {"required": true,  "state": "ok",     "error_code": null,         "last_ok_at": "2026-11-11T10:33:00Z", "active_count": 1},
    "jtwc": {"required": false, "state": "failed", "error_code": "http_error", "last_ok_at": "2026-11-11T09:03:00Z", "active_count": null}
  },
  "storms": [
    {
      "cyclone_id": "2026-jma-tc2638",
      "status": "active",
      "season": 2026,
      "name": "CEMPAKA",
      "name_zh": "查帕卡",
      "origin_basin": "WP",
      "ids": {"jtwc": "31W", "jma_tc": "TC2638", "jma_number": "2632", "cwa_ty": "31", "cwa_td": "35"},
      "match": {"jtwc": "name", "jma": "origin", "cwa": "name"},
      "last_fix_time": "2026-11-11T09:00:00Z",
      "ended_at": null,
      "summary": {
        "jtwc": {"analysis_time": "2026-11-11T06:00:00Z", "active": true, "lat": 29.1, "lon": 150.2, "category": "TYPHOON",
                 "max_wind": {"kt": 65, "ms": null, "averaging_min": 1}, "pressure_hpa": 983},
        "jma":  {"analysis_time": "2026-11-11T09:00:00Z", "active": true, "lat": 29.6, "lon": 151.9, "category": "STS",
                 "max_wind": {"kt": 60, "ms": 30, "averaging_min": 10}, "pressure_hpa": 985},
        "cwa":  {"analysis_time": "2026-11-11T06:00:00Z", "active": true, "lat": 29.0, "lon": 150.1, "category": "輕度颱風",
                 "max_wind": {"kt": null, "ms": 30, "averaging_min": 10}, "pressure_hpa": 975}
      }
    }
  ]
}
```

（範例的強度、氣壓取自 `source-matrix.md` 第 3 節；JMA、CWA 的位置數字是示意，不是實測值。）

| 欄位 | 型別與規則 |
|---|---|
| `basin` | 固定 `"WP"`。保留欄位，日後擴充其他洋區時新增檔案而不是改這個值 |
| `status` | `"OK_WITH_STORMS"`、`"OK_NO_STORMS"`、`"PARTIAL"` 三者之一。判定規則見第 3.3 節。**後端不寫 `UNAVAILABLE`、`STALE`**，這兩種由前端推導（第 3.4 節） |
| `sources.{cwa,jma,jtwc}` | 三個鍵都必須存在 |
| `sources.*.required` | 固定值：`cwa`、`jma` 為 `true`，`jtwc` 為 `false` |
| `sources.*.state` | `"ok"` 或 `"failed"`，表示**本次**檢查的結果 |
| `sources.*.error_code` | `state` 為 `ok` 時 `null`；否則是 `scheduling.SAFE_ERRORS` 內的固定代碼。不保存例外訊息或上游回應 |
| `sources.*.last_ok_at` | 該來源最後一次成功檢查的時刻，**取到分鐘**（秒固定 `00`）。從未成功為 `null`。這是**語意欄位**（見下方「心跳」） |
| `sources.*.active_count` | 該來源本次回報、落在範圍內且活躍的系統數；`state` 為 `failed` 時 `null` |
| `storms` | 陣列，最多 12 筆；依 `cyclone_id` 字典序排列（輸出順序固定，避免無意義的內容變更） |
| `storms[].status` | `"active"` 或 `"ended"`（第 3.5 節） |
| `storms[].season` | 四位數年份，取自機構編號所屬的季別，不取目前日期（跨年系統不會改變） |
| `storms[].name` | 國際名，大寫 ASCII；尚未命名為 `null` |
| `storms[].name_zh` | CWA 的中文名；沒有為 `null` |
| `storms[].origin_basin` | `"WP"`、`"CP"`、`"EP"`：系統編號所屬的洋區 |
| `storms[].ids` | 五個鍵都必須存在，未知為 `null`。`jtwc` 形如 `31W`、`04C`；`jma_tc` 形如 `TC2638`；`jma_number` 形如 `2632`；`cwa_ty`、`cwa_td` 為數字字串 |
| `storms[].match` | 各機構資料是如何歸到這個系統：`"origin"`（`cyclone_id` 就是由它產生）、`"id"`（沿用前一次索引中已綁定的機構編號）、`"name"`、`"position"`；該機構沒有資料為 `null` |
| `storms[].last_fix_time` | 各機構 `analysis_time` 的最大值 |
| `storms[].ended_at` | `status` 為 `ended` 時，第一次判定結束的時刻（取到分鐘）；否則 `null` |
| `storms[].summary.{jtwc,jma,cwa}` | 三個鍵都必須存在；沒有資料為 `null`。有資料時六個欄位都必須存在 |
| `summary.*.active` | 該機構目前是否仍視此系統為活躍（第 3.2 節）。該來源本次 `failed` 時沿用前一次的值（第 3.3 節） |
| `summary.*.category` | **機構原文的分類字串**，不做跨機構對照。JTWC 取 `.tcw` 的分類（如 `TYPHOON`）；JMA 取 `TyphoonClass` 括號內的代碼（如 `STS`、`LOW`）；CWA 取原文 |

**心跳（`last_ok_at`）[建議，見第 13 節 C]**

現有流程會丟棄「只有抓取時間改變」的重寫（`checked_update` 最後一段依內容識別還原舊檔）。若索引只有 `fetched_at`，淡季時「目前無活躍系統」的索引可能幾個月不變，前端無法分辨「十分鐘前剛確認過」與「抓取已經壞了三個月」。

- 做法：每個來源的 `last_ok_at` 是語意欄位，成功檢查就更新（取到分鐘）。
- 代價：`tropical_official` 每次成功（30 分鐘一次）都會讓內容識別改變並保存新版本。現有雷達與衛星每 10 分鐘就有內容變更，所以新增的版本數不多；但這偏離了現有「檢查時間不算內容」的原則，需要使用者確認。
- 替代：不設心跳，前端不顯示 STALE，只顯示各機構的 `analysis_time`。

### 1.4 `tropical/official/storms/{cyclone_id}/analysis.json`

```json
{
  "schema_version": 1,
  "cyclone_id": "2026-jma-tc2638",
  "fetched_at": "2026-11-11T10:33:07Z",
  "agencies": {
    "jtwc": {
      "product_url": "https://www.metoc.navy.mil/jtwc/products/wp3126.tcw",
      "graphic_url": "https://www.metoc.navy.mil/jtwc/products/wp3126.gif",
      "issued_at": "2026-11-11T09:00:00Z",
      "bulletin": "021",
      "final": false,
      "fix": {
        "analysis_time": "2026-11-11T06:00:00Z", "lat": 29.1, "lon": 150.2, "category": "TYPHOON",
        "max_wind": {"kt": 65, "ms": null, "averaging_min": 1},
        "gust": {"kt": 80, "ms": null},
        "pressure_hpa": 983,
        "movement": {"direction_deg": 70, "direction_text": null, "speed_kt": 36, "speed_kmh": null},
        "radii": [
          {"threshold": {"value": 34, "unit": "kt"}, "unit": "nm",
           "sectors": [{"dir": "NE", "radius": 130}, {"dir": "SE", "radius": 95}, {"dir": "SW", "radius": 160}, {"dir": "NW", "radius": 110}]}
        ]
      },
      "past_track_origin": "accumulated",
      "past_track": [
        {"analysis_time": "2026-11-11T00:00:00Z", "lat": 27.9, "lon": 147.0, "category": "TYPHOON",
         "max_wind": {"kt": 70, "ms": null, "averaging_min": 1}, "pressure_hpa": null}
      ]
    },
    "jma": null,
    "cwa": null
  }
}
```

| 欄位 | 規則 |
|---|---|
| `agencies` | `jtwc`、`jma`、`cwa` 三個鍵都必須存在；沒有資料為 `null` |
| `product_url` | 該筆資料的機構產品網址。JTWC 取 RSS 內的 `.tcw` 連結；JMA 取電文網址；CWA 固定為資料集頁面。必為字串 |
| `graphic_url` | 官方警報圖的外連網址（目前只有 JTWC 的 `.gif`，取自 RSS）；沒有為 `null`。CWA 路徑圖的檔名規則是 **[待驗證]**，S11 再決定是否填入 |
| `issued_at` | 機構發布時刻。JTWC 取 `.tcw` 第一行的日時組（如 `WTPN51 PGTW 111500` 的 `111500`），年月取自第二行的時間戳（樣本為 `261111141257`，即 2026-11-11）[實測 S3 的格式；推算規則是 **[假設]**]；JMA 取 `ReportDateTime`；CWA 若回應沒有發布時刻，取分析時刻 **[待驗證：CWA 回應是否有獨立的發布時間欄位]** |
| `bulletin` | 機構的報次字串，**原樣保存、不補零也不去零**（JTWC `.tcw` 標頭行的 `022`、JMA 的 `Serial` 如 `53`）；沒有為 `null` |
| `final` | 機構是否已宣告結束（第 3.2 節）。CWA 沒有已知的結束標記，固定 `false` |
| `fix` | 最新分析。`category`、`max_wind`、`gust`、`pressure_hpa`、`movement`、`radii` 都必須存在，沒有資料時為 `null`（`radii` 為空陣列） |
| `fix.pressure_hpa` | JTWC 的中心氣壓只出現在 REMARKS 文字中 [實測]；解析不到就填 `null`，不猜測 |
| `fix.movement` | 方向與速度各保留機構提供的形式：JTWC 為度數與 kt；JMA 為 16 方位文字（轉成英文縮寫如 `ENE`）與 kt／km/h；CWA 為 km/h。`direction_text` 只能是 16 方位縮寫、`"STNR"`（幾乎停滯）、`"VAR"`（方向不定）或 `null`；JMA 表示停滯與不定的原文用詞沒有樣本 **[待驗證]**，對不上已知用詞就填 `null` |
| `radii[].threshold` | 門檻風速與單位：JTWC `34／50／64 kt`；JMA 強風域 `30 kt`、暴風域 `50 kt`；CWA 七級風 `15 m/s`、十級風 `25 m/s`（JMA 與 CWA 的門檻數值依其官方定義，**S6 實作前需由官方文件再確認** **[待驗證]**） |
| `radii[].unit` | 半徑單位：JTWC `"nm"`；JMA `"nm"`（另有 km，取 nm）；CWA `"km"` |
| `radii[].sectors[].dir` | `NE`、`SE`、`SW`、`NW`、`N`、`E`、`S`、`W`、`ALL` 之一；`radius` 為非負數或 `null` |
| `past_track_origin` | `"source"`：機構自己提供完整過去路徑（CWA）。`"accumulated"`：本站把每次看到的 `fix` 累積起來（JTWC、JMA），**只從本站開始觀察的時點起算，不是完整生命史**，前端要標示 |
| `past_track` | 依 `analysis_time` 遞增、不重複，最多 160 點（6 小時一點可涵蓋 40 天；JMA 3 小時一點可涵蓋 20 天）。超過時捨棄最舊的點。不含目前的 `fix` |

**JMA 過去路徑的取捨**：bosai JSON 有完整過去路徑，但點上沒有時間戳、也沒有官方文件 [實測]。V1 採用累積法；不使用 bosai 的路徑陣列。見第 13 節 H。

### 1.5 `tropical/official/storms/{cyclone_id}/forecast.json`

```json
{
  "schema_version": 1,
  "cyclone_id": "2026-jma-tc2638",
  "fetched_at": "2026-11-11T10:33:07Z",
  "agencies": {
    "jma": {
      "product_url": "https://www.data.jma.go.jp/developer/xml/data/20261111094118_0_VPTW60_010000.xml",
      "issued_at": "2026-11-11T09:45:00Z",
      "bulletin": "52",
      "init_time": "2026-11-11T09:00:00Z",
      "points": [
        {"tau_h": 24, "valid_time": "2026-11-12T09:00:00Z", "lat": 34.5, "lon": 165.0, "category": "LOW",
         "max_wind": null, "gust": null, "pressure_hpa": 992,
         "probability_circle": {"radius": 110, "unit": "km", "probability_pct": 70},
         "radii": [], "note": null}
      ]
    },
    "jtwc": null,
    "cwa": null
  }
}
```

| 欄位 | 規則 |
|---|---|
| `init_time` | 預報所依據的分析時刻（各點 `tau_h` 的起算點）。**不是發布時刻** |
| `points` | 依 `tau_h` 遞增、不重複，最多 24 點；不含 `tau_h = 0`（那是 `analysis.json` 的 `fix`）。可以是空陣列（例如 JMA 最終報沒有預報區段 [實測 S3]） |
| `points[].valid_time` | 必須等於 `init_time + tau_h`；驗證器檢查。前端的時間軸只用 `valid_time` |
| `points[].probability_circle` | JMA 預報圓與 CWA 70% 機率半徑；JTWC 沒有，為 `null`。**這是機構的機率圓，不是暴風範圍**，前端圖例要分開 |
| `points[].note` | 機構對該時效的狀態註記，取固定詞彙：`"DISSIPATING"`、`"DISSIPATED"`、`"EXTRATROPICAL"`、`"POST_TROPICAL"`、`null`。對不上固定詞彙就填 `null`，不保存任意上游文字 |

- 每個機構只保留**最新一報**。官方預報的歷史版本不在 V1 範圍。
- 預報最長時效：JTWC 一般 120h、JMA 120h、CWA 依回應內容 [實測範圍見 `source-matrix.md`]；驗證器只限制 `tau_h` 為 1–240 的整數，不寫死各機構的時效。

### 1.6 `tropical/models/index.json`

```json
{
  "schema_version": 1,
  "fetched_at": "2026-11-11T11:05:12Z",
  "sources": {
    "noaa":  {"state": "ok", "error_code": null},
    "ecmwf": {"state": "failed", "error_code": "timeout"}
  },
  "match_basis": ["2026-jma-tc2638|31W|CEMPAKA"],
  "checked": {
    "2026111100": ["aifs", "aigfs", "gfs", "ifs"],
    "2026111106": ["aigfs", "gfs"]
  },
  "storms": {
    "2026-jma-tc2638": {
      "bridge": {"jtwc": null},
      "cycles": [
        {"cycle": "2026111100", "models": ["aifs", "aigfs", "gfs"]},
        {"cycle": "2026111106", "models": ["aigfs", "gfs"]}
      ]
    }
  }
}
```

| 欄位 | 規則 |
|---|---|
| `sources.*.state` | `"ok"`、`"failed"` 或 `"idle"`。`idle` 表示本次沒有對該來源發出請求（沒有活躍系統，或沒有待補的 cycle）；此時 `error_code` 為 `null` |
| `match_basis` | 本次用來配對的輸入：每個 `active` 系統一個字串 `cyclone_id|JTWC 編號或空|name 或空`，依字典序。JTWC 編號取官方索引的 `ids.jtwc`，沒有時取 `bridge.jtwc`。**清單中有新增的字串時（新系統、命名、取得編號），`checked` 視為全部清空**：先前「檔案裡沒有這個系統」的結論不再有效，要重新處理還在保留窗內的 cycle。**只有字串減少（系統結束）時不清空** |
| `checked` | 鍵為 cycle，值為**已成功下載並解析**的模式清單（依字母序），不論檔案裡有沒有對到任何系統。最多 8 個 cycle，超過時移除最舊的。**出現在這裡的組合不再請求** |
| `storms` | 鍵是 `cyclone_id`；只列官方索引中存在、且至少有一個 cycle 檔的系統。沒有任何資料時是空物件 `{}` |
| `storms.*.bridge.jtwc` | 由 tcvitals 橋接取得的 JTWC 編號（第 2.4 節），沒有為 `null`。官方索引的 `ids.jtwc` 已有值時這裡固定為 `null`。**橋接結果只存在這裡，模式任務不寫入官方索引** |
| `storms.*.cycles` | 依 `cycle` 遞增，最多 4 筆；`models` 依字母序，值為 `gfs`、`aigfs`、`ifs`、`aifs` 的子集，至少一個 |

- `checked` 有、但 `storms.*.cycles` 沒有的組合，表示「檔案處理過，裡面沒有這個系統」（範例的 `ifs` 00Z）。ECMWF 已實測會發生 [source-matrix 6.2 條件 4]。沒有這個紀錄的話，任務會每小時重抓同一個檔直到放棄時間。
- **索引是唯一的清單來源**：前端只讀 `storms` 列出的 cycle 檔；清除步驟也以它為準（第 3.6 節）。
- 這個檔案沒有心跳欄位。模式資料的新舊由 `cycle` 本身判斷：**有 `active` 系統、但它最新的 cycle 距今超過 18 小時 [初值] 時，前端標示「模式資料可能未更新」**。這也涵蓋兩個來源都失敗的情況：那時任務失敗、索引回復成舊檔，舊檔裡的 `state` 仍是先前的 `ok`，只能靠 cycle 的新舊看出異常。
- `state` 在 `ok` 與 `idle` 之間切換會算成內容變更（每天最多數次）。相對於雷達每 10 分鐘的變更可以忽略，不另外處理。

### 1.7 `tropical/models/storms/{cyclone_id}/{cycle}.json`（精簡格式）

```json
{"schema_version":1,"cyclone_id":"2026-jma-tc2638","cycle":"2026111106","init_time":"2026-11-11T06:00:00Z","fetched_at":"2026-11-11T11:05:12Z","models":{"gfs":{"provider":"NOAA","source_id":"WP31","match":"jtwc_id","wind_unit":"kt","track":[[0,28.8,149.8,985,62],[6,30.1,153.9,988,55]]},"aigfs":{"provider":"NOAA","source_id":"WP31","match":"jtwc_id","wind_unit":"kt","track":[[0,28.9,149.9,null,60]]}}}
```

| 欄位 | 規則 |
|---|---|
| `init_time` | 必須等於 `cycle` 對應的時刻 |
| `models` | 鍵為 `gfs`、`aigfs`、`ifs`、`aifs` 的子集，至少一個 |
| `provider` | `gfs`、`aigfs` 為 `"NOAA"`；`ifs`、`aifs` 為 `"ECMWF"` |
| `source_id` | 來源檔內的識別碼，原樣保存（ATCF 如 `WP31`、`CP04`；ECMWF 如 `38W`、`31W`）。**只供追查，不得當成配對鍵** |
| `match` | 這條路徑如何對到 `cyclone_id`：`"jtwc_id"`（用官方索引的 `ids.jtwc`）、`"tcvitals"`（用橋接取得的編號）、`"name"`、`"position"`（第 2.4 節） |
| `wind_unit` | NOAA 為 `"kt"`；ECMWF 為 `"m/s"` |
| `track` | 陣列的陣列，每點固定五個值：`[tau_h, lat, lon, pressure_hpa, wind]`。`tau_h` 為 0–480、6 的倍數、嚴格遞增；`lat`、`lon` 不得為 `null`（沒有中心位置的點不輸出）；`pressure_hpa`、`wind` 可為 `null`。最多 81 點 |

- 有效時間＝`init_time + tau_h`，由前端計算，檔案不重複保存。
- ATCF 同一時效有多行（每個風速門檻一行）[實測]：合併成一點，只取位置、氣壓、最大風，丟棄風圈。
- 追蹤器追丟就結束 [實測]：路徑長度不固定，不補點。

### 1.8 `tropical/ensemble/index.json`

```json
{
  "schema_version": 1,
  "fetched_at": "2026-11-11T11:40:30Z",
  "sources": {
    "noaa":  {"state": "ok", "error_code": null},
    "ecmwf": {"state": "ok", "error_code": null}
  },
  "match_basis": ["2026-jma-tc2638|31W|CEMPAKA"],
  "checked": {
    "2026111100": {
      "gefs":    {"complete": true,  "missing_files": []},
      "aigefs":  {"complete": false, "missing_files": ["a007", "a019"]},
      "ifs-ens": {"complete": true,  "missing_files": []}
    }
  },
  "storms": {
    "2026-jma-tc2638": {
      "cycles": [
        {"cycle": "2026111100", "models": {"gefs": {"members": 28, "members_expected": 31}, "ifs-ens": {"members": 51, "members_expected": 51}}}
      ]
    }
  }
}
```

| 欄位 | 規則 |
|---|---|
| `sources`、`match_basis` | 與 1.6 相同 |
| `checked` | 鍵為 cycle（最多 4 個），值的鍵為已開始處理的 Ensemble。`missing_files`：**下載失敗**的成員檔名代碼（只有 NOAA 會有；ECMWF 是單一檔，固定為空陣列）。`complete` 為 `true` 表示所有成員檔都已成功下載並解析，或已超過放棄時間；**`complete` 的組合不再請求，未 `complete` 的只補 `missing_files` 內的檔** |
| `storms.*.cycles` | 依 `cycle` 遞增，最多 2 筆。`models` 的鍵為 `gefs`、`aigefs`、`ifs-ens`、`aifs-ens` 的子集 |
| `members`、`members_expected` | `members` 是檔案內實際有這個系統路徑的成員數；`members_expected` 是該來源應有的成員檔數或 subset 數 |

- 「成員檔下載失敗」與「成員檔取得了、但追蹤器沒有追到這個系統」是兩回事：前者記在 `missing_files`、會重試；後者只反映在 `members` 小於 `members_expected`、**不重試**。範例的 GEFS 31 個檔都取得（`complete`），其中 28 個成員有這個系統。前端顯示「31 個成員中的 28 個」。
- Ensemble 任務不自己做 tcvitals 橋接，讀 `tropical/models/index.json` 的 `bridge`（第 2.4 節）。

### 1.9 `tropical/ensemble/storms/{cyclone_id}/{cycle}/{model}.json`（精簡格式）

```json
{"schema_version":1,"cyclone_id":"2026-jma-tc2638","model":"gefs","cycle":"2026111100","init_time":"2026-11-11T00:00:00Z","fetched_at":"2026-11-11T11:40:30Z","provider":"NOAA","source_id":"WP31","match":"jtwc_id","wind_unit":"kt","members_expected":31,"members":[{"m":"ac00","type":null,"track":[[0,27.7,146.8,984,60],[6,28.6,149.5,986,58]]},{"m":"ap01","type":null,"track":[[0,27.8,146.7,985,58]]}]}
```

| 欄位 | 規則 |
|---|---|
| `members` | 最多 60 筆，依 `m` 排序；只列至少有一點的成員 |
| `members[].m` | 來源的成員識別，原樣保存。NOAA 用檔名代碼（`ac00`、`ap01`…`ap30`、`a000`…`a030`）；ECMWF 用成員編號的字串（`"1"`…`"52"`） |
| `members[].type` | ECMWF 的 `ensembleForecastType` 原始整數（0、1、4）；NOAA 為 `null`。**不解讀成「控制成員」或「擾動成員」**：代碼的正式意義與 `ac00`／`a000` 的身分都是 [待驗證]，前端也不得標示「控制」 |
| `members[].track` | 與 1.7 相同的五值陣列；最多 81 點 |

- ECMWF 時效 0 的點取各成員自己的位置；若該 subset 沒有，取 significance=1 的共同分析位置（與 `source-matrix.md` 第 9 節的估算方式一致）。
- 不取用 NOAA 的平均檔（`aemn`、`aimn`）與 `p` 檔。`p` 檔第 5 欄代碼與主檔相同 [實測]，程式只請求主檔的固定檔名，不會混讀。

---

## 2. `cyclone_id` 與跨來源配對

### 2.1 S1／S2 發現與對策

| 發現 | 對策 |
|---|---|
| plan 寫「優先用編號」，但各來源的編號互不相通，ECMWF 的編號還會跨 cycle 改變（`38W`→`31W`）[實測] | **修正 plan 的規則**：機構之間不用編號互相配對。編號只用於「同一機構、跨次執行」的延續（上次看到的 `TC2638` 這次還是同一個系統）。跨機構用名稱加年份，命名前用位置加時間。ECMWF 的 `stormIdentifier` 完全不當配對鍵 |
| ATCF 用 JTWC 編號但沒有名稱；JMA、CWA 只有名稱與各自的編號 | ATCF 以 `ids.jtwc` 配對。`ids.jtwc` 的來源依序是：JTWC 自己的 RSS／`.tcw`；JTWC 缺席時用 NOAA tcvitals 橋接（同一行有編號、名稱、位置）[實測] |
| 命名前的系統沒有共通鍵 | 位置加時間配對（2.3 規則 3）；不夠確定就不合併，各自成為一筆系統 [已決定] |
| 中太平洋系統越線後仍是 `CP` 編號 | 以位置判斷是否納入，不看前綴（第 3.1 節）[已決定]；`origin_basin` 保留原洋區 |

### 2.2 `cyclone_id` 的格式與產生

**格式**：`{season}-{agency}-{code}`，全部小寫，例如 `2026-jma-tc2638`、`2026-jtwc-31w`、`2026-cwa-td35`。

**產生規則（鑄造一次，之後不變）**
1. 一個新系統第一次出現時，依優先序 **JMA → JTWC → CWA** 取當時有資料的第一個機構，用它的編號鑄造：
   - JMA：`EventID`（`TC2638` → `tc2638`）。
   - JTWC：編號（`31W` → `31w`；中太平洋 `04C` → `04c`）。
   - CWA：有 `CwaTdNo` 用 `td{n}`，否則用 `ty{n}`。
2. 之後每次執行，先讀前一次的索引（在候選目錄內，由種子快照帶入）。機構資料的編號若已綁定在某個既有系統的 `ids` 上，就沿用該系統的 `cyclone_id`。**ID 不會因為命名、其他機構加入或編號以外的變化而改變**。
   - **只有活躍的機構資料才能鑄造新系統**（活躍的定義見第 3.2 節）。不活躍、又對不上任何既有系統的資料直接忽略。理由：來源會殘留已結束系統的資料（JTWC RSS 在最終報後 20 小時仍列出 [實測 S3]；CWA 可能保留舊內容 [官方文件]）。沒有這條規則的話，系統過了保留期從索引移除後，殘留資料會把它重新鑄造成一筆「一出生就結束」的新系統，如此循環；第一次上線時也會立刻發生。
3. 前一次索引不存在或無法通過驗證時，視為沒有既有系統，依規則 1 重新鑄造。此時 ID 可能與先前不同（例如先前由 JTWC 鑄造，重建時 JMA 也有資料）。前端遇到不存在的 `storm` 參數時回到總覽並顯示提示（第 7.1 節）。

**選項與取捨**

| 選項 | 取捨 |
|---|---|
| A（建議）以機構編號鑄造、由前一次索引延續 | ID 穩定；命名前後不變；不需要額外的狀態檔（索引本身就是狀態）。缺點：網址不含颱風名，可讀性較差；索引遺失時可能重新鑄造出不同的 ID |
| B 以名稱為 ID（`2026-cempaka`） | 可讀。缺點：命名前沒有名稱，命名當下 ID 必須改變，檔案要搬移、舊連結失效 |
| C 自訂流水號加獨立狀態檔 | 最穩定。缺點：要多一個必須進快照的狀態檔，遺失時無法重建 |

### 2.3 官方機構之間的配對規則

每次執行，把三個機構本次取得的每一筆系統資料，依序套用以下規則歸到系統：

1. **延續（`match: "id"`）**：該機構的編號已出現在前一次索引某個系統的 `ids` 中，且季別相同 → 歸到該系統。
2. **名稱（`match: "name"`）**：資料有國際名，且某個系統的 `name` 與它相同（比較前轉大寫、只保留 A–Z）、`season` 相同 → 歸到該系統。附加檢查：兩者最近的分析位置相距不得超過 1500 km [初值]；超過就不合併並記錄。
3. **位置（`match: "position"`）**：其餘情況（至少一方尚未命名）。
   - 取該筆資料的分析時刻與位置，對每個候選系統找出時間最接近的已知位置（各機構的 `fix` 與 `past_track`），時間差不得超過 6 小時。
   - 容許距離 `D = 150 km + 60 km/h × 時間差（小時）` [初值]。CEMPAKA 實測移速 36 kt（約 67 km/h），所以時間差的補償不能省。
   - **只有在容許距離內恰好有一個候選，而且 2 × D 內沒有第二個候選時才合併**。其餘情況一律不合併。
4. **新系統（`match: "origin"`）**：以上都不成立，**而且這筆資料是活躍的** → 依 2.2 鑄造新的 `cyclone_id`。不活躍的資料到這一步就丟棄。

補充規則：
- 規則 1 優先於規則 2、3。既有綁定不會被名稱或位置推翻。
- 同一機構的兩筆資料不得歸到同一個系統；發生時保留規則順位較高的那筆，另一筆成為新系統。
- **兩個系統一旦各自成立，V1 不自動合併**（例如命名前 JMA 與 JTWC 各成一筆，命名後名稱相同）。處理方式：命名後機構資料依規則 1 仍留在各自的系統；兩筆系統會同名並列。這是保守的做法，避免自動合併出錯；合併功能列為 V1 之後。前端對同名的系統顯示「可能為同一系統」的提示。見第 13 節 I。
- 位置配對的門檻是初值。S6 必須用真實樣本（CEMPAKA、PENA）與人工構造的鄰近雙颱案例測試，並在 HANDOFF 記錄調整。

### 2.4 模式路徑的配對規則

模式路徑只會歸到**已存在於官方索引、且 `status` 為 `active`** 的系統；對不上的路徑一律丟棄（V1 不顯示 Invest 與模式自行生成的系統）。

**NOAA ATCF（GFS、AIGFS、GEFS、AIGEFS）**
1. 把檔內的洋區與序號轉成 JTWC 樣式（`WP, 31` → `31W`；`CP, 04` → `04C`；`EP` → `E`）。
2. `match: "jtwc_id"`：與某個系統的 `ids.jtwc` 相同 → 歸到該系統。
3. `match: "tcvitals"`（橋接）：若某個**已命名**系統的 `ids.jtwc` 是 `null`（JTWC 缺席或尚未發報），`tropical_models` 讀同一個 cycle 的 tcvitals，找出名稱相同的行取得編號，再以該編號比對。
   - tcvitals 的行可能比檔案 cycle 舊（18Z 檔內有 12Z 的行 [實測 S3]），只採用時刻與 cycle 相差不超過 6 小時的行。
   - 橋接結果存在 `tropical/models/index.json` 的 `storms.*.bridge.jtwc`（1.6），**不寫回官方索引**（各任務只寫自己的前綴）。`tropical_ensemble` 讀這個欄位，不自己請求 tcvitals。
   - 未命名的系統不做橋接：tcvitals 與 JTWC 對未命名系統的名稱欄寫法沒有樣本 **[待驗證]**，直接進步驟 4。
4. `match: "position"`：仍對不上時，用路徑的 `tau_h = 0` 位置與官方分析位置比對，規則同 2.3 的第 3 點。
5. 其他洋區（`SI`、`SP`、`IO`、`AL` 等）直接略過，不進入步驟 4。

**ECMWF BUFR（IFS、AIFS、IFS-ENS、AIFS-ENS）**
1. 丟棄 `stormIdentifier` 序號 70 以上的系統（模式自行生成）[實測；70 這個界線的官方定義是 [待驗證]]。另加一道不依賴 70 的檢查：`longStormName` 與 `stormIdentifier` 相同、且沒有分析位置的，也丟棄 [實測的特徵]。
2. 丟棄殘留的舊分析：沒有任何預報步（只有時效 0）的系統不輸出 [依 10a 的實測現象；成因是 [待驗證]]。
3. `match: "name"`：`longStormName` 與某個系統的 `name` 相同、季別相同，且時效 0 的位置與官方分析位置（時間最接近者）相距不超過 500 km [初值] → 歸到該系統。
4. `match: "position"`：名稱對不上（命名前）時，用位置比對，規則同 2.3 的第 3 點。
5. `stormIdentifier` 只寫入 `source_id` 供追查，**不參與任何判斷**。

**共通**
- 已命名系統不一定每個 cycle 都出現在 ECMWF 檔案 [實測]。某個 cycle 沒有該系統 → 該 cycle 檔的 `models` 就沒有那個模式；**不代表系統消散**，也不影響官方索引的 `status`。
- 同一個模式在同一個 cycle 有兩條路徑對到同一個系統時，兩條都不採用並記錄（不猜測）。

---

## 3. 活躍判定、狀態與清除

### 3.1 納入範圍

- 西北太平洋範圍定義為：北緯 0° 至 60°、東經 100° 至 180°（不含 180°）。
- JMA 與 CWA 的系統：全部納入。前提是這兩個來源只發布西北太平洋（含南海）的系統 **[假設：依兩個機構的責任區推定，source-matrix 沒有這項實測]**。保險做法：最新分析位置在北緯 0°–60°、東經 90°–180° 以外的 JMA／CWA 資料不納入並記錄。
- JTWC：RSS 的西北太平洋項目全部納入；**中太平洋／東太平洋項目的系統，只有在最新分析位置落在上述範圍內時才納入** [已決定]。PENA 在 S3 補測時位於 171.3W，預報 36 小時後越過 180° [實測 S3]：依此規則，越線前不納入，分析位置越線後納入，`origin_basin` 為 `CP`。
- 系統納入後，即使之後移出範圍（例如向東越過 180°），仍保留到結束為止。
- 北印度洋的系統雖與西北太平洋在 JTWC 的同一個 RSS 項目 [實測：項目標題含 North Indian Ocean]，依編號字尾（`A`、`B`）排除。

### 3.2 各機構的「活躍」判定

一筆機構資料同時滿足以下兩點才算活躍（`summary.*.active = true`）：

| 機構 | 結束標記（任一成立即不活躍） | 過期門檻（最新分析時刻早於「現在－門檻」即不活躍）|
|---|---|---|
| JTWC | RSS 該系統文字含 `Final Warning` [實測 S3] | 15 小時 [初值]：6 小時一報、發布比分析晚 3 小時，正常最久 9 小時；15 小時等於漏一報 |
| JMA | 最新 VPTW60 的 `TyphoonClass` 為 `温帯低気圧(LOW)` [實測 S3，**只有一個樣本**]。`Remark` 的 `台風消滅` **不單獨當作結束標記**（見下方說明）| 9 小時 [初值]：3 小時一報，等於漏兩報 |
| CWA | 沒有已知的結束標記 **[待驗證]** | 15 小時 [初值]：6 小時更新、延遲約 1.5 小時 [實測]，等於漏一報 |

- 「現在」一律由呼叫端傳入，不在判定函式內讀系統時鐘（第 9 節）。
- JMA 的 `熱帯低気圧(TD)` 仍算活躍（V1 範圍含 TD）。
- JMA 的結束標記只看 `TyphoonClass`，理由：唯一的樣本是「變性為溫帶低氣壓」，`Remark` 為 `台風消滅（温帯低気圧化）`。颱風減弱為熱帶低氣壓時 `Remark` 的寫法沒有樣本 **[待驗證]**；若它也含 `台風消滅`，以 `Remark` 判斷會把仍在範圍內的 TD 判成結束。只看 `TyphoonClass` 的話，減弱為 TD 的系統維持活躍；JMA 若之後不再發報，9 小時的過期門檻會讓它結束。`TyphoonClass` 出現未知的值時視為活躍並記錄。
- **過期門檻只在該來源本次 `ok` 時套用**。來源 `failed` 時不重新判定，沿用前一次的 `active`（第 3.3 節）。
- **來源本次 `ok`，但不再列出我方持有的系統**（CWA 的陣列少了那一筆；JTWC 的 RSS 不再列出它）：該機構對這個系統的 `active` 立刻設為 `false`，`summary`、`analysis.json`、`forecast.json` 中**保留最後一筆資料**（不清成 `null`），直到系統從索引移除。JMA 不適用這一條：JMA 靠電文與 9 小時門檻判定。
- 不能用「是否出現在檔案或清單」判斷活躍：JTWC RSS 在最終報後 20 小時仍列出系統、JMA `targetTc.json` 在消散後 22 小時仍列出 `LOW`、CWA 可能保留舊內容 [實測 S3／官方文件]。

### 3.3 來源狀態與整體 `status`

**各來源的 `state`**

| 來源 | `ok` 的條件 | 「成功且沒有系統」的條件 |
|---|---|---|
| CWA | HTTP 200、JSON 可解析、結構符合預期 | 颱風陣列存在，且為空或每一筆都不活躍。**其他長相一律視為 `parse_error`**（無颱風時的實際回應是 [待驗證]，不猜測） |
| JMA | 見下方「JMA 的判定」 | 同左 |
| JTWC | RSS 取得並解析成功、找得到西北太平洋項目；RSS 列出的每個相關系統的 `.tcw` 都取得並解析成功 | 西北太平洋項目寫 `No Current Tropical Cyclone Warnings.` [實測：南半球項目]，或列出的系統全部是 Final Warning 或不在範圍內 |

- 403、404、逾時、5xx、解析失敗都是 `failed`，**一律不當成「沒有颱風」**。JTWC 不存在的產品回 403 [實測]，同樣是 `failed`。
- JTWC 要求「每個相關系統的 `.tcw` 都成功」包含中／東太平洋項目的系統：不抓到 `.tcw` 就不知道它是否已越線進入範圍，所以任何一個失敗都讓 JTWC 整個 `failed`（保留舊資料）。這比較嚴格，但 JTWC 不是必要來源，代價只是顯示 `PARTIAL`。

**JMA 的判定**（`extra.xml`、`targetTc.json`、長期 feed 三者的組合；抓取流程見 5.3）

令「涵蓋足夠」＝ `extra.xml` 最舊的條目不晚於「我方已保存的最新 JMA 電文的 feed 時間 + 3.5 小時」。我方沒有任何 JMA 資料時視為不足。

| `extra.xml` | `targetTc.json` | 長期 feed | JMA `state` |
|---|---|---|---|
| 失敗 | — | — | `failed` |
| 成功 | 成功，且**它列出的每個非 `LOW` 系統，我方都持有 6 小時內的 VPTW60**（必要時先以長期 feed 補抓）| 不需要，或補抓成功 | `ok` |
| 成功 | 成功，但有非 `LOW` 的系統在補抓長期 feed 之後仍沒有對應的 VPTW60 | 成功或失敗 | **`failed`**（`validation_error`）|
| 成功 | 失敗或長相不符預期 | 涵蓋足夠 → 不抓 | `ok`（只靠有官方文件的 feed）|
| 成功 | 失敗或長相不符預期 | 涵蓋不足 → 補抓成功 | `ok` |
| 成功 | 失敗或長相不符預期 | 涵蓋不足 → 補抓失敗 | `failed` |

- 第三列是刻意的保守做法：JMA 自己的清單說有系統，我方卻拿不到它的電文（例如 JMA 不對某些 TD 發 VPTW60，這是 [待驗證]），此時**不能**把 JMA 算成「成功且沒有系統」，否則 CWA 也沒有該系統時會誤判 `OK_NO_STORMS`。判為 `failed` 的結果是 `PARTIAL`。若實際觀察到 JMA 確實不為某類系統發電文，再決定是否改為「以 `targetTc.json` 的項目成立只有編號、沒有位置的系統」；那需要修改契約，不在本版範圍。
- JMA「成功且沒有系統」＝ `state` 為 `ok`，而且沒有任何活躍的 VPTW60 系統。

**來源失敗時的資料與活躍狀態**

- **`state` 是來源層級的結論，個別系統的資料另外處理**。來源判為 `failed` 的那一輪，凡是**已成功取得並解析**的個別系統資料照常採用、照常依 3.2 判定活躍（例如 JMA 因判定表第三列而 `failed`，但另一個颱風的新電文已下載成功；或 JTWC 有一個 `.tcw` 失敗，其他系統的 `.tcw` 成功）。`failed` 的意義只是「不能據此斷定該來源沒有其他系統」。
- 該輪**沒有取得**的系統：`summary`、`analysis.json`、`forecast.json` 中保留前一次的資料（從候選目錄內的舊檔帶入）。
- 這些沒有取得的系統，`active` **沿用前一次的值，不套用過期門檻**。理由：抓不到不等於系統結束；若照樣套用門檻，唯一持有某系統的來源連續失敗十幾小時，該系統就會被錯標為 `ended`、48 小時後移除。
- 上限：來源連續失敗超過 **72 小時**（以 `last_ok_at` 計算）[初值] 之後，該來源的資料一律視為不活躍。避免一個長期失效的來源讓系統永遠停在 `active`。
- 後果（需知）：**只有 JTWC 發報的系統**，在 JTWC 連續失敗 72 小時後會變成 `ended`；若同時 CWA 與 JMA 都成功且沒有系統，整體會是 `OK_NO_STORMS`。這是「JTWC 不列必要來源」[已決定] 的直接結果。在那之前的 72 小時內顯示為 `PARTIAL`。

**整體 `status`**（由上往下，第一個成立的為準）

| 條件 | `status` |
|---|---|
| 三個來源全部 `failed` | 不寫檔，任務視為失敗（保留舊索引，第 5.5 節）|
| 任一**必要**來源（CWA、JMA）`failed` | `PARTIAL` |
| 必要來源都 `ok`，沒有任何 `active` 的系統 | `OK_NO_STORMS`（即使 JTWC `failed`）[依已決定的第 4 項] |
| 必要來源都 `ok`，有 `active` 的系統，JTWC `failed` | `PARTIAL` |
| 三個來源都 `ok`，有 `active` 的系統 | `OK_WITH_STORMS` |

- JTWC `ok` 且回報範圍內有活躍系統、但 CWA 與 JMA 都沒有時：該系統照常成為一筆（只有 JTWC 的資料），`status` 為 `OK_WITH_STORMS`。
- `PARTIAL` 時 `storms` 可能是空陣列（例如 CWA 成功且沒有系統、JMA 失敗）：前端顯示「部分來源無法取得，無法確認是否有活躍系統」，**不得顯示「目前無活躍熱帶系統」**。
- `storms` 內只剩 `ended` 的系統時，`status` 仍可為 `OK_NO_STORMS`；前端在「目前無活躍系統」下方列出近期結束的系統。

### 3.4 前端推導的狀態

| 情況 | 前端顯示 |
|---|---|
| 讀不到索引（404、網路錯誤、JSON 不合預期） | `UNAVAILABLE`：「熱帶系統資料暫時無法取得」。不得顯示為無系統 |
| 索引讀到，但任一必要來源的 `last_ok_at` 距今超過 3 小時 [初值] | `STALE`：顯示索引內容，並標示「最後確認時間：…」。此時即使 `status` 是 `OK_NO_STORMS` 也要加上過期警示 |
| 其他 | 依索引的 `status` |

- `STALE` 優先於索引的 `status`：兩者同時成立（例如索引是 `PARTIAL`、而且已過期）時，主要訊息顯示過期，各來源的 `state` 仍逐一列出。

- 三個來源全部失敗時後端不寫檔，索引停在最後一次成功的內容；`last_ok_at` 不再前進，超過門檻後前端自然顯示 `STALE`。這就是 plan 2.5 的 STALE。
- 若不採用心跳（第 13 節 C 選擇替代方案），這一列改為只顯示各機構的 `analysis_time`，不判定 STALE。

### 3.5 系統的結束與保留

- `storms[].status = "active"`：至少一個機構的 `active` 為 `true`。
- `storms[].status = "ended"`：沒有任何機構 `active`。第一次判定時寫入 `ended_at`。
- 已 `ended` 的系統若又有機構轉為活躍（例如重新增強、重新發報），改回 `active`，`ended_at` 清為 `null`。
- **保留期**：`ended` 的系統在索引中保留到 `ended_at` 之後 48 小時 [建議，第 13 節 B]，之後從索引移除。保留期內 `analysis.json`、`forecast.json` 與既有的模式檔都還在，使用者可以看到最後狀態。
- 模式任務只為 `active` 的系統抓新 cycle；`ended` 的系統不再抓，**但它在模式索引與 Ensemble 索引中的項目與檔案要保留**，直到系統從官方索引移除（5.4）。
- 被移除的系統不留紀錄。之後來源若還殘留它的舊資料，因為不活躍，不會再被鑄造成新系統（2.2）。若它真的重新增強並再度發報，會以活躍資料重新成立；由同一機構鑄造時 `cyclone_id` 與先前相同。

### 3.6 清除（必須是獨立步驟）

`snapshot_runner.run_candidate` 會把更新函式刪掉的既有檔案還原，並標成無效輸出（「Updates may never delete a validated prior resource」）。所以颱風任務**不能自己刪檔**。

- 做法：比照 `_prune_past_history`，在所有任務跑完後執行一個清除步驟（S6 實作，S8／S9 擴充）。
- 規則只有一條：**`tropical/` 底下任何沒有被三個索引檔列出的檔案都刪除**。
  - `tropical/official/storms/{id}/…`：`id` 不在 `tropical/official/index.json` 的 `storms` 內 → 刪除。
  - `tropical/models/storms/{id}/{cycle}.json`：不在 `tropical/models/index.json` 列出的組合內 → 刪除。
  - `tropical/ensemble/storms/{id}/{cycle}/{model}.json`：不在 `tropical/ensemble/index.json` 列出的組合內 → 刪除。
- 任務只負責「把不要的項目從自己的索引拿掉」：官方任務移除過了保留期的系統；模式任務移除超過 4 個（Ensemble 2 個）的舊 cycle，以及**在有效的官方索引中已不存在**的系統。官方索引讀不到或無效時，模式任務不移除任何項目（5.4）。
- 清除步驟不發任何網路請求，只讀候選目錄內的三個索引。索引檔讀不到或無效時，**該前綴不做任何刪除**。
- 被清除的路徑必須從 `run_candidate` 的 `expected` 中扣除（否則會被算成缺檔，整個候選變成不可發布）。**報告中另用一個新欄位（如 `pruned_tropical`）記錄，不併入現有的 `pruned_history`**：`tests/test_history_pruning.py` 以 `pruned_history` 的筆數斷言，併入會改變現有測試的結果。
- 只在 `mode == 'refresh'` 執行；明確的 `publish` 路徑原樣重發種子，不清除（與現有 history 清除一致）。

---

## 4. 白名單註冊與舊快照相容

### 4.1 `snapshots.py` 的修改方式（S4 起逐階段加入）

- **`REQUIRED` 不變**。颱風路徑一律「允許但非必要」。
- `allowed_path` 新增以下精確比對（`re.fullmatch`），各階段只加自己用到的：

| 階段 | 新增的允許路徑 |
|---|---|
| S4 | `tropical/official/index.json` |
| S6 | `tropical/official/storms/{id}/(analysis|forecast).json` |
| S8 | `tropical/models/index.json`、`tropical/models/storms/{id}/{cycle}.json` |
| S9 | `tropical/ensemble/index.json`、`tropical/ensemble/storms/{id}/{cycle}/(gefs|aigefs|ifs-ens|aifs-ens).json` |

  其中 `{id}` 為 `[0-9]{4}-(jma|jtwc|cwa)-[a-z0-9]{1,8}`，`{cycle}` 為 `[0-9]{8}(00|06|12|18)`。

- `validate_resource` 新增對應分支，放在現有分支之後、`else: raise` 之前。建議把颱風驗證器寫在新模組（如 `fetchers/src/tropical_contract.py`），`validate_resource` 只負責轉呼叫，避免 `snapshots.py` 繼續膨脹。
- 驗證器的要求（與現有驗證器同等嚴格）：
  - 精確欄位集合（`exact`）；精確型別（`type(x) is int`，不接受 `bool` 冒充）。
  - 路徑與內容一致：檔內的 `cyclone_id`、`cycle`、`model` 必須等於路徑上的值。
  - 時間格式、`valid_time = init_time + tau_h`、排序與不重複。
  - 數值範圍：`lat` -90–90、`lon` -180–180（不含 180）、`pressure_hpa` 850–1100 或 `null`、風速 0–200 或 `null`、`tau_h` 範圍。
  - 結構上限（第 6.1 節）：系統數、cycle 數、成員數、點數。
  - 列舉值：`status`、`state`、`error_code`、`match`、`dir`、`note`、`provider`、`wind_unit`。
  - 網址欄位：主機清單與憑證檢查（第 1.2 節）。
  - 字串長度上限（名稱 40 字元、`category` 40 字元等），避免把任意上游文字帶進公開資料。
- 驗證器**不做跨檔檢查**（例如索引列出的檔案必須存在）。理由見 4.3。
- **驗證器對任何不合格的輸入只能丟 `ValueError`**。`validate_resource` 只把 `KeyError`、`TypeError`、`RuntimeError`、`OverflowError`、`AttributeError` 轉成 `ValueError`，`read_resources` 只攔 `ValueError` 與 `OSError`。颱風驗證器若漏出 `IndexError` 之類的例外，會讓整輪（含 13 項圖資）中斷。做法：颱風驗證器的入口自己包一層，把所有例外轉成 `ValueError`；S4 的測試要以各種畸形輸入（空陣列、長度不足的 `track` 點、巢狀型別錯誤）確認。

### 4.2 相容性

| 情境 | 結果 |
|---|---|
| 舊快照（沒有任何 `tropical/` 檔）＋新程式 | 可以正常恢復、封裝、發布。`REQUIRED` 沒變，沒有任何檢查要求颱風檔存在 |
| 新快照（含 `tropical/` 檔）＋新程式 | 正常 |
| **新快照＋舊程式**（程式回復到沒有颱風白名單的版本）| **無法恢復**：舊的 `allowed_path` 會拒絕 `tropical/` 路徑，`read_resources` 與 `unpack_snapshot` 都會報錯 |

第三列是上線與回復方案必須處理的風險：

1. **白名單要先於資料**：允許路徑與驗證器必須先合併到預設分支，颱風任務才能開始產生檔案。同一個 commit 一起上線可以；先上任務、後上白名單不行。
2. **回復方案不能是「還原程式」**：一旦線上快照含有颱風檔，把程式退回沒有白名單的版本會讓所有較新的快照都讀不進來。正確的停用方式是**把任務從 `due-intervals.json` 拿掉，保留白名單與驗證器**（第 5.6 節）。這一點要寫進 S12 的回復步驟。
3. **契約只能往相容的方向改**：已上線的 `schema_version` 不得改變欄位。要改欄位就新增版本號，驗證器同時接受新舊版本，直到保留期內的舊快照（約 26 份、15 天）都已換新。
4. 功能分支上的本機測試只能寫入 `.runtime` 內的隔離儲存區，不得把含颱風檔的快照存進線上共用的 artifact。

### 4.3 連帶檢查的模組

| 模組 | 是否需要修改 | 說明 |
|---|---|---|
| `pages_package.site_summary` | 不需要 | 它只檢查 `REQUIRED` 與 radar／satellite／rainfall 的 history。颱風檔會被算進 `json_files` 的數量，僅此而已。**不新增颱風的跨檔檢查**：否則一個颱風檔的問題會讓整個快照無法封裝，違反失敗隔離 |
| `pages_package.unpack_snapshot` | 不需要 | 用 `allowed_path` 判斷，白名單加了就通過。單一項目上限 8 MB、項目數上限 10000、壓縮檔上限 128 MB，都遠高於第 6 節的上限 |
| `content_versions` | 不需要 | 颱風檔不含 `image_url`，`images_in` 找不到圖片，不會發請求；`fetched_at` 被排除在識別之外 |
| `verify_pages_build.py` | S5 要改 | 新增檢查 `tropical/index.html` 存在且與入口相同（第 7.1 節）|
| `snapshot_runner.belongs` | S4 要改 | 見第 5.2 節 |
| `snapshot_runner.run_candidate` | S6 要改 | 加入第 3.6 節的清除步驟 |
| `due_refresh.checked_update`、`deployment_decision` | S4 要改 | 見第 5.2、5.5 節 |
| `update_images.update_image`（由 `refresh_pages.py` 當成 `update` 傳入）| S4 要改 | 它對未知的名稱會丟 `KeyError`。S4 要為颱風任務加分派。`registered_products()` 的其他使用者 S4 要逐一檢查，確認颱風任務不會被當成圖資列舉 |
| `cloud_snapshots.validate_state`、`cleanup` | 不改程式，但行為要知道 | `validate_state` 也以 `default_tasks()` 驗證排程狀態：任務集合改變的那一輪，舊狀態是在這裡被拒絕的。`cleanup` 同樣驗證不過舊狀態的 artifact，不會主動清除它們，要等保留期到期。S12 驗收時要預期這個現象 |
| `due_refresh._restore` | 不改 | 排程狀態被重置時，history 缺口狀態會一併清空（5.1）|
| `history_reconciliation.history_due` | 不需要 | 對未知的任務名稱回傳 False，不會出錯 [審查代理已對照原始碼確認] |
| `tests/test_scheduling.py` | S4、S8、S9 要改 | 寫死了 13 項任務的間隔；每次加任務都要同步更新，否則每輪發布前的測試會失敗 |
| `tests/test_history_pruning.py` | 不應需要改 | 前提是颱風清除用獨立的報告欄位（3.6）|
| `frontend/src/api.js` | S5 要改 | `readStatic` 目前沒有匯出；S5 匯出它或新增颱風專用的讀取函式 |

---

## 5. due 任務

### 5.1 任務定義

加入 `fetchers/policies/due-intervals.json` 的 `tasks`，**排在現有 13 項之後**（`prepare_due` 依這個順序執行，現有圖資先跑）。三個任務的順序固定為官方 → 模式 → Ensemble，因為後兩者要讀官方索引。

| 任務名稱 | 加入階段 | `interval_seconds` | `retry_delays_seconds` | 路徑前綴 | 必存檔 |
|---|---|---|---|---|---|
| `tropical_official` | S4 | 1800 | `[600, 1200, 2400, 3600]` | `tropical/official/` | `tropical/official/index.json` |
| `tropical_models` | S8 | 3600 | `[1800, 3600, 7200, 14400]` | `tropical/models/` | `tropical/models/index.json` |
| `tropical_ensemble` | S9 | 3600 | `[1800, 3600, 7200, 14400]` | `tropical/ensemble/` | `tropical/ensemble/index.json` |

**間隔的理由**
- 官方：JMA 每 3 小時、CWA 與 JTWC 每 6 小時發布 [實測／官方文件]。30 分鐘檢查一次，最慢 30 分鐘內反映新報；每次約 4–10 個請求。
- 模式與 Ensemble：每天 4 個 cycle，每小時檢查一次，最慢 1 小時內取得新 cycle。尚未到預期發布時間的 cycle 不發請求（5.4）。
- 重試延遲只用於**真正的失敗**（網路、5xx、解析錯誤）。「cycle 尚未發布」不算失敗（5.4），不會進入重試退避。

**加入任務的副作用**：`scheduling.restore_state` 發現狀態檔的任務集合與設定不同時，會把狀態判為 `corrupt` 並重置，**所有任務在那一輪全部視為到期**（`cloud_snapshots.validate_state` 會先以同樣的理由拒絕舊狀態）。S4、S8、S9 各自上線的那一輪：
- 13 項圖資會全部重新檢查一次；
- `due_refresh._restore` 會把 history 缺口的重查狀態一併清空，當日缺口的重查次數從頭計算；
- 舊的狀態 artifact 不會被 `cleanup` 主動清除，要等到期。

這些都是一次性的，但那一輪的執行時間會比平常長，S12 要安排在可觀察的時段並寫進驗收紀錄。

### 5.2 接進現有流程需要的修改（S4 實作，這裡只定規格）

現有程式把「任務」與「`images/{kind}/`」綁在一起，有五處要加規則：

1. **`snapshot_runner.belongs(name, product)`**：`tropical_official` → 前綴 `tropical/official/`；`tropical_models` → `tropical/models/`；`tropical_ensemble` → `tropical/ensemble/`。
2. **`due_refresh.checked_update` 的 `latest_name`**：颱風任務對應到各自的 `index.json`。
3. **`due_refresh.checked_update` 的圖片雜湊與重寫區塊**：颱風任務必須**跳過**。那一段對內容識別與舊檔不同的檔案（也就是每一個新寫入或有變更的檔）用 `json.loads` 讀入、經 `stamp_changed_images` 後以 `atomic_write_json` 重寫；颱風檔沒有圖片可處理，卻會把精簡格式的模式檔改寫成縮排 2 的格式。之後「依內容識別還原舊位元組」的那一段要保留（它負責丟棄只有 `fetched_at` 改變的重寫）。
4. **更新函式的寫入位置**：`update(kind, images_root)` 收到的是候選目錄的 `images/`；颱風任務寫到 `images_root.parent / 'tropical' / …`。
5. **獨立的請求預算範圍**：每個颱風任務在自己的 `http_scope()` 內執行（見 5.4「請求預算」）。

其他入口：
- 本機的 `update_images.py`、`update_runner`、`local_updater` 以 `IMAGE_TYPES` 列舉圖資。颱風任務**不加入 `IMAGE_TYPES`**（那會讓它變成 `REQUIRED`，也會被前端當成圖片頁）。S4 為颱風任務另設本機入口或在註冊表中分開列。
- `refresh_pages.py` 把 `update_images.update_image` 當成 `update` 傳入，它對未知的名稱會丟 `KeyError`：S4 要加上颱風任務的分派（4.3）。
- `history_due` 對未知的任務名稱回傳 False，不需要修改 [審查代理已確認]。

### 5.3 `tropical_official` 的抓取流程與請求數

固定 UA（第 5.7 節）。同一來源連續請求之間至少間隔 1 秒。

請求預算：`tropical_official` 在自己的 `http_scope()` 內執行，以下各來源的次數與時間都**從這個任務開始時重新計算**，不與同一輪的現有圖資共用（理由與取捨見 5.4「請求預算」）。

**CWA**（`cwa`：600 次／240 秒）
- 1 次：`datastore/W-C0034-005`。金鑰由環境變數讀取，以 `params` 傳入（不拼進網址字串）。不使用會轉址的 fileapi [實測]。
- 遮蔽：任何 log、例外、狀態檔、公開 JSON 都不得出現含金鑰的網址。錯誤只記固定代碼。比照現有 `rainfall_observation_service` 的做法。

**JMA**（`jma`：80 次／90 秒）
1. 1 次：`extra.xml`（約 73 KB [實測 S3]）。找出連結符合 `https://www.data.jma.go.jp/developer/xml/data/{14 位數字}_{數字}_VPTW60_{6 位數字}.xml` 的條目；其他種類（含 VPTW61）忽略。
2. 0–12 次：下載 feed 時間在最近 4 小時內、**而且網址不等於我方任何系統已保存的 JMA `product_url`** 的 VPTW60 電文，由新到舊，每次執行最多 12 則。下載後依 `EventID` 分組，每個系統採用 `ReportDateTime` 最新的一則；不比我方已保存者新的就丟棄。
   - **以網址去重，不以單一的全域時間比較**。理由：電文內的發布時刻比 feed 時間晚幾分鐘（樣本的 feed 時間是 12:41:52Z，`ReportDateTime` 是 12:45:00Z [實測 S3]）；兩個系統同一批發報、某一輪只看到其中一則時，用「比已保存的最大 `issued_at` 新」來篩會跳過另一則，要等 3 小時後的下一報。
   - 4 小時的窗口涵蓋一個發報週期（3 小時）加餘裕。每個系統每輪因此可能多下載一則較舊的電文（約 3 KB），可以接受。
3. 1 次：`targetTc.json`（約 100 bytes）。只當作**活躍清單的交叉檢查**，不取用它的預報或路徑。
4. 0–1 次：長期 feed `extra_l.xml`（2.7 MB [實測 S3]）。只在以下情況抓：
   - (a) `targetTc.json` 列出 `category` 不是 `LOW` 的系統，但我方沒有它在 6 小時內的 VPTW60；或
   - (b) `targetTc.json` 取得失敗或長相不符預期，而且 `extra.xml` 的涵蓋不足（定義見 3.3）；或
   - (c) 我方有 JMA 仍為 `active` 的系統，它最新的電文已超過 4 小時，而本次步驟 2 沒有取得它的新電文。這是為了補上任務停擺超過 4 小時期間發出的最終報（最終報之後 JMA 不再發報，`targetTc.json` 只會列 `LOW`，不會觸發 (a)）。
   - 抓到後只處理最近 6 小時內的 VPTW60，去重與分組規則同步驟 2。
5. 依 3.3「JMA 的判定」表決定 `state`。
- 理由：`extra.xml` 官方只保證保留 10 分鐘 [官方文件]，而任務每 30 分鐘才跑一次；實際觀察到約 10 小時 [實測]，但不能依賴。正常情況靠 `targetTc.json` 發現漏抓；它是非文件化介面，壞掉時退回有官方文件的長期 feed。
- 流量：最壞情況（每次都抓長期 feed）每天約 130 MB，遠低於官方每 IP 每日 10 GB 的上限 [官方文件]。
- XML 解析用標準函式庫；解析前拒絕含 `<!DOCTYPE` 或 `<!ENTITY` 的文件（第 8 節）。

**JTWC**（新來源名稱 `jtwc`：預設的 80 次／90 秒）
1. 1 次：RSS。
2. 每個相關系統 1 次：`.tcw`（西北太平洋項目的系統，加上中／東太平洋項目的系統——後者要先抓 `.tcw` 才知道位置是否在範圍內）。同時期通常 0–4 個。
- **只抓 RSS 與 RSS 內連結的產品檔，不抓 HTML** [依 S1 條件 6]。
- **以 RSS 連結為準，不自行組檔名** [依 S1 條件 4]。RSS 內的連結必須符合 `https://www.metoc.navy.mil/jtwc/products/[A-Za-z0-9_.-]+` 才會被請求；不符合的忽略。RSS 項目本身的 `link` 指向 `s3.amazonaws.com/…/jtwc.html` [實測]，那是 HTML，不請求。
- `.tcw` 的 Content-Type 是 `binary/octet-stream` [實測]，以 latin-1 解碼後解析標頭行與 `T000／T012…` 行。
- 中心氣壓在警報文字（`web.txt`）的 REMARKS 中 [實測]；`.tcw` 後半含全文 [實測]，先從 `.tcw` 找，找不到就填 `null`，**不為了氣壓多抓一個檔**。
- 轉址：S3 補測時 RSS 與產品都直接回 200，沒有轉址 [實測 S3]。`http_client` 禁止跨來源轉址；若日後 JTWC 改成轉到其他網域，請求會失敗、JTWC 變成 `failed`、整體顯示 `PARTIAL`，不會影響其他來源。S4 在 `http_client.source_name` 的對照表加上 `'jtwc': ('metoc.navy.mil',)`。

**每次執行的請求數**：無颱風時 4 次（CWA 1、JMA 2、JTWC 1）；一個颱風時約 6–7 次；最壞情況約 30 次。

### 5.4 `tropical_models` 與 `tropical_ensemble` 的抓取流程

**共通**
- 先讀候選目錄內的 `tropical/official/index.json`，依結果分三種情況：

| 官方索引 | 模式任務的行為 |
|---|---|
| 讀不到或無效 | **不發請求、不改動自己的索引與檔案**，任務算成功。自己的索引還不存在時（第一次執行）寫出空的索引。理由：官方索引一次暫時性的問題不該清掉模式資料，NOMADS 只能補抓約一天 |
| 有效，沒有 `active` 的系統 | 不發請求。只做整理：移除官方索引中已不存在的系統。`ended` 的系統**保留**（3.5）。來源 `state` 記為 `idle` |
| 有效，有 `active` 的系統 | 做整理，再為 `active` 的系統補抓（以下各點）|

- 模式任務不因官方任務失敗而失敗。
- 計算本次的 `match_basis`；與自己索引中的不同時，把 `checked` 視為空（1.6）。
- 只處理最近 4 個 cycle（Ensemble 2 個）。**已記在 `checked` 的組合不再請求**，不論當時有沒有對到系統。
- **預期發布時間**：cycle 時刻加上下表的最早等待時間之前，不發請求。超過「放棄時間」仍沒有的 cycle 不再嘗試。

| 模式 | 最早等待 [初值] | 實測延遲 | 放棄時間 |
|---|---|---|---|
| AIGFS | 3.75 小時 | +4.0 至 +4.1 小時 | 24 小時（NOMADS 只保留兩個日期目錄 [實測]，以約一天設計）|
| GFS | 4.5 小時 | +4.7 至 +4.8 小時 | 24 小時 |
| AIGEFS | 4.5 小時 | +4.6 至 +5.3 小時 | 24 小時 |
| GEFS | 5.25 小時 | +5.5 至 +5.6 小時 | 24 小時 |
| IFS | 6.0 小時 | +6.2 至 +6.9 小時 | 48 小時（ECMWF 保留約 12 個 run [官方文件／實測]）|
| AIFS | 6.25 小時 | +6.5 至 +7.1 小時 | 48 小時 |
| IFS-ENS、AIFS-ENS | 7.0 小時 | +7.3 至 +7.7 小時 | 48 小時 |

  延遲樣本只有 3–7 個 cycle [實測]。最早等待取得比實測下緣略早，代價只是每小時多 1 次探測請求。

- **「尚未發布」的回應不是失敗，但有期限**：NOMADS 對未發布的 cycle 回 403、對過期或不存在的回 404；ECMWF 對未發布的回 404 [實測]。
  - 在「最早等待」之後、「**逾期時間**」之前遇到這些狀態碼：記為「尚未取得」，下次再試；該來源的 `state` 仍是 `ok`。
  - **逾期時間＝最早等待 + 6 小時** [初值]（遠超過實測延遲的上緣）。**以來源為單位判斷**：某來源在本次請求的產品中，已過逾期時間的**全部**仍回 403／404 時，該來源的 `state` 記為 `failed`、`error_code` 為 `http_error`，照常每次執行再試。只有其中一個產品逾期（例如 AIFS 的 tf 產品停止提供，而 IFS 正常）不算來源失敗；該產品在那個 cycle 視為沒有資料，過了放棄時間就記進 `checked`。理由：來源若擋下 Actions 的 IP 或更改檔名規則，回應同樣是 403／404；沒有這個期限的話，來源會永遠顯示 `ok`，沒有人看得到異常。
  - **不依回應本體判斷**（NOMADS 有兩種 403 本體 [實測]，且本體含請求端 IP，不得記錄或保存）。
- 逾時、連線錯誤、429、5xx、解析失敗是該來源的 `failed`。
- **任務層級的成敗**：只要有一個來源不是 `failed`（`ok` 或 `idle`），任務就算成功，把各來源的 `state` 寫進索引，下次照常每小時執行。**兩個來源都 `failed` 時任務才算失敗**，保留舊索引並進入重試退避。單一來源失敗不會讓任務退避；它每小時只多花一次探測請求。
- **不列目錄**：NOMADS 的目錄清單在 Actions 上失敗 [實測，10a]。一律以已知檔名直接請求。
- 檔名規則 [實測]：
  - NOAA：`…/ens_tracker/prod/{gfs|aigfs|gefs|aigefs}.{YYYYMMDD}/{HH}/tctrack/{code}.t{HH}z.cyclone.trackatcfunix`；確定性 `avno`（GFS）、`agfs`（AIGFS）；GEFS `ac00`、`ap01`–`ap30`；AIGEFS `a000`–`a030`。
  - tcvitals：`…/gfs/prod/gfs.{YYYYMMDD}/{HH}/atmos/gfs.t{HH}z.syndata.tcvitals.tm00`。
  - ECMWF：`…/forecasts/{YYYYMMDD}/{HH}z/{model}/0p25/{stream}/{YYYYMMDDHH}0000-{step}h-{stream}-tf.bufr`。四組 `{model}/{stream}`：IFS 確定性 `ifs/oper`、IFS-ENS `ifs/enfo`、AIFS 確定性 `aifs-single/oper`、AIFS-ENS `aifs-ens/enfo` [實測]。`step`：`ifs` 的兩個產品在 00／12Z 為 360、06／18Z 為 144；`aifs-single` 與 `aifs-ens` 四個 cycle 都是 360 [實測；Ensemble 檔的 `step` 與確定性相同，見 S2 保存的 11/11 00Z、06Z 檔名]。
- 一個檔案含全球所有系統 [實測]，抓一次就能服務所有活躍系統；請求數與颱風數無關。

**`tropical_models` 每次執行的請求**
- 每個待補的 cycle：NOAA 2 次（`avno`、`agfs`）加 tcvitals 0–1 次（只在有系統的 `ids.jtwc` 為 `null` 時）；ECMWF 2 次（IFS、AIFS 確定性檔，各約 10–37 KB [實測]）。
- 平常每小時 0–4 次；新系統剛出現、要補 4 個 cycle 時最多約 20 次。

**`tropical_ensemble` 每次執行的請求**
- **每次執行、每個模式最多處理一個 cycle**：最近 2 個 cycle 中，最新的、尚未 `complete` 的那一個。較新的 cycle 已 `complete` 時，才回頭補較舊的。較新的 cycle 一旦 `complete`，更舊且未完成的 cycle 直接標為 `complete`（放棄），不再佔用請求。
- 執行順序：**先 ECMWF，後 NOAA**。ECMWF 只有兩次下載，先做完可以避免被 NOAA 的 62 次請求拖到 ECMWF 的時間窗之外。
- IFS-ENS、AIFS-ENS：各 1 次請求（0.3–1.1 MB [實測]）。兩個都下載完再解碼（本機每檔約 7 秒 [實測]；Actions 上的 Ensemble 解碼時間是 [待驗證]）。解碼時間不佔來源的時間窗。
- GEFS、AIGEFS：先請求第一個成員檔（`ac00`、`a000`）當探測。不是 200 就跳過這個模式（只花 1 次請求）。是 200 才依序請求其餘 30 個成員檔，間隔至少 1 秒。兩個模式合計約 62 次請求、約 90 秒。
- 個別成員檔**下載失敗**：保留已取得的成員並寫出檔案，把失敗的檔名記進 `checked.*.missing_files`；下次執行只補這些檔，直到齊全或超過放棄時間。成員檔取得了但裡面沒有這個系統，**不算缺漏、不重試**（1.8）。
- **這同時是請求預算或時間用完時的自然退路**：任務內部設 240 秒的時間上限 [初值]，到了就停，還沒請求的成員檔記進 `missing_files`，下次接著補。
- 成員數：GEFS 31、AIGEFS 31、IFS-ENS 51、AIFS-ENS 52 [實測]。

**請求預算（S8／S9 修改 `http_client`）[已決定]**

現有 `HttpPolicy` 的行為（對照 `http_client.py`）：
- 非 CWA 來源每輪 80 次／90 秒；CWA 600 次／240 秒。
- **時間窗從該來源在這一輪的第一個請求起算，是固定的**，不是每個任務各算各的。`run_candidate` 整輪共用同一個 `http_scope`。
- 某來源重試耗盡或等待過久時會被標成 `blocked`，**同一輪之後對該來源的所有請求都直接失敗**。

這對排在最後的颱風任務有兩個問題：
1. `radar` 排第一、每 10 分鐘到期，所以 CWA 的 240 秒幾乎每輪都從一開始起算。前面 13 項只要跑超過 240 秒，`tropical_official` 的 CWA 請求必定失敗；CWA 是必要來源，結果是 `PARTIAL`。JMA 的 90 秒在 `sst`（同屬 `jma`）到期的那一輪也一樣。
2. 現有任務把某來源弄成 `blocked` 時，颱風任務同來源的請求全部失敗。

（方向是颱風任務受害，現有圖資不受影響。）

**對策：每個颱風任務在自己的 `http_scope()` 內執行** [建議，第 13 節 J]
- `http_scope` 用 `ContextVar` 設定與還原，可以巢狀：在颱風任務的外層再開一個 scope，任務內的請求用全新的 `HttpPolicy`，結束後還原成外層的。**外層（現有圖資）的計數、時間窗、`blocked` 狀態完全不被讀取也不被改動**。
- 三個颱風任務各自一個 scope，彼此也不共用（`tropical_models` 用掉的 ECMWF 時間不會算到 `tropical_ensemble`）。
- 取捨：同一輪對 CWA、JMA 的總請求數可能超過「每輪每來源」的上限，超出的量就是颱風任務自己的用量（CWA 1 次、JMA 3–16 次）。這個上限的目的是防止單一來源拖垮整輪，颱風任務另有自己的上限，目的沒有被破壞。
- 替代方案：(a) 不隔離，接受颱風任務在前面跑得久的那幾輪顯示 `PARTIAL`；(b) 把颱風任務排到最前面，但這會讓颱風任務佔用現有圖資的時間窗，違反失敗隔離，不採用。

在各自的 scope 內，NOAA 的 Ensemble（62 次、約 90 秒）仍超過預設的 90 秒，所以仍需要專屬上限 [已決定第 9 項]：

| 來源名稱 | 主機 | 上限 [初值] | 理由 |
|---|---|---|---|
| `noaa` | `nomads.ncep.noaa.gov` | 200 次／420 秒 | 單一任務最多：Ensemble 62 次（約 90 秒），或確定性補 4 個 cycle 約 12 次。留餘裕給重試與變慢的回應 |
| `ecmwf` | `data.ecmwf.int` | 40 次／240 秒 | 單一任務最多 2 個 Ensemble 檔或 8 個確定性檔。時間含下載，不含解碼 |
| `jtwc` | `www.metoc.navy.mil` | 沿用預設 80 次／90 秒 | 每輪約 1–5 次 |

- 實作方式：把 `HttpPolicy` 內寫死的「`cwa` 用 600／240，其他用 80／90」改成查表，表內新增 `noaa`、`ecmwf` 兩列。**現有來源（含 `cwa`、`jma`）的數值不變。**
- 16 MB 的單一回應上限維持不變（最大的 Ensemble 檔約 1.1 MB）。
- NOMADS 沒有找到官方的請求頻率上限 **[待驗證]**。本設計在有颱風時每小時約 0–75 次、間隔至少 1 秒，屬保守用量。若被限流（429），`http_client` 會依 `Retry-After` 處理；超過 30 秒就放棄該來源本輪。
- 最小間隔 1 秒由颱風服務自己控制（`http_client` 沒有這個功能），等待函式可注入以便測試。

**執行時間**
- 實際抓取、測試與建置都在 `pages-manual.yml` 的 `build` job，上限 **20 分鐘**；這 20 分鐘還包含安裝相依套件、完整的 Python 與前端測試、前端建置。（`weather-relay.yml` 的 18 分鐘是只做接力的 job，與抓取無關。）
- 新增的時間估計：官方約 10–20 秒；確定性約 5–15 秒；抓到一個 Ensemble cycle 的那一輪約 2–3 分鐘（NOAA 約 90 秒、ECMWF 下載加解碼約 20–40 秒）。另外，新增的颱風測試會拉長每一輪的測試時間，S4 起每個階段都要量。
- 現有每輪的實際耗時本階段沒有量 **[待驗證]**。**S4 開始前應先從最近的執行紀錄取得 `build` job 的典型與最長耗時**，才能判斷餘裕。S9 的完成條件已要求實測；若餘裕不足，退路是把 Ensemble 任務的內部時間上限調低，讓它分多輪補齊。

### 5.5 失敗隔離

| 情境 | 行為 | 依據 |
|---|---|---|
| 某個颱風來源失敗，其他成功 | 任務成功，索引標 `PARTIAL` 或該來源 `failed`；失敗來源保留舊資料 | 任務內部處理 |
| 一個颱風任務整個失敗（例外或全部來源失敗）| `run_candidate` 把例外攔下，該任務標 `failed`；`checked_update` 把該任務前綴下的檔案回復成執行前的內容；排程進入重試退避 | 現有機制，前綴互不重疊所以不波及其他任務 |
| 颱風任務寫出不合契約的檔案 | `run_candidate` 把壞檔還原成舊檔（沒有舊檔就刪除）；`checked_update` 判為失敗 | 現有機制 |
| 颱風任務失敗時，13 項圖資 | **不受影響**：各自的檔案、雜湊、排程狀態都獨立；`complete` 的判斷只看 `REQUIRED` 與既有檔案是否仍在 | `REQUIRED` 不含颱風 |
| 颱風任務耗盡某來源的請求預算，或把來源弄成 `blocked` | 只影響該颱風任務自己。每個颱風任務有獨立的 `http_scope`，現有圖資的計數、時間窗與 `blocked` 狀態不被讀取也不被改動 | 5.4「請求預算」|
| 現有圖資耗盡 CWA／JMA 的預算，或把它們弄成 `blocked` | 不影響颱風任務（同上，反方向）| 同上 |
| 颱風任務執行太久 | 任務內部有時間上限（Ensemble 240 秒 [初值]）；現有圖資排在前面，已先完成 | 5.1 的順序 |

**部署決策（`deployment_decision`）[S4 必須修改]**

現有規則：內容沒變、而且「本輪嘗試的檢查全部是 `retained_after_failure`」或「所有產品都 `failed`」時不部署（`all_source_checks_failed`）。加入颱風任務後有兩個副作用：

1. 13 項圖資全部失敗、但颱風任務成功且內容沒變時，「全部失敗」不再成立，判斷會往下走到「已保存版本不在線上就部署」。
2. 只有颱風任務到期且失敗時，會被判成「全部失敗」而不部署；加入颱風之前，同樣的時點是「沒有任務到期」，判斷會往下走。

對策：計算 `attempted` 與 `products` 的「全部失敗」時，**排除名稱以 `tropical_` 開頭的任務**。目標是：**把颱風任務拿掉後，這個函式對同一輪的判斷與加入颱風前完全相同**。

這條規則只在「內容沒變」時才會被走到。各種組合的預期結果（都以通過前面的線上版本檢查為前提；S4 的測試照這張表寫）：

| 現有圖資本輪 | 颱風任務本輪 | 內容是否改變 | 預期 | 說明 |
|---|---|---|---|---|
| 有成功 | 失敗 | 是（圖資）| 部署，`content_changed` | 颱風失敗不阻止部署 |
| 有成功 | 失敗 | 否 | 與加入前相同：往下走到 `saved_version_not_online`（線上已是同一版本時在更前面就回傳 `already_online`）| |
| 全部失敗 | 成功，內容沒變 | 否 | 不部署，`all_source_checks_failed` | 修正副作用 1 |
| 全部失敗 | 失敗 | 否 | 不部署，`all_source_checks_failed` | |
| 全部失敗 | 成功，內容有變 | 是（颱風）| 部署，`content_changed` | 見下方 |
| 沒有任務到期 | 失敗 | 否 | 與加入前「沒有任務到期」相同：往下走（通常在更前面已是 `already_online`；已保存版本不在線上時會補部署）| 修正副作用 2。**不是「不部署」** |
| 沒有任務到期 | 成功，內容有變 | 是（颱風）| 部署，`content_changed` | |

**颱風內容變更會觸發部署，這是預期行為，不是對現有圖資的影響**。例如現有圖資全部失敗（保留舊檔），但颱風索引有新內容：`changed` 為真，會保存新版本並部署，網站上的圖資仍是先前驗證過的舊內容。需要保證的是反方向——颱風的失敗不會阻止、也不會促成現有圖資的保存與部署。

### 5.6 停用方式（給 S12 的回復方案）

- 停用某個颱風任務：從 `due-intervals.json` 移除該任務。既有的颱風檔會留在快照中（不再更新，前端依 3.4 顯示 STALE）。移除任務同樣會觸發一次排程狀態重置。
- 要讓頁面消失：前端移除入口連結即可，路由與資料可以保留。
- **不得**以還原白名單的方式停用（4.2）。
- 要清掉資料：需要一個明確的維護步驟刪除 `tropical/` 並保存新快照；不在 V1 自動流程內。

### 5.7 User-Agent

- 颱風服務的所有請求帶同一個固定、誠實標示身分的 UA。建議值：`weather-integration-static/1.0 (tropical cyclone data fetcher)` [建議，第 13 節 D]。
- **不得**為了通過阻擋而變換 UA、偽裝成瀏覽器或加上其他標頭。被擋就是 `failed`。
- JTWC 的 HTML 頁面會依 UA 被 CloudFront 擋下；RSS 與各產品檔用兩種自訂 UA 都是 200；requests 預設 UA 只抽測了 RSS 與 `wp3126web.txt`，兩者是 200，**沒有測 `.tcw`** [實測，S1]。建議的新 UA 字串本身沒有測過 **[待驗證]**：S4 的本機真來源測試要確認；若 RSS 或產品被擋，退路是改用現有服務的做法（不帶自訂 UA，使用 requests 預設值），並同樣要先實測 `.tcw`。
- 現有 13 項圖資的請求標頭不變。

---

## 6. 大小與保留

### 6.1 上限

驗證器以**結構上限**把關（它拿到的是解析後的資料，不是位元組）；寫入端另外檢查位元組數，超過就不寫該檔並記錄。

| 檔案 | 結構上限 | 單檔位元組上限 | 依據 |
|---|---|---|---|
| `official/index.json` | 12 個系統 | 64 KB | 每個系統約 1.5 KB |
| `analysis.json` | 3 個機構 × 160 個過去點 | 256 KB | 每點約 250–300 bytes（縮排格式）[估計；審查代理粗估約 300]，480 點約 144 KB，加上三個 `fix` 與風圈 |
| `forecast.json` | 3 個機構 × 24 點 | 64 KB | |
| `models/index.json` | 12 個系統 × 4 個 cycle | 16 KB | |
| `models/…/{cycle}.json` | 4 個模式 × 81 點 | 24 KB | 估計上限每模式約 2 KB [source-matrix 第 9 節] |
| `ensemble/index.json` | 12 個系統 × 2 個 cycle | 16 KB | |
| `ensemble/…/{model}.json` | 60 個成員 × 81 點 | 192 KB | 估計上限 81–82 KB、最壞約 90 KB [source-matrix 第 9 節，變體 A]；留一倍餘裕 |

- `tropical/` 整體上限 **4 MB**（未壓縮），拆成三個前綴各自的上限，**由各任務在寫出自己的索引之前量測自己前綴的總位元組數並執行**（任務不讀寫別人的前綴）：

| 前綴 | 上限 | 超過時的捨棄順序（從索引移除，由清除步驟刪檔）|
|---|---|---|
| `tropical/official/` | 1 MB | 先移除 `ended_at` 最早的 `ended` 系統；仍超過就把各系統的 `past_track` 從最舊的點開始截短（每次減半）；仍超過才任務失敗、保留舊檔 |
| `tropical/models/` | 0.5 MB | `ended` 系統最舊的 cycle → `active` 系統最舊的 cycle |
| `tropical/ensemble/` | 2.5 MB | `ended` 系統的 cycle → `active` 系統較舊的那個 cycle → 仍超過就不寫入本次新增的檔 |
- 同時超過 12 個系統（含 `ended`）時：先移除 `ended_at` 最早的 `ended` 系統；`active` 的系統不會被移除（若 `active` 超過 12 個，驗證會失敗、任務保留舊索引，並需要人工調整上限）。

### 6.2 保留

| 項目 | 保留 | 理由 |
|---|---|---|
| 官方分析與預報 | 每個機構只留最新一報；過去路徑累積在 `analysis.json` | V1 不做官方預報的歷史版本 |
| 確定性模式 | 最近 **4 個 cycle** [已決定] | 支援相同起報時間比較與修正趨勢；每個 cycle 最多 8 KB |
| Ensemble | 最近 **2 個 cycle** [已決定]，只存路徑 [已決定] | 每個 cycle 四個 Ensemble 的估計上限合計約 230 KB |
| 結束的系統 | `ended_at` 後 48 小時 [建議] | 第 3.5 節 |

「最近 N 個 cycle」的定義：以該系統在索引中**實際有資料**的 cycle 為準，取時間最新的 N 個。不是以時鐘推算。

### 6.3 估算

以 `source-matrix.md` 第 9 節的數字（精簡格式、變體 A）：

| 項目 | 實測（長路徑系統）| 估計上限 |
|---|---|---|
| 一個系統、一個 cycle 的四個 Ensemble | 約 89 KB | 約 229 KB |
| 一個系統、一個 cycle 的四個確定性 | 約 2–4 KB | 約 8 KB |
| **一個系統的模式資料**（Ensemble 2 個 cycle＋確定性 4 個 cycle）| 約 190 KB | 約 490 KB |
| 一個系統的官方資料（索引項目＋分析＋預報）| 約 30–60 KB [估計，未實測] | 約 320 KB（單檔上限合計）|
| **三個系統同時活躍** | 約 0.7 MB | 約 2.2 MB |

- 對照：現有快照整份約 15 KB [引自 plan 2.8]。有颱風時快照會變成數百 KB 到約 2 MB；無颱風時只多三個小索引檔（共約 2 KB）。
- 壓縮：Ensemble 樣本 gzip 後約為原大小的 15–36% [實測]。封裝用的是 ZIP deflate，預期相近 [估計]。三個系統的估計上限壓縮後約 0.4–0.8 MB。
- 保存：分層保留最多約 26 份快照 [引自 plan 2.8]，最壞約 20 MB。遠低於封裝上限（單一項目 8 MB、壓縮檔 128 MB）。
- 樣本只有兩個系統、三個 cycle，其中一個正在消散 [source-matrix 的限制]。生命期長的強颱可能更接近估計上限。**S9 的完成條件必須包含實測快照大小**。
- 前端下載量：GitHub Pages 會以 gzip 傳送 JSON [待驗證：未實測]。Ensemble 檔按需載入（第 7.4 節），不開啟就不下載。

---

## 7. 前端

### 7.1 路由 [已決定]

- 固定入口 `/tropical`。`pages-build.mjs` 多產生一個 `tropical/index.html`（內容與入口相同）；`verify_pages_build.py` 多檢查這一個檔案。靜態入口 `dist/tropical/index.html` 與資料 `dist/data/tropical/…` 不同路徑，不衝突。
- 查詢參數：

| 參數 | 值 | 預設 |
|---|---|---|
| `storm` | `cyclone_id` | 沒有 → 顯示總覽 |
| `tab` | `overview`、`forecast`、`analysis`、`imagery` | `overview` |
| `cycle` | `YYYYMMDDHH` | 索引中最新的 cycle |

- 參數值一律先以正規表示式檢查再使用；不合格式就忽略。`storm` 不在索引中時回到總覽，並顯示「找不到這個系統，可能已結束或編號已變更」。
- `App.jsx` 新增一條 `/tropical` 路由，頁面元件以 `React.lazy` 載入，Leaflet 與海岸線資料不進入首頁的 bundle。導覽列加一個連結。**現有路由與頁面不動**；`image-types.js` 不加入颱風（那是圖資頁的清單，也是 `pages-build` 產生圖資入口的依據）。
- 選項與取捨：hash 路由（`/tropical#/storm/…`）也只需要一個入口，但與全站的 `BrowserRouter` 風格不一致；每個系統一個路徑則無法預先產生靜態入口（plan 2.6）。

### 7.2 地圖套件與底圖 [已決定：Leaflet＋隨站海岸線]

- 套件：`leaflet`（1.9.x，BSD-2-Clause），**直接使用，不加 `react-leaflet`**。理由：`react-leaflet` 採用 Hippocratic License，不是常見的開源授權，避開；直接用 Leaflet 只需要一個 `useEffect` 管理地圖實例，程式量不大。
- 繪圖：`preferCanvas: true`。Spaghetti 最多約 200 條線、每條數十點，Canvas 繪製足夠；逐成員建立 SVG 節點會拖慢互動。
- 底圖：**不使用任何外部圖磚**。隨站打包 Natural Earth 的陸地多邊形（公有領域），裁切到約東經 80° 至西經 140°、南緯 10° 至北緯 65°，簡化後存成 GeoJSON。
  - 大小估計約 150–400 KB **[估計，S7 實測]**；隨地圖元件延遲載入。
  - 資料檔在 S7 以一次性的工具產生後提交進版控，並記錄來源版本與處理步驟。處理工具不成為專案的相依套件。
  - 解析度的選擇（1:50m 或 1:110m）留給 S7，以臺灣、琉球、菲律賓的輪廓是否可辨識為準。
- 另畫經緯線與主要地名標示（少量，寫在前端）。
- 選項：d3-geo 純 SVG 較輕、投影可任意旋轉，但縮放、拖曳、點選都要自己寫；MapLibre 功能最強但體積大且偏向圖磚。

### 7.3 跨 180° 經線

- 資料檔的經度是 -180 至 180（1.2）。**前端在繪圖前把所有經度展開到 0–360**：`lon < 0` 時加 360。西北太平洋與中太平洋的系統都落在約 100–220 的連續區間，路徑越過 180° 時不會被拉成橫跨整張地圖的線。
- Leaflet 接受超出 ±180 的經度，會照數值連續繪製。底圖 GeoJSON 在產生時就以同一個 0–360 的慣例輸出。
- 地圖中心約東經 140°，可拖曳範圍限制在約東經 80° 至 220°（即西經 140°）。
- 展開的規則集中在一個函式，並有單元測試（輸入 179.5、-179.5、-171.3 等）。顯示給使用者的經度仍換回東經／西經。
- V1 只涵蓋西北太平洋，不處理路徑向西越過 0° 或環繞地球的情況。

### 7.4 按需載入

| 時機 | 讀取 |
|---|---|
| 進入 `/tropical` | `tropical/official/index.json` |
| 選定系統 | 該系統的 `analysis.json`、`forecast.json` |
| 開啟 Forecast 分頁 | `tropical/models/index.json`；所選 cycle 的確定性檔（預設最新）|
| 勾選某個 Ensemble 圖層 | `tropical/ensemble/index.json`（第一次）；該 cycle、該模式的 Ensemble 檔 |
| 切換 cycle | 新 cycle 的確定性檔；已勾選的 Ensemble 重新讀取對應的檔 |

- 沿用 `api.js` 的 `readStatic`（`cache: "no-cache"`，由瀏覽器做條件式請求）。同一個頁面生命週期內，已讀過的 cycle 檔與 Ensemble 檔留在記憶體，不重複請求。
- 每個讀取各自處理失敗：某個 Ensemble 檔 404 只影響那個圖層（顯示「此資料暫時無法取得」），不影響其他圖層與官方路徑。索引列出但檔案不存在是可能發生的（4.1 不做跨檔檢查），前端必須容忍。
- 讀到的 JSON 先做最基本的形狀檢查（`schema_version`、`cyclone_id` 與請求一致），不合就當成讀取失敗。

### 7.5 顯示原則（由 plan 1.3 與來源條款推得，S5／S7／S10 遵守）

- **時間軸**：以 `valid_time` 對齊。某條路徑在所選時刻沒有節點就不顯示該點，**不插值**。
- **起報時間**：每個圖層標示自己的 `init_time`；官方路徑另標 `issued_at`。
- **強度**：每個數值都帶機構與平均期間（「JTWC，1 分鐘平均」）。Analysis 分頁並列三家，不排序、不平均、不標示「最強／最弱」。
- **Ensemble**：說明文字固定寫明「各成員路徑的分散程度不等於官方機率；外圍範圍不是官方預報範圍」。不畫包絡線、不計算機率。
- **模式路徑**：圖例標示「數值模式原始輸出，非官方預報」。
- **機率圓**（JMA、CWA）與**風圈**（官方）分開圖層、分開圖例。
- **未配對或同名的系統**：顯示提示（2.3）。
- **`past_track_origin: "accumulated"`**：標示「僅含本站開始觀察後的紀錄」。
- **時區**：資料是 UTC；畫面同時顯示 UTC 與臺灣時間。

### 7.6 署名區塊

署名文字是前端的固定內容（不放在每個 JSON 裡），在 `/tropical` 頁尾固定顯示，並在各分頁的資料旁以短標註指向它。**S11 定稿時必須逐字對照 `.runtime/tc-source-verification/terms/` 與 `s2/out/terms/` 的條款原文**；下表是必須涵蓋的要點，不是定稿文字。

| 來源 | 必須包含 | 依據 |
|---|---|---|
| JTWC | 本頁含 JTWC 資料，該資料不受著作權保護（17 U.S.C. §403）；JTWC 產品主要供美國政府機關使用，一般使用者應以本國氣象機關與 RSMC 為準（臺灣以 CWA 為準）；本站未修改其內容後宣稱著作權 | [官方文件，S1] |
| NOAA／NWS | 本頁含 NWS 資料，該資料不受著作權保護（17 U.S.C. §403）；非 NOAA／NWS 背書；經本站轉換格式與篩選，**不是官方資料的原樣呈現** | [官方文件，S2] |
| JMA | `出典：気象庁ホームページ` 加上網址；本站的路徑圖與表格另註明是加工作成（`…を加工して作成` 的句型）；不得讓人誤以為是日本政府製作 | [官方文件，S1] |
| CWA | 依平臺「顯名聲明」：提供機關「交通部中央氣象署」、資料名稱、授權條款名稱 | [官方文件，S1]；資料集的正式名稱 S11 由平臺頁面取得 |
| ECMWF | 條款指定的署名句（含「…based on data and products of the European Centre for Medium-Range Weather Forecasts (ECMWF)」）、著作權聲明、CC BY 4.0 授權聲明、免責聲明、**已經修改的說明**（格式轉換、只保留西北太平洋已識別系統、只保留路徑欄位）| [官方文件，S2]。完整原句 S11 自條款原文複製，本文件不重寫 |
| Natural Earth | 底圖來源（公有領域，非必要但建議標示）| |

- ECMWF 要求時須移除署名 [官方文件]：署名集中在一處，方便調整。
- CWA 官網圖片（非開放平臺資料）的條款沒有個別查證 [S1]：S11 若外連 CWA 路徑圖，沿用現有 13 項圖資的外連做法，並維持這個限制的紀錄。

### 7.7 日本氣象業務法的評估

問題：氣象業務法第 17 條規定，從事「予報業務」需經許可 [官方文件，S1]。本站在 JMA 官方預報旁顯示數值模式路徑，是否構成需要許可的預報行為？

**評估（不是法律意見）**
- 本站不產生預報：不插值、不計算共識或平均路徑、不計算侵襲機率、不對模式輸出做任何判斷或修正，只是把 NOAA 與 ECMWF 公開發布的追蹤結果轉換格式後顯示。
- 本站不以 JMA 的名義發布任何內容；JMA 的資料只原樣轉載並標示出典與加工。
- 本站是在日本境外營運的非商業網站。
- 依以上三點，判斷**風險低**。

**對應的設計約束（即使風險低也照做）**
1. 模式路徑與官方路徑分開圖層、分開圖例，預設顯示官方路徑；模式圖例固定標示「數值模式原始輸出，非官方預報，亦非本站預報」。
2. 不取用、也不自行計算平均路徑（`aemn`、`aimn` 不抓；不畫 Ensemble 平均）。
3. 不對日本境內地點提供任何本站推導的到達時間或影響判斷。
4. 頁面說明不使用「預測」「本站預報」等字眼描述模式圖層。

**結論**：該法是否適用於境外、非商業、單純轉載模式輸出的網站，本階段沒有取得權威解釋，標為 **[待驗證]**。若使用者不接受這個風險，退路是以建置時的設定關閉模式與 Ensemble 圖層（資料契約不變，前端不載入），只顯示三個機構的官方路徑。見第 13 節 F。

---

## 8. 新增相依套件

| 套件 | 版本 | 加入階段 | 用途 | 授權 | 理由與風險 |
|---|---|---|---|---|---|
| `pybufrkit`（Python）| 鎖定 `==0.2.25` | S8 | 解碼 ECMWF 熱帶氣旋 BUFR | MIT | 純 Python；Actions 上安裝 4.0 秒、30 MB [實測，10a]；已用真實樣本與 ecCodes 抽樣比對（成員編號範圍、第 1 個 subset 的前 6 個緯度、8 個識別碼）一致 [實測]，**不是逐值全面比對**；S8 的測試要補上對位置、氣壓、風速的逐值檢查。只有 sdist、沒有 wheel；維護狀況未查證。鎖定版本以免相依變動影響每輪都跑的測試 |
| `bitstring`（Python）| `>=3.1.9,<4` | S8 | `pybufrkit` 的相依 | MIT | 搭配 5.0.0 會在解碼時出錯 [實測]，必須限制在 4 以下。會連帶安裝 `six` |
| `leaflet`（前端）| `^1.9.4` | S7 | 互動地圖 | BSD-2-Clause | 見 7.2 |

**不新增的套件與理由**
- `eccodes`：解碼較快，但 Linux 上佔 391 MB、帶入 numpy 等多個套件 [實測，10a]。列為 `pybufrkit` 無法使用時的備案。
- `pdbufr`：是 `eccodes` 上的包裝，還多帶 pandas [source-matrix 第 8 節]。
- `react-leaflet`：授權非常規（7.2）。
- `defusedxml`：不加。JMA XML 與 JTWC RSS 用標準函式庫解析；解析前以位元組搜尋拒絕含 `<!DOCTYPE` 或 `<!ENTITY` 的文件，並受 `http_client` 的 16 MB 回應上限保護。這兩個來源的正常文件都不含 DTD [實測：S1／S3 樣本]。
- XML、RSS、ATCF 文字、tcvitals 的解析都只用標準函式庫。

**影響**
- `pybufrkit` 必須加入 `fetchers/requirements.txt`（不是只加在開發用清單）：發布流程每輪都跑完整測試，測試會匯入解析模組。每輪安裝時間增加約 3 秒 [實測，10a]。
- `pybufrkit` 的備案切換條件：在 `ubuntu-latest`（已遷移到 Ubuntu 26 [HANDOFF]）或日後的 Python 版本上安裝或解碼失敗。解碼模組對外只提供一個函式（輸入位元組、輸出中性的資料結構），切換套件時其他程式不用改。
- S4–S7 不新增任何 Python 套件。

---

## 9. 測試策略

### 9.1 測試資料來源

| 類別 | 來源 | 用於 |
|---|---|---|
| 真實樣本 | `.runtime/tc-source-verification/`（S1、S2、S3）已保存的 CEMPAKA 與 PENA 回應 | 解析器的主要測試；配對（`38W`→`31W` 的兩個 ECMWF 確定性檔；`WP31` 對 JTWC 31W）；最終報（JMA 消滅電文、JTWC Final Warning 的 RSS 與 `.tcw`）；越線預報（`cp0426.tcw`）|
| 人工構造 | 依真實樣本的格式手寫 | 無系統（各來源）、命名前的 TD、兩個鄰近系統、CP 系統越線後、成員缺漏、殘留的舊分析、壞格式、超過上限 |

**把真實樣本放進版控** [建議，第 13 節 E]
- 位置：`fetchers/tests/fixtures/tropical/`，附 `README.md` 記錄每個檔的來源網址、取得時間、是否經過裁剪，以及各來源的署名。
- 授權依據：JTWC 與 NOAA 為公有領域；JMA、CWA、ECMWF 的條款允許再散布，需署名 [官方文件]。
- 放入前逐檔檢查：
  - **NOMADS 的 403 回應本體含請求端 IP，不得放入** [HANDOFF]。要測 403 就用人工構造的本體。
  - CWA 的回應不得含金鑰；放入前以搜尋確認。
  - 檔案盡量小：文字類全部放；BUFR 放 2–3 個確定性檔（各 10–37 KB）與**一個**最小的 Ensemble 檔（約 0.3 MB）。
- Ensemble BUFR 無法簡單裁剪。解碼之後的邏輯（篩選、配對、輸出）改用解碼後的中性資料結構當測試輸入，這部分可以手寫，不需要大檔。
- 無系統時的真實回應目前沒有（[待驗證]）。相關測試用人工構造，並在測試名稱與 HANDOFF 標明「未經真實無系統回應驗證」。日後取得真實樣本時補上。

### 9.2 阻網

- 現有測試用 `unittest discover`，沒有全域的阻網機制。颱風測試**不依賴全域設定**：
  1. 每個服務都接受注入的傳輸函式（比照 `http_client.HttpPolicy.get` 的 `transport` 參數）。測試一律注入假的傳輸函式，由網址對應到 fixture。
  2. 颱風測試模組在 `setUpModule` 把 `requests.sessions.Session.request` 換成會直接拋出例外的函式，`tearDownModule` 還原。任何漏掉注入的程式路徑會立刻讓測試失敗，而不是悄悄連網。
- 間隔等待（1 秒）與重試等待用可注入的等待函式，測試中不實際等待。
- 假的傳輸函式遇到沒有登錄的網址要拋出例外（確保程式沒有發出設計以外的請求，例如列目錄或抓 HTML）。

### 9.3 與時間無關

- 所有判定函式（活躍、過期、保留期、預期發布時間、放棄時間、cycle 選擇）都以參數接收「現在」，內部不呼叫 `datetime.now()`。只有最外層的入口讀時鐘。
- 測試使用與 fixture 相符的固定時刻（例如 `2026-11-11T10:30:00Z`）。
- 必須涵蓋的時間邊界：跨日（NOMADS 的日期目錄）、跨月、跨年（季別不變、12 月 31 日 18Z 的 cycle）、臺灣時間午夜前後（11/9 曾因午夜假設出錯擋住發布 [plan 2.3]）、門檻的兩側各一筆。
- 測試不得依賴執行當下有沒有颱風、執行的日期或時區。CI 上以不同的 `TZ` 執行結果相同（所有時間都是帶時區的 UTC）。

### 9.4 各階段必須有的測試

| 階段 | 測試 |
|---|---|
| S4 | 各來源：成功有系統、成功無系統、失敗（403、404、逾時、5xx、壞格式）；五種整體狀態的判定表；金鑰不出現在任何輸出；驗證器接受合法檔、拒絕每一種違規；**舊快照（無颱風檔）恢復、封裝、驗證都通過**；`deployment_decision` 的組合表（5.5）；颱風任務失敗時 13 項圖資的檔案與排程狀態不變；任務集合改變造成的狀態重置；**獨立 `http_scope`**：外層來源已用完預算或已 `blocked` 時颱風任務仍可請求，颱風任務用完預算或 `blocked` 後外層的狀態不變；驗證器對畸形輸入只丟 `ValueError`；JMA 判定表的每一列；不活躍的殘留資料不鑄造新系統（含第一次執行）；來源失敗時沿用前一次的 `active` 與 72 小時上限；經度 180 的正規化 |
| S5 | 五種狀態的畫面；讀檔失敗；`pages-build` 與 `verify_pages_build` 的新入口；查詢參數的檢查 |
| S6 | 配對：延續、名稱、位置（含不合併的案例）、同名不同系統、單一機構缺席、CP 系統越線；結束與保留期；清除步驟（只刪索引未列出的檔、索引無效時不刪、`pruned_tropical` 與 `expected`）；過去路徑的累積與上限 |
| S7 | 經度展開函式；圖層開關；時間軸不插值；真實瀏覽器驗證（AGENTS.md 第 5 條：元件測試不能當成瀏覽器驗證）|
| S8 | ATCF 解析（多行合併、追丟、其他洋區略過）；BUFR 解碼與 70 號以上的過濾、殘留舊分析的過濾；未發布（403／404）不算失敗；預期發布時間與放棄時間；精簡格式不被改寫成縮排格式；`http_client` 新增來源上限後，現有來源的上限測試結果不變 |
| S9 | 成員缺漏與補抓；探測控制檔；時間上限中斷後續接；結構上限與位元組上限；實測快照大小與單輪執行時間 |
| S10 | 按需載入（未勾選不請求）；單一檔 404 不影響其他圖層；成員數顯示 |

- 每個階段都依 AGENTS.md 交給未參與實作的獨立 Sub-Agent 審查與測試。
- 真來源的本機測試（各階段完成條件所要求的）只寫入 `.runtime`，不寫入 `frontend/public/data/`。

---

## 10. S1／S2 發現的逐項對策

| # | 發現 | 對策所在 |
|---|---|---|
| 1 | ATCF 用 JTWC 編號且沒有名稱；JMA、CWA 只有名稱與各自編號；ECMWF 編號不可信；tcvitals 可橋接；命名前沒有共通鍵；plan 的「優先用編號」需修正 | 2.1、2.3、2.4 |
| 2 | 中太平洋系統越線後仍是 `CP` 編號 | 3.1（以位置判斷）、2.4（`CP` 轉成 `04C` 配對）、1.3（`origin_basin`）|
| 3 | ECMWF 檔案含大量 70 號以上的系統；已命名系統不一定每個 cycle 都出現；消散後殘留舊分析；不能用「是否出現在檔案」判斷活躍 | 2.4（過濾、殘留檢查、缺席不代表消散）；3.2（活躍只由官方來源判定）|
| 4 | 「未發布」與「不存在」的回應不一致（JTWC 403；NOMADS 403／404；ECMWF 404），都不能當成沒有颱風 | 3.3（一律 `failed`）；5.4（模式的 403／404 是「尚未取得」，不是失敗也不是無系統）|
| 5 | NOMADS 目錄清單在 Actions 上失敗；GEFS、AIGEFS 各 31 個成員檔，每 cycle 約 62 次請求 | 5.4（以已知檔名請求、先探測控制檔、間隔 1 秒、專屬預算、時間上限）|
| 6 | NOMADS 只保留兩個日期目錄；ECMWF 保留約 12 個 run | 5.4（放棄時間 24／48 小時；每小時檢查，補抓窗口以約一天設計）|
| 7 | 大小是現有快照的 6–39 倍 | 第 6 節（只存路徑、Ensemble 2 個 cycle、精簡格式、結構與位元組上限、整體 4 MB）；1.2（精簡輸出）；5.2 第 3 點（防止被改寫成縮排格式）|
| 8 | 強度不可直接比較；時間各用 UTC、JST、+08:00 | 1.2（風速物件、一律 UTC）；7.5（顯示原則）|
| 9 | JTWC：只抓 RSS 與產品檔；以 RSS 連結為準；RSS 與產品在不同網域 | 5.3（JTWC）|
| 10 | JMA：`extra.xml` 只保證 10 分鐘，需搭配長期 feed；只轉載不產生預報；氣象業務法 | 5.3（JMA）；7.7 |
| 11 | CWA：用 datastore、不用 fileapi；金鑰遮蔽 | 5.3（CWA）；1.2（網址欄位）|
| 12 | 各來源的署名要求 | 7.6 |
| 13 | JTWC 目前連得上，但設計須允許缺席並顯示 PARTIAL | 3.3（JTWC 非必要、缺席時 `PARTIAL` 或 `OK_NO_STORMS`）；2.4（`ids.jtwc` 由 tcvitals 橋接）；5.3（轉址或阻擋都只讓 JTWC `failed`）|

讀現有程式後追加的限制：

| # | 限制 | 對策所在 |
|---|---|---|
| A | 任務與 `images/{kind}/latest.json` 綁定 | 1.1、5.2 |
| B | 更新函式不能刪檔 | 3.6 |
| C | `image_url`、`source_url` 是有副作用的鍵名 | 1.2（保留欄位名）|
| D | 只有 `fetched_at` 等四個欄位不計入內容識別；只改這些欄位的重寫會被丟棄 | 1.2（時間）；1.3（心跳）|
| E | 非 CWA 來源每輪 80 次／90 秒；時間窗從該來源本輪第一個請求起算；同一輪所有任務共用；`blocked` 會持續到該輪結束 | 5.4（獨立的 `http_scope`、NOAA／ECMWF 專屬上限）|
| F | 排在最後的颱風任務會因現有圖資先用掉 CWA／JMA 的時間窗而失敗 | 5.4、5.5（獨立的 `http_scope`）|
| G | 任務集合改變會重置排程狀態（連帶清空 history 缺口狀態；`cloud_snapshots` 也會拒絕舊狀態）| 5.1、4.3 |
| K | 驗證器漏出非 `ValueError` 的例外會讓整輪中斷 | 4.1 |
| L | `update_image` 對未知名稱丟 `KeyError`；測試寫死 13 項任務；`pruned_history` 的筆數被測試斷言 | 4.3、3.6 |
| H | `deployment_decision` 的「全部失敗」判斷會被颱風任務影響 | 5.5 |
| I | 通過驗證的檔案會被 `atomic_write_json` 以縮排格式重寫 | 5.2 第 3 點 |
| J | 舊程式讀不了含颱風檔的新快照 | 4.2 |

---

## 11. 各階段的修改範圍摘要

| 階段 | 後端 | 前端 |
|---|---|---|
| S4 | 官方服務（三個來源的索引部分）；`tropical/official/index.json` 的白名單與驗證器；`belongs`、`checked_update`、`deployment_decision` 的規則；`http_client.source_name` 加 `jtwc`；`due-intervals.json` 加 `tropical_official` | — |
| S5 | — | `/tropical` 路由與靜態入口；總覽與五種狀態；Dashboard 入口 |
| S6 | `analysis.json`、`forecast.json`；配對；結束與保留；清除步驟 | — |
| S7 | — | Leaflet 與底圖；個別系統頁；官方路徑、時間軸、Analysis |
| S8 | 確定性模式（ATCF 與 BUFR）；`pybufrkit`；精簡寫入；`http_client` 的 `noaa`、`ecmwf` 上限；`tropical_models` | 模式圖層 |
| S9 | Ensemble；`tropical_ensemble`；大小與時間實測 | — |
| S10 | — | Spaghetti、cycle 選擇、按需載入 |
| S11 | （若需要）`graphic_url` 的擴充 | Imagery、站內串接、署名定稿 |

plan 的 S8 寫「若 ECMWF 確定性產品可用且套件可行，一併加入」：本設計確認可行，`pybufrkit` 在 S8 加入。若 S8 額度不足，可先只做 NOAA 的兩個模式（不需要新套件），ECMWF 的兩個確定性模式併入 S9。

---

## 12. 假設、[待驗證] 與退路

設計**沒有**把以下任何一項當成事實；每一項都有不成立時的行為。

| # | 假設或未驗證事項 | 設計如何依賴 | 不成立時的退路 |
|---|---|---|---|
| 1 | CWA 無颱風時的回應長相 [待驗證] | 只接受「陣列存在且為空或全部過期」為無系統 | 其他長相判為 `parse_error` → CWA `failed` → 整體 `PARTIAL`，不會誤報無颱風。取得真實回應後再把該長相加入接受清單 |
| 2 | JMA `targetTc.json` 無系統時為空陣列 [待驗證]；`category` 除 `LOW` 外都表示仍在追蹤 [假設] | 當作活躍清單的交叉檢查 | 長相不符就只靠 feed：`extra.xml` 涵蓋足夠就判 `ok`，不足就補抓長期 feed；補抓也失敗 → JMA `failed` → `PARTIAL`（3.3 的判定表）|
| 3 | JTWC 整個西北太平洋無系統時 RSS 項目的寫法（只在南半球項目實測到）[待驗證] | 以固定句子判斷無系統 | 文字不符且沒有任何系統連結 → `parse_error` → JTWC `failed`。JTWC 非必要，不影響 `OK_NO_STORMS` 的判定 |
| 4 | CWA 沒有結束標記；CWA 回應是否有獨立的發布時間欄位 [待驗證] | 只用過期門檻判斷 CWA 不活躍；`issued_at` 可退回分析時刻 | 門檻（15 小時）到了自然結束。S4 檢視真實樣本後若發現結束標記（如 `StateTransfer`）再加入 |
| 5 | JMA 是否對熱帶低氣壓發布 VPTW60、接近日本時是否加密發布 [待驗證] | 有電文就處理。`targetTc.json` 列出系統、卻拿不到它的電文時，JMA 判為 `failed`（3.3 判定表第三列）| 結果是該期間顯示 `PARTIAL`，不會誤報無颱風；系統由其他機構成立。若證實 JMA 不為某類系統發電文，再評估改契約。加密發布時每次最多處理 12 則、每個系統只採用最新一則 |
| 5a | JMA 結束標記只有一個樣本（變性為溫帶低氣壓）；減弱為熱帶低氣壓時的 `Remark` 與 `TyphoonClass` 寫法 [待驗證] | 只以 `TyphoonClass` 為 `温帯低気圧(LOW)` 判定結束 | 其他結束形式靠 9 小時過期門檻；未知的 `TyphoonClass` 視為活躍並記錄 |
| 5b | JMA、CWA 只發布西北太平洋的系統 [假設] | 3.1 全部納入 | 以位置範圍再檢查一次，範圍外的不納入 |
| 5c | tcvitals 與 JTWC 對未命名系統的名稱欄寫法 [待驗證] | 未命名系統不做橋接，直接用位置配對 | — |
| 6 | VPTW61 的內容 [待驗證] | 忽略 | 不影響 |
| 7 | ECMWF 70 號界線的官方定義 [待驗證] | 過濾條件之一 | 另有不依賴 70 的條件（名稱等於編號且無分析位置）；而且模式路徑必須對到官方系統才會輸出，漏濾的生成系統也不會顯示 |
| 8 | ECMWF 殘留舊分析的成因 [待驗證] | 以「沒有預報步」過濾 | 若殘留形式不同（有預報步但位置不動），名稱配對的 500 km 距離檢查會擋下；系統 `ended` 後也不再為它抓模式 |
| 9 | `ensembleForecastType` 的意義；`ac00`／`a000` 是否為控制成員；AIFS 第 51、52 號成員的身分 [待驗證] | 不依賴。原樣保存代碼，不標示「控制」 | 日後查明再由前端加標示，契約不用改 |
| 10 | AIFS 的 tf 產品是否為正式支援 [待驗證] | 當成可能缺席的模式 | 404 → 該 cycle 沒有 AIFS，其他模式不受影響 |
| 11 | 各 NOAA 模式追蹤器的時效上限 [待驗證] | 結構上限取 480 小時、81 點（高於實測最長的 240 小時）| 超過 → 驗證失敗 → 該檔不寫入並記錄；再調整上限 |
| 12 | NOMADS 舊目錄的刪除時點；正式的請求頻率上限 [待驗證] | 放棄時間 24 小時；每小時檢查；間隔 1 秒 | 被限流（429）時 `http_client` 放棄該來源本輪，該來源記為 `failed`；任務只有在兩個來源都失敗時才進入重試退避，否則下一個小時再試。持續被限流就拉長任務間隔或成員檔之間的間隔 |
| 12a | 現有每輪 `build` job 的實際耗時 [待驗證] | 5.4 的時間餘裕 | S4 開始前先量；不足時優先縮短 Ensemble 的時間上限 |
| 13 | 全球都沒有系統時 ATCF 檔與 ECMWF tf 檔的狀況 [待驗證] | 不依賴：沒有活躍系統時根本不請求模式檔 | — |
| 14 | 位置配對的距離與時間門檻 [初值] | 2.3、2.4 | 門檻偏嚴 → 該合併的沒合併（並列兩筆，有提示）；偏鬆 → 以「必須唯一」的條件防止錯併。S6 以真實與構造案例校正 |
| 15 | 各機構的過期門檻、STALE 門檻、最早等待時間 [初值] | 3.2、3.4、5.4 | 都是設定值，調整不影響契約 |
| 16 | Ensemble 檔在 Actions 上的解碼時間；現有每輪的實際耗時 [待驗證] | 估計新增 2–3 分鐘 | S9 實測。不足時降低 Ensemble 任務的時間上限，分多輪補齊 |
| 17 | JTWC 個別系統產品（`.tcw`）從 Actions 的可達性 [待驗證，10a 只測了 RSS 與展望] | JTWC 的分析與預報來自 `.tcw` | 取不到 → JTWC `failed` → `PARTIAL`；`ids.jtwc` 改由 tcvitals 橋接 |
| 18 | 建議的 UA 字串能通過 JTWC、NOMADS 等來源 [待驗證] | 5.7 | 改用 requests 預設 UA（有實測紀錄）。不變換 UA 繞過阻擋 |
| 19 | JTWC `.tcw` 的 `issued_at` 可由第一行日時組加上第二行時間戳的年月推得 [假設；跨月時（第二行是月底、第一行是次月 1 日）要以「最接近第二行時間戳的那個月」處理] | 1.4 | 改取 RSS 的發布文字（`Issued at 11/1500Z`）；兩者都失敗則該筆視為解析失敗。不以「分析時刻加 3 小時」推測 |
| 20 | JMA、CWA 風圈的門檻數值（30／50 kt；15／25 m/s）[待驗證] | `radii[].threshold` | S6 由官方文件確認後才寫入；確認不了就把 `threshold` 改為只存機構原文的名稱，不存數值（屆時契約以新 `schema_version` 處理，或在 S6 上線前直接修正本文件）|
| 21 | 日本氣象業務法是否適用 [待驗證] | 7.7 | 以設定關閉模式圖層 |
| 22 | GitHub Pages 以 gzip 傳送 JSON；ZIP 壓縮率與 gzip 相近 [估計] | 6.3 的下載量與保存量 | 只影響效能估計，不影響正確性。S9 實測 |
| 23 | 底圖 GeoJSON 的大小 [估計] | 7.2 | 過大就改用較粗的解析度或縮小裁切範圍 |
| 24 | 長期穩定性：所有來源的可達性都只有單日、單次的實測 | 整體 | 每個來源都可以獨立失敗而不影響其他來源與現有圖資；S12 的線上觀察負責發現 |

---

## 13. 需要使用者決定的事項

前十項已於 2026-11-12 確認（0.2）。以下是撰寫設計時新產生的決定。

> **2026-11-13：使用者確認 A–K 全部採用「建議」欄的方案。** 文中標為 [建議] 並指向本節的項目，自此視為 [已決定]。其中 F（日本氣象業務法）是使用者接受「低風險」的評估並同意照 7.7 的四項約束實作，法律上是否適用仍是 [待驗證]。

| # | 事項 | 建議 | 替代方案 | 影響 |
|---|---|---|---|---|
| A | `cyclone_id` 的格式 | 以機構編號鑄造（`2026-jma-tc2638`），由前一次索引延續 | 以名稱為 ID（命名時 ID 會變）| 2.2；網址的可讀性 |
| B | 結束的系統保留多久 | `ended_at` 後 48 小時 | 立即移除；24 小時；72 小時 | 3.5；淡季前最後一個系統的資料多留兩天 |
| C | 索引的心跳欄位 `last_ok_at` | 採用（語意欄位，每次成功檢查都更新）| 不採用；前端不顯示 STALE | 1.3、3.4。採用後每 30 分鐘多一次內容變更，偏離現有「檢查時間不算內容」的原則 |
| D | User-Agent 字串 | `weather-integration-static/1.0 (tropical cyclone data fetcher)`，不含聯絡方式 | 加上專案網址或聯絡信箱（會把專案身分送給外部服務，需要你明確同意）；或沿用 requests 預設值 | 5.7 |
| E | 真實樣本是否放進版控 | 放（裁剪後，附來源與署名，排除含 IP 的回應）| 不放；測試全部用人工構造的資料 | 9.1。不放的話，解析器與真實格式的一致性只能靠本機的 `.runtime` 樣本驗證 |
| F | 日本氣象業務法的風險 | 接受「低風險」的評估，照 7.7 的四項約束實作 | 關閉模式與 Ensemble 圖層；或先諮詢專業意見 | 7.7；影響 S8–S10 是否進行 |
| G | 三個任務、三個前綴的切法 | 採用（1.1 選項 A）| 單一任務 | 1.1、5.1；決定 S4 對 `due_refresh` 的修改方式 |
| H | JMA 的過去路徑 | 由本站累積（只含開始觀察後的紀錄）| 使用 bosai JSON 的路徑陣列（完整但沒有時間戳、沒有官方文件）| 1.4 |
| I | 命名前各自成立的兩筆系統，命名後是否自動合併 | V1 不自動合併，並列並顯示提示 | 自動合併（要處理 ID 改變與檔案搬移）| 2.3 |
| J | 颱風任務的請求預算是否與現有圖資分開計算 | 分開：每個颱風任務用自己的 `http_scope`（審查後新增）| 不分開，接受前面任務跑得久的那幾輪 CWA／JMA 請求失敗、顯示 `PARTIAL` | 5.4。分開後同一輪對 CWA、JMA 的總請求數會比現行上限多出颱風任務自己的用量（CWA 1 次、JMA 3–16 次）|
| K | 來源連續失敗多久後，把它持有的系統視為不活躍 | 72 小時（審查後新增）| 24 小時；或沿用一般的過期門檻（9–15 小時，但會把「抓不到」誤標成「已結束」）| 3.3。只有 JTWC 發報的系統，在 JTWC 連續失敗這段時間後會變成結束 |

---

## 14. 驗證紀錄

### 主代理（撰寫者）

- 讀過：`AGENTS.md`；`HANDOFF.md` 的 S2 與 S2 補測兩節；`plan.md` 全文；`source-matrix.md` 全文；`snapshots.py`、`due_refresh.py`、`scheduling.py`、`snapshot_runner.py`、`http_client.py`、`content_versions.py`、`pages_package.py`、`verify_pages_build.py`、`due-intervals.json`、`due-runtime.json`、`pages-build.mjs`、`App.jsx`、`api.js`、`package.json`、兩個 requirements 檔。
- 只以搜尋片段檢視、沒有通讀：`publication.py`（確認 `atomic_write_json` 的格式）、`refresh_pages.py`、`update_runner.py`、兩個 workflow（確認逾時、排程、測試指令）、`rainfall_observation_service.py`（確認金鑰以 `params` 傳入）。
- **沒有讀**：`history_reconciliation.py`、`current_day.py`、`local_updater.py`、`chain_controller.py`、各現有 service、所有測試檔、前端各頁面元件。5.2 對 `history_due` 與本機入口的敘述因此寫成「S4 要確認」。
- S3 補測：14 次請求（0.3）。腳本在 `.runtime/tc-source-verification/s3/scripts/`，回應在 `s3/raw/`，輸出紀錄在 `s3/*.log`。
- 沒有執行任何專案測試（S3 沒有修改程式）。沒有讀取 `.env`。沒有複製或執行 Pillar 的程式；本文件沒有新增向 Pillar 借用的概念（沿用 `source-matrix.md` 第 11 節已列者）。

### 獨立 Sub-Agent

**第一輪審查（2026-11-13，未參與撰寫；完全唯讀，沒有發出外部請求）**

做了什麼：
- 通讀 `AGENTS.md`、`plan.md`、`source-matrix.md`、本文件，以及 `snapshots.py`、`due_refresh.py`、`scheduling.py`、`snapshot_runner.py`、`http_client.py`、`content_versions.py`、`pages_package.py`、`publication.py`、`history_reconciliation.py`、`cloud_snapshots.py`、`verify_pages_build.py`、`refresh_pages.py`、`update_images.py`、兩個 policy 檔、`pages-build.mjs`、`App.jsx`、`api.js`、`image-types.js`、`weather-relay.yml`。
- 片段檢視 `pages-manual.yml`（第 80–214 行）、`tests/test_scheduling.py`（前 60 行）、`pages_refresh.py`、`chain_controller.py`、各 service 的主機與 `params` 用法。
- 以自寫腳本（`python -I`，放在暫存目錄）核對 S3 樣本：重數 `extra.xml`、`extra_l.xml` 的筆數與 VPTW 種類；讀兩個 `.tcw` 的開頭；逐字比對 `targetTc.json`、RSS、JMA 最終報。另以標準函式庫重現 `canonical_url(None)` 的行為。
- 重算第 6.3 節的大小數字（89、229、490 KB、2.2 MB）。

沒做什麼：
- 沒有讀 `current_day.py`、`update_runner.py`、`local_updater`、`update_snapshot.py`、`watch_images.py`、各 service 內文、前端頁面元件與前端測試、`pages-manual.yml` 其餘部分、`HANDOFF.md`。
- 沒有核對 `.runtime` 內的 S1／S2 樣本與條款原文（7.6 只對照 source-matrix 的摘要）；`s3/raw` 的 tcvitals、avno 原檔只看了主代理的 log。
- 沒有執行專案測試；7.7 的法律評估沒有查證。

確認無誤：0.3 節核對過的每一項；引用 source-matrix 的延遲、成員數、檔名規則、狀態碼、大小；對現有程式的敘述（`latest_name`、`belongs`、回復與還原機制、`pruned`／`expected`、任務集合重置、`deployment_decision`、`EXECUTION_FIELDS`、`images_in`、封裝上限、「新快照＋舊程式無法恢復」、`history_due` 對未知名稱回傳 False）；三個前綴可沿用現有回復機制；颱風資源未加入 `REQUIRED`；plan 的九項與十三項發現都有對應。沒有找到會傷害現有 13 項圖資的路徑。

提出的問題與處理：

| 級別 | 問題 | 處理 |
|---|---|---|
| 阻擋 | 請求預算的時間窗從該來源本輪第一個請求起算，排在最後的颱風任務會因此失敗；`blocked` 會延續 | 每個颱風任務用獨立的 `http_scope`（5.2、5.4、5.5；第 13 節 J）|
| 阻擋 | 已移出索引的系統會被來源殘留的舊資料反覆鑄造成新系統 | 只有活躍的資料才能鑄造（2.2、2.3、3.5）|
| 阻擋 | 沒有活躍系統時把模式索引清空，與 `ended` 保留期矛盾；官方索引暫時無效會清掉全部模式資料 | 5.4 改為三種情況；`ended` 保留、官方索引無效時不改動（3.5、3.6、5.4）|
| 阻擋 | JMA 的來源狀態有未定義的組合，可能誤判 `OK_NO_STORMS`；3.3 與 5.3 不一致 | 3.3 新增 JMA 判定表；清單有系統卻拿不到電文時判 `failed` |
| 建議 | 模式沒有「已檢查、沒有這個系統」的紀錄，會每小時重抓 | 索引新增 `checked`、`match_basis`、`missing_files`（1.6、1.8、5.4）|
| 建議 | 持續的 403／404 會永遠被當成尚未發布；與第 12 節的敘述矛盾 | 新增逾期時間與任務層級成敗的定義（5.4、第 12 節第 12 項）|
| 建議 | `deployment_decision` 對策與內文不一致 | 5.5 改為明確的組合表 |
| 建議 | 連帶修改清單漏列模組與測試 | 4.1、4.3、5.1、5.2 補上 |
| 建議 | 單次執行上限寫錯工作流程 | 5.4 改為 `build` job 的 20 分鐘 |
| 建議 | JMA 以單一全域時間篩選電文會漏報 | 5.3 改為以網址去重 |
| 建議 | 來源失敗造成的過期被標成 `ended` | 3.2、3.3：失敗時沿用前值，72 小時上限（第 13 節 K）|
| 建議 | JMA 結束標記只來自一個樣本，可能與「TD 仍活躍」衝突 | 3.2 只看 `TyphoonClass`；第 12 節 5a |
| 建議 | tcvitals 橋接的歸屬不清 | 1.6 的 `bridge`、2.4、`match: "tcvitals"` |
| 建議 | 經度剛好 180.0 沒有明訂 | 1.2 |
| 建議 | 4 MB 整體上限沒有執行者 | 6.1 拆成三個前綴 |
| 輕微 | 共 14 項（`source_url` 的出錯位置、重寫條件、`bulletin` 範例、`issued_at` 推算、JMA／CWA 範圍的標記、UA 與 ecCodes 敘述略為擴大、ECMWF 四組路徑、`analysis.json` 大小、JTWC `.tcw` 全部成功的要求、`PARTIAL` 與 `STALE` 並存、`idle` 狀態、JMA 停滯的表示、JTWC 獨有系統的後果）| 全部納入對應章節 |

**複查**

同一位審查代理於 2026-11-13 複查（重讀修正後的全文，對照第一輪已讀的 `http_client.py`、`due_refresh.py`、`snapshot_runner.py`；這一輪沒有執行指令、沒有重開原始碼檔，也沒有核對 5.4 引用的 S2 檔名）。

- 結論：**4 項阻擋都已在內文實際解決，沒有新的阻擋問題**。巢狀 `http_scope` 的做法對照原始碼成立；5.5 的組合表七列逐列對照 `deployment_decision` 都正確。
- 11 項建議修正：10 項已解決，1 項（持續的 403／404）部分解決。14 項輕微：13 項已解決，1 項（`idle` 造成的內容變更）部分解決。
- 新提出 2 項建議修正與 6 項輕微，處理如下。**這些修正之後沒有再送複查**。

| 級別 | 問題 | 處理 |
|---|---|---|
| 建議 | 來源判為 `failed` 時，同一輪已成功取得的個別系統資料是否採用，沒有明訂 | 3.3：照常採用；`failed` 只表示不能斷定沒有其他系統 |
| 建議 | 來源 `ok` 但不再列出我方持有的系統時怎麼處理，沒有明訂 | 3.2：`active` 立刻設為 `false`，保留最後一筆資料 |
| 輕微 | `match_basis` 在系統結束時也會清空 `checked`；橋接取得編號卻不會 | 1.6：只在新增字串時清空；納入橋接的編號 |
| 輕微 | 逾期判定以來源為單位，單一產品停止提供會讓整個來源失敗 | 5.4：該來源已逾期的產品全部取不到才算失敗 |
| 輕微 | 兩個來源都失敗時，索引回復成舊檔，看不出異常 | 1.6：前端以最新 cycle 的新舊標示 |
| 輕微 | JMA 的 4 小時窗口在任務停擺後會漏掉最終報 | 5.3 步驟 4 新增條件 (c) |
| 輕微 | `official/` 超過上限且沒有可移除的系統時任務直接失敗 | 6.1：先截短 `past_track` |
| 輕微 | 文字出入（「四處」、`pruned` 清單）；第 10 節追加表的編號順序 | 前兩者已改；編號順序保留（K、L 為審查後新增）|
| 輕微 | `idle` 與 `ok` 切換造成內容變更 | 1.6 註明，不另外處理 |
