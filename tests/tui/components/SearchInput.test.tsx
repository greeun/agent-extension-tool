import { describe, test, expect, mock } from "bun:test";
import React from "react";
import { render } from "ink-testing-library";
import { SearchInput } from "../../../src/tui/components/SearchInput.js";

describe("SearchInput", () => {
  test("'Search:' 레이블이 렌더링된다", () => {
    const { lastFrame } = render(
      <SearchInput value="" onChange={() => {}} onSubmit={() => {}} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Search:");
  });

  test("value prop이 표시된다", () => {
    const { lastFrame } = render(
      <SearchInput value="my-plugin" onChange={() => {}} onSubmit={() => {}} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("my-plugin");
  });

  test("빈 value로 렌더링 시 크래시 없음", () => {
    expect(() => {
      render(
        <SearchInput value="" onChange={() => {}} onSubmit={() => {}} />
      );
    }).not.toThrow();
  });

  test("onChange 콜백 prop이 수용된다", () => {
    const onChange = mock(() => {});
    const { lastFrame } = render(
      <SearchInput value="test" onChange={onChange} onSubmit={() => {}} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Search:");
  });

  test("onSubmit 콜백 prop이 수용된다", () => {
    const onSubmit = mock(() => {});
    const { lastFrame } = render(
      <SearchInput value="query" onChange={() => {}} onSubmit={onSubmit} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("query");
  });
});
