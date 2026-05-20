import { describe, test, expect } from "bun:test";
import React from "react";
import { render } from "ink-testing-library";
import { Text } from "ink";
import { useDetailScroll } from "../../../src/tui/components/useDetailScroll.js";

function Probe({ total, viewport, dispatch }: {
  total: number; viewport: number;
  dispatch: (api: ReturnType<typeof useDetailScroll>) => void;
}) {
  const api = useDetailScroll({ totalLines: total, viewportLines: viewport });
  dispatch(api);
  return <Text>{`${api.focused ? "F" : "U"}:${api.scroll}`}</Text>;
}

function simulate(
  api: ReturnType<typeof useDetailScroll>,
  input: string,
  key: Partial<{ return: boolean; escape: boolean; downArrow: boolean; upArrow: boolean; pageDown: boolean; pageUp: boolean; tab: boolean; shift: boolean; leftArrow: boolean; rightArrow: boolean; ctrl: boolean; meta: boolean }> = {},
) {
  const fullKey = {
    return: false, escape: false, downArrow: false, upArrow: false,
    pageDown: false, pageUp: false, tab: false, shift: false,
    leftArrow: false, rightArrow: false, ctrl: false, meta: false,
    backspace: false, delete: false,
    ...key,
  } as any;
  return api.handleInput(input, fullKey);
}

describe("useDetailScroll", () => {
  test("Enter from unfocused state focuses and consumes", () => {
    let api!: ReturnType<typeof useDetailScroll>;
    const { lastFrame, rerender } = render(<Probe total={20} viewport={5} dispatch={(a) => { api = a; }} />);
    expect(lastFrame()).toContain("U:0");
    const consumed = simulate(api, "", { return: true });
    expect(consumed).toBe(true);
    rerender(<Probe total={20} viewport={5} dispatch={(a) => { api = a; }} />);
    expect(lastFrame()).toContain("F:0");
  });

  test("Esc from focused state blurs and consumes", () => {
    let api!: ReturnType<typeof useDetailScroll>;
    const { lastFrame, rerender } = render(<Probe total={20} viewport={5} dispatch={(a) => { api = a; }} />);
    simulate(api, "", { return: true });
    rerender(<Probe total={20} viewport={5} dispatch={(a) => { api = a; }} />);
    const consumed = simulate(api, "", { escape: true });
    expect(consumed).toBe(true);
    rerender(<Probe total={20} viewport={5} dispatch={(a) => { api = a; }} />);
    expect(lastFrame()).toContain("U:0");
  });

  test("j and downArrow scroll by 1, capped at maxScroll", () => {
    let api!: ReturnType<typeof useDetailScroll>;
    const { lastFrame, rerender } = render(<Probe total={10} viewport={4} dispatch={(a) => { api = a; }} />);
    simulate(api, "", { return: true });
    rerender(<Probe total={10} viewport={4} dispatch={(a) => { api = a; }} />);
    simulate(api, "j", {});
    rerender(<Probe total={10} viewport={4} dispatch={(a) => { api = a; }} />);
    expect(lastFrame()).toContain("F:1");
    simulate(api, "", { downArrow: true });
    rerender(<Probe total={10} viewport={4} dispatch={(a) => { api = a; }} />);
    expect(lastFrame()).toContain("F:2");
    // maxScroll = 10 - 4 = 6 → push to 7 should clamp at 6
    for (let i = 0; i < 10; i++) simulate(api, "j", {});
    rerender(<Probe total={10} viewport={4} dispatch={(a) => { api = a; }} />);
    expect(lastFrame()).toContain("F:6");
  });

  test("PgDn scrolls by viewport, PgUp reverses, clamped at 0", () => {
    let api!: ReturnType<typeof useDetailScroll>;
    const { lastFrame, rerender } = render(<Probe total={50} viewport={10} dispatch={(a) => { api = a; }} />);
    simulate(api, "", { return: true });
    simulate(api, "", { pageDown: true });
    rerender(<Probe total={50} viewport={10} dispatch={(a) => { api = a; }} />);
    expect(lastFrame()).toContain("F:10");
    simulate(api, "", { pageUp: true });
    simulate(api, "", { pageUp: true });
    rerender(<Probe total={50} viewport={10} dispatch={(a) => { api = a; }} />);
    expect(lastFrame()).toContain("F:0");
  });

  test("any input is consumed (true) while focused even if not a scroll key", () => {
    let api!: ReturnType<typeof useDetailScroll>;
    render(<Probe total={20} viewport={5} dispatch={(a) => { api = a; }} />);
    simulate(api, "", { return: true });
    const consumed = simulate(api, "x", {});
    expect(consumed).toBe(true);
  });

  test("unfocused state passes through non-Enter keys (returns false)", () => {
    let api!: ReturnType<typeof useDetailScroll>;
    render(<Probe total={20} viewport={5} dispatch={(a) => { api = a; }} />);
    const consumed = simulate(api, "j", {});
    expect(consumed).toBe(false);
  });
});
