import { test, expect } from "bun:test";
import { filterByTimestampMs, filterByDateString } from "../../../src/core/usage/filter.js";

test("filterByTimestampMs uses millisecond comparison", () => {
  const e = [{ timestamp: "2026-05-01T12:00:00Z", v: 1 }];
  expect(filterByTimestampMs(e, new Date("2026-05-01T13:00:00Z").getTime(), null)).toEqual([]);
  expect(filterByTimestampMs(e, new Date("2026-05-01T11:00:00Z").getTime(), null)).toEqual(e);
});

test("filterByDateString uses YYYY-MM-DD prefix comparison", () => {
  const e = [{ timestamp: "2026-05-01T12:00:00Z" }];
  expect(filterByDateString(e, "2026-05-01", undefined)).toEqual(e);
  expect(filterByDateString(e, "2026-05-02", undefined)).toEqual([]);
});
