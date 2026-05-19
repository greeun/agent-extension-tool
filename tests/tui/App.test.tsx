/**
 * App 포커스 레이어 전환 규칙 테스트
 *
 * 핵심 규칙: 최상단 탭 레이어(mainTab)에 포커스가 있을 때 좌우/숫자키로
 * 탭을 이동해도 포커스는 mainTab 레이어에 그대로 머물러야 한다.
 * (하위 탭/콘텐츠로 자동 하강 금지)
 */

import { describe, test, expect } from "bun:test";
import { nextFocusLayer } from "../../src/tui/App.js";

describe("nextFocusLayer", () => {
  test("mainTab에서 탭 이동 시 mainTab 유지 (claude로 이동해도 subTab으로 안 내려감)", () => {
    expect(nextFocusLayer("mainTab", "claude")).toBe("mainTab");
  });

  test("mainTab에서 Extensions로 이동해도 mainTab 유지 (content로 안 내려감)", () => {
    expect(nextFocusLayer("mainTab", "extensions")).toBe("mainTab");
  });

  test("mainTab에서 일반 탭으로 이동해도 mainTab 유지", () => {
    expect(nextFocusLayer("mainTab", "dashboard")).toBe("mainTab");
    expect(nextFocusLayer("mainTab", "project")).toBe("mainTab");
    expect(nextFocusLayer("mainTab", "cursor")).toBe("mainTab");
  });

  test("content 레이어에서 직접 점프 시 기존 동작 유지 (claude→subTab)", () => {
    expect(nextFocusLayer("content", "claude")).toBe("subTab");
  });

  test("content 레이어에서 일반 탭으로 점프 시 content 유지", () => {
    expect(nextFocusLayer("content", "dashboard")).toBe("content");
    expect(nextFocusLayer("content", "extensions")).toBe("content");
  });

  test("subTab 레이어에서 점프 시 목적지 기본값 적용 (기존 동작 보존)", () => {
    expect(nextFocusLayer("subTab", "claude")).toBe("subTab");
    expect(nextFocusLayer("subTab", "project")).toBe("content");
  });
});
