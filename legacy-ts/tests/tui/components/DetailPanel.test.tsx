import { describe, test, expect, beforeAll, afterAll } from "bun:test";
import { EventEmitter } from "node:events";
import type { ReactElement } from "react";
import { render as inkRender } from "ink";
import { render } from "ink-testing-library";
import { DetailPanel } from "../../../src/tui/components/DetailPanel.js";
import chalk, { type ColorSupportLevel } from "chalk";
import stringWidth from "string-width";

class MockStdout extends EventEmitter {
  columns: number;
  frames: string[] = [];
  private _lastFrame: string | undefined;
  constructor(columns: number) {
    super();
    this.columns = columns;
  }
  write = (frame: string) => {
    this.frames.push(frame);
    this._lastFrame = frame;
  };
  lastFrame = () => this._lastFrame;
}

class MockStdin extends EventEmitter {
  isTTY = true;
  setEncoding() {}
  setRawMode() {}
  resume() {}
  pause() {}
  ref() {}
  unref() {}
  read() {
    return null;
  }
}

function renderAtWidth(node: ReactElement, columns: number) {
  const stdout = new MockStdout(columns);
  const stderr = new MockStdout(columns);
  const stdin = new MockStdin();
  inkRender(node, {
    stdout: stdout as any,
    stderr: stderr as any,
    stdin: stdin as any,
    debug: true,
    exitOnCtrlC: false,
    patchConsole: false,
  });
  return { lastFrame: () => stdout.lastFrame() };
}

let originalChalkLevel: ColorSupportLevel;

beforeAll(() => {
  originalChalkLevel = chalk.level;
  chalk.level = 3 as ColorSupportLevel;
});

afterAll(() => {
  chalk.level = originalChalkLevel;
});

describe("DetailPanel (multiline + scroll)", () => {
  test("wraps long field values across multiple lines", () => {
    const longVal = "a".repeat(120);
    const { lastFrame } = render(
      <DetailPanel
        title="T"
        fields={[{ label: "P", value: longVal }]}
        maxHeight={20}
      />,
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("P:");
    expect((frame.match(/a/g) ?? []).length).toBeGreaterThan(80);
  });

  test("shows scroll indicator when content exceeds maxHeight", () => {
    const fields = Array.from({ length: 40 }, (_, i) => ({
      label: `K${i}`,
      value: `v${i}`,
    }));
    const { lastFrame } = render(
      <DetailPanel fields={fields} maxHeight={10} scroll={0} />,
    );
    const frame = lastFrame() ?? "";
    expect(/\[\d+-\d+ ?\/ ?\d+\]/.test(frame)).toBe(true);
  });

  test("scroll prop shifts which lines are visible", () => {
    const fields = Array.from({ length: 40 }, (_, i) => ({
      label: `K${i}`,
      value: `v${i}`,
    }));
    const a = render(<DetailPanel fields={fields} maxHeight={10} scroll={0} />).lastFrame() ?? "";
    const b = render(<DetailPanel fields={fields} maxHeight={10} scroll={20} />).lastFrame() ?? "";
    expect(a).toContain("K0:");
    expect(a.includes("K39:")).toBe(false);
    expect(b.includes("K0:")).toBe(false);
    expect(b).toContain("K20:");
  });

  test("focused=true colors the border cyan", () => {
    const { lastFrame } = render(
      <DetailPanel fields={[{ label: "A", value: "x" }]} focused />,
    );
    const frame = lastFrame() ?? "";
    expect(frame.includes("[36m")).toBe(true);
  });
});

describe("DetailPanel (CJK width handling)", () => {
  const STRIP_ANSI = /\x1b\[[0-9;]*m/g;

  function frameLines(frame: string): string[] {
    return frame
      .replace(STRIP_ANSI, "")
      .split("\n")
      .filter((l) => l.length > 0);
  }

  test("right border stays at a consistent column for CJK-heavy content (wide terminal)", () => {
    const cols = 196;
    const cjkValue =
      'English prompt playbook that operationalizes Anthropic\'s "Harness Design for Long-Running Application Development" article for app/service build phases. "하네스 디자인", "하네스 프롬프트", "코딩 하네스", "장시간 코딩 에이전트", "장시간 자율 코딩", "앱 만들 때 프롬프트", "서비스 구축 프롬프트", "풀스택 에이전트 루프", "planner generator evaluator 루프", "플래너 제너레이터 이밸류에이터", "sprint contract", "스프린트 컨트랙트", "컨텍스트 불안", "컨텍스트 리셋", "파일 기반 시스템 프롬프트", "앱 빌드 루프", "Anthropic harness design" 같은 요청에 사용.';
    const { lastFrame } = renderAtWidth(
      <DetailPanel
        title="harness-driven-dev (skill)"
        fields={[
          { label: "Description", value: cjkValue },
          { label: "Extension path", value: "/Users/uni4love/.axt/vault/skills/harness-driven-dev" },
          { label: "Used in", value: "withwiz-pms, dts-ballet-homepage, url-shortener-mvp, yeroom-homepage, withwiz-blog-core-v2, withwiz-toolkit" },
        ]}
        contentWidth={cols - 4}
        maxHeight={40}
      />,
      cols,
    );
    const lines = frameLines(lastFrame() ?? "");
    expect(lines.length).toBeGreaterThan(2);
    const widths = lines.map((l) => stringWidth(l));
    const max = Math.max(...widths);
    const min = Math.min(...widths);
    expect(max - min).toBe(0);
  });

  test("ambiguous-width chars (→ — …) never push content past the box inner width", () => {
    const cols = 100;
    const innerWidth = cols - 4;
    const arrowValue =
      'Generate plans using a Planner → Generator → Evaluator harness. Trigger phrases — English: "business plan", "GTM plan", "validate my idea"… (한글): "사업 계획", "비즈니스 모델".';
    const { lastFrame } = renderAtWidth(
      <DetailPanel
        title="harness (skill)"
        fields={[
          { label: "Description", value: arrowValue },
          { label: "Path", value: "/tmp/x" },
        ]}
        contentWidth={innerWidth}
        maxHeight={40}
      />,
      cols,
    );
    const lines = frameLines(lastFrame() ?? "");
    // For CONTENT rows (those with `│` paddings) check that the inner content
    // never exceeds `innerWidth` in either measurement. Border rows made
    // entirely of box-drawing glyphs are skipped — those glyphs are also
    // ambiguous-width and need their own handling at the Ink layer.
    for (const l of lines) {
      if (l.startsWith("│") && l.endsWith("│")) {
        const inner = l.slice(2, -2); // strip "│ " and " │"
        expect(stringWidth(inner, { ambiguousIsNarrow: false })).toBeLessThanOrEqual(innerWidth);
      }
    }
  });

  test("long single-field value that wraps does not collapse onto the bottom border", () => {
    const cols = 100;
    const usedIn =
      "withwiz-pms, dts-ballet-homepage, url-shortener-mvp, yeroom-homepage, withwiz-blog-core-v2, withwiz-toolkit";
    const { lastFrame } = renderAtWidth(
      <DetailPanel
        title="t"
        fields={[{ label: "Used in", value: usedIn }]}
        contentWidth={cols - 4}
        maxHeight={40}
      />,
      cols,
    );
    const lines = frameLines(lastFrame() ?? "");
    const lastLine = lines[lines.length - 1] ?? "";
    expect(lastLine.startsWith("└")).toBe(true);
    expect(lastLine.includes("withwiz")).toBe(false);
  });
});
