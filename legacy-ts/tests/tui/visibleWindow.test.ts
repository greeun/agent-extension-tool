import { describe, test, expect } from "bun:test";
import { visibleWindow } from "../../src/tui/utils.js";

describe("visibleWindow", () => {
  test("목록이 maxRows 이하면 전체를 보여준다", () => {
    expect(visibleWindow(5, 0, 10)).toEqual([0, 5]);
    expect(visibleWindow(10, 9, 10)).toEqual([0, 10]);
  });

  test("선택 항목을 중앙에 두고 윈도잉한다", () => {
    // 20개, maxRows 10, 선택 10 → half=5 → start=5
    expect(visibleWindow(20, 10, 10)).toEqual([5, 15]);
  });

  test("앞쪽 선택 시 start가 0으로 클램프된다", () => {
    expect(visibleWindow(20, 1, 10)).toEqual([0, 10]);
  });

  test("끝쪽 선택 시 end가 length로 클램프된다", () => {
    expect(visibleWindow(20, 19, 10)).toEqual([10, 20]);
  });

  test("maxRows가 작아도 최소 1개 이상 윈도우를 만든다", () => {
    const [s, e] = visibleWindow(20, 5, 1);
    expect(e - s).toBe(1);
    expect(s).toBe(5);
  });

  test("Table.tsx 기존 동작과 동일 (length<=max → 전체)", () => {
    expect(visibleWindow(3, 2, 3)).toEqual([0, 3]);
  });
});
