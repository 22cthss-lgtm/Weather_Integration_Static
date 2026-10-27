// @vitest-environment node
import { expect, test } from "vitest";
import { formatImageDate, formatImageTime, formatImageTitle } from "./image-time";

test("image time converts UTC to Taipei with a fixed midnight format", () => {
  expect(formatImageTime("2026-10-21T16:00:00Z")).toBe("2026/10/22 00:00");
});

test("represented dates keep their calendar date without timezone conversion", () => {
  expect(formatImageDate("2026-10-21")).toBe("2026/10/21");
});

test("image headings format both existing title suffixes without changing metadata", () => {
  const image = { title: "CWA Radar 2026-10-22 01:00", image_time: "2026-10-22T01:00:00+08:00" };
  expect(formatImageTitle(image)).toBe("CWA Radar 2026/10/22 01:00");
  expect(formatImageTitle({ ...image, title: `Radar ${image.image_time}` })).toBe("Radar 2026/10/22 01:00");
  expect(image.image_time).toBe("2026-10-22T01:00:00+08:00");
});
