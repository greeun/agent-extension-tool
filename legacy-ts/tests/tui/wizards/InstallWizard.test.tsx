import { describe, test, expect, mock } from "bun:test";
import React from "react";
import { render } from "ink-testing-library";
import { InstallWizard } from "../../../src/tui/wizards/InstallWizard.js";

describe("InstallWizard", () => {
  test("'Install Plugin' 텍스트가 렌더링된다", () => {
    const { lastFrame } = render(
      <InstallWizard onDone={() => {}} onCancel={() => {}} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Install Plugin");
  });

  test("'Step 1/3' 표시가 있다", () => {
    const { lastFrame } = render(
      <InstallWizard onDone={() => {}} onCancel={() => {}} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Step 1/3");
  });

  test("'Search' 관련 텍스트가 있다", () => {
    const { lastFrame } = render(
      <InstallWizard onDone={() => {}} onCancel={() => {}} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Search");
  });

  test("초기 상태에서 SearchInput 레이블('Search:')이 보인다", () => {
    const { lastFrame } = render(
      <InstallWizard onDone={() => {}} onCancel={() => {}} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Search:");
  });

  test("onDone / onCancel 콜백 prop으로 렌더링에 크래시 없음", () => {
    const onDone = mock(() => {});
    const onCancel = mock(() => {});
    expect(() => {
      render(<InstallWizard onDone={onDone} onCancel={onCancel} />);
    }).not.toThrow();
  });
});
