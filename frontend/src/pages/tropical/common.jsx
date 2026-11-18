// Shared pieces of the /tropical overview and storm pages (design.md 7.5, 7.6).
import { REQUIRED_AGENCIES } from "../../tropical/status";
import { MODEL_LAYERS_ENABLED } from "../../tropical/features";
import {
  AGENCY_LABELS, AGENCY_SHORT, formatDualTime, formatPosition, formatPressure, formatWind, textOrNull,
} from "../../tropical/format";

export function DualTime({ stamp, missing = "—" }) {
  const time = formatDualTime(stamp);
  if (!time) return <>{missing}</>;
  return (
    <span className="tc-time">
      <span>{time.utc}</span>
      <span>臺灣 {time.taipei}</span>
    </span>
  );
}

export const INTENSITY_NOTE = "強度不可跨機構比較：JTWC 為 1 分鐘平均風速，JMA 與 CWA 為 10 分鐘平均風速；"
  + "分類為各機構原文，未做對照。本頁不排序、不平均、不換算各機構的數值。";

/** @param models show the NOAA/ECMWF lines (design.md 7.6, 11f F9); follows the build switch. */
export function Attribution({ models = MODEL_LAYERS_ENABLED }) {
  return (
    <footer className="tc-attribution" aria-labelledby="tc-attribution-title">
      <h3 id="tc-attribution-title">資料來源與署名（暫定文字，正式版本待定稿）</h3>
      <ul>
        <li>
          <strong>JTWC：</strong>本頁含美國聯合颱風警報中心（JTWC）資料，該資料不受著作權保護（17 U.S.C. §403）。
          JTWC 產品主要供美國政府機關使用，一般使用者請以本國氣象機關與區域專業氣象中心的資訊為準（臺灣以中央氣象署為準）。
          本站未修改其內容後宣稱著作權。
        </li>
        <li>
          <strong>JMA：</strong>出典：気象庁ホームページ（
          <a href="https://www.jma.go.jp/" target="_blank" rel="noreferrer">https://www.jma.go.jp/</a>
          ）。本頁的表格與路徑圖是以氣象廳資料加工作成（気象庁のデータを加工して作成）；本站與日本政府無關，內容並非日本政府製作。
        </li>
        <li>
          <strong>CWA：</strong>提供機關：交通部中央氣象署；資料：颱風消息資料集 W-C0034-005（正式資料名稱待確認）；
          依「政府資料開放授權條款」使用。CWA 風速的平均期間依慣例視為 10 分鐘，尚未經官方文件確認。
        </li>
        {models ? (
          <>
            <li>
              <strong>NOAA／NWS（數值模式 GFS、AIGFS）：</strong>本頁含美國國家氣象局（NOAA／NWS）的熱帶氣旋追蹤資料，
              該資料不受著作權保護（17 U.S.C. §403）。本站與 NOAA／NWS 無關，亦未獲其背書；
              資料經本站轉換格式與篩選，不是官方資料的原樣呈現。
            </li>
            <li>
              <strong>ECMWF（數值模式 IFS、AIFS）：</strong>本頁的 IFS、AIFS 路徑以歐洲中期天氣預報中心的資料與產品為基礎
              （based on data and products of the European Centre for Medium-Range Weather Forecasts (ECMWF)），
              著作權屬 ECMWF，依 CC BY 4.0 授權使用。本站已修改原始資料：轉換格式、只保留西北太平洋已識別的系統、只保留路徑欄位。
              ECMWF 不對本站的內容負責。完整的署名、著作權與免責聲明原文待定稿。
            </li>
            <li>
              數值模式路徑是模式的原始輸出，非官方預報，亦非本站預報；模式風速是 10 m 最大風，沒有平均期間，不可與機構的強度比較。
            </li>
          </>
        ) : null}
        <li>
          <strong>底圖：</strong>陸地輪廓取自 Natural Earth（公有領域），經本站裁切與簡化。
        </li>
        <li>{INTENSITY_NOTE}</li>
      </ul>
    </footer>
  );
}

export function Banner({ display, index }) {
  if (display.state === "UNAVAILABLE") {
    return (
      <div className="tc-banner tc-banner-unavailable" role="alert">
        <strong>熱帶系統資料暫時無法取得</strong>
        <p>這不代表目前沒有熱帶系統，請稍後重新整理，或參考中央氣象署的颱風消息。</p>
      </div>
    );
  }
  const noActive = !display.hasActive;
  let detail;
  if (display.indexStatus === "PARTIAL") {
    detail = noActive
      ? "部分來源無法取得，無法確認是否有活躍系統。"
      : "部分來源無法取得：以下為取得成功的來源與先前保存的資料，可能不完整。";
  } else if (display.indexStatus === "OK_NO_STORMS") {
    detail = "目前無活躍熱帶系統。";
  } else {
    detail = "以下為各機構目前發報中的系統。";
  }

  if (display.state === "STALE") {
    const stale = display.staleSources;
    return (
      <div className="tc-banner tc-banner-stale" role="alert">
        <strong>資料可能已過期，目前狀況無法確認</strong>
        <ul className="tc-stale-list">
          {REQUIRED_AGENCIES.map(agency => (
            <li key={agency}>
              {AGENCY_SHORT[agency]} 最後確認時間：
              <DualTime stamp={index.sources[agency].last_ok_at} missing="尚無成功紀錄" />
              {stale.includes(agency) ? <span className="tc-flag">已過期</span> : null}
            </li>
          ))}
        </ul>
        <p>最後一次確認時的狀態：{display.indexStatus === "OK_NO_STORMS"
          ? "當時沒有活躍熱帶系統（已過期，不代表現在）。"
          : display.indexStatus === "OK_WITH_STORMS"
            ? "當時各機構發報中的系統如下（已過期，可能已有變化）。"
            : detail}</p>
      </div>
    );
  }
  const tone = display.state === "PARTIAL" ? "tc-banner-partial" : "tc-banner-ok";
  return (
    <div className={`tc-banner ${tone}`} role="status">
      <strong>{detail}</strong>
    </div>
  );
}

export function AgencySummary({ agency, summary, children = null }) {
  const position = formatPosition(summary.lat, summary.lon);
  const wind = formatWind(agency, summary.max_wind);
  const pressure = formatPressure(summary.pressure_hpa);
  const category = textOrNull(summary.category);
  return (
    <section className="tc-agency" aria-label={AGENCY_LABELS[agency]}>
      <h5>{AGENCY_LABELS[agency]}</h5>
      <dl>
        <dt>機構判定</dt>
        <dd>{summary.active === true ? "活躍" : summary.active === false ? "已不視為活躍" : "—"}</dd>
        <dt>分析時間</dt>
        <dd><DualTime stamp={summary.analysis_time} /></dd>
        <dt>位置</dt>
        <dd>{position || "—"}</dd>
        <dt>最大風速</dt>
        <dd>{wind || "—"}</dd>
        <dt>中心氣壓</dt>
        <dd>{pressure || "—"}</dd>
        {category ? <><dt>機構分類（原文）</dt><dd>{category}</dd></> : null}
        {children}
      </dl>
    </section>
  );
}
