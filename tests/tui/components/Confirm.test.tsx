import { describe, test, expect, mock } from "bun:test";
import React from "react";
import { render } from "ink-testing-library";
import { Confirm } from "../../../src/tui/components/Confirm.js";

describe("Confirm", () => {
  test("message prop이 렌더링에 포함된다", () => {
    const { lastFrame } = render(
      <Confirm
        message="정말로 삭제하시겠습니까?"
        onConfirm={() => {}}
        onCancel={() => {}}
      />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("정말로 삭제하시겠습니까?");
  });

  test("y:confirm  n:cancel 힌트가 포함된다", () => {
    const { lastFrame } = render(
      <Confirm
        message="확인 메시지"
        onConfirm={() => {}}
        onCancel={() => {}}
      />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("y:confirm  n:cancel");
  });

  test("double 테두리(border)가 있다", () => {
    const { lastFrame } = render(
      <Confirm
        message="border 테스트"
        onConfirm={() => {}}
        onCancel={() => {}}
      />
    );
    const frame = lastFrame() ?? "";
    // ink의 double borderStyle은 ╔ 또는 ═ 문자를 사용
    expect(frame).toMatch(/[╔╗╚╝═║]/);
  });

  test("onConfirm 콜백 prop이 수용된다", () => {
    const onConfirm = mock(() => {});
    const onCancel = mock(() => {});
    const { lastFrame } = render(
      <Confirm
        message="콜백 테스트"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("콜백 테스트");
  });

  test("onCancel 콜백 prop이 수용된다", () => {
    const onCancel = mock(() => {});
    const { lastFrame } = render(
      <Confirm
        message="취소 콜백 테스트"
        onConfirm={() => {}}
        onCancel={onCancel}
      />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("취소 콜백 테스트");
  });
});
