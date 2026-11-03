import { expect, test } from "vitest";
import { historyStatus } from "./history-status";

test("v2 names pending, actual missing, failure and exclusion separately", () => {
  const data = {schema_version:2,items:[{}],complete:false,pending:["a","b"],missing:["c"],failed:["d"],official_missing:["e"],legacy_unknown:["f"]};
  const text=historyStatus(data,1);
  for (const part of ["尚未探查 2", "已確認缺圖 1", "請求／驗證失敗 1", "既定排除 1", "舊版分類不明 1"]) expect(text).toContain(part);
});
test("legacy failed never becomes a claimed request failure or pending count", () => {
  const text=historyStatus({items:[{}],complete:false,missing:["a"],failed:["b","c"]},1);
  expect(text).toContain("舊版缺漏 3");
  expect(text).toContain("無法可靠區分");
  expect(text).not.toContain("請求／驗證失敗 2");
});
test("unknown versions and malformed arrays fail instead of inventing zero gaps", () => {
  expect(()=>historyStatus({schema_version:3},1)).toThrow();
  expect(()=>historyStatus({schema_version:2,pending:[]},1)).toThrow();
});
