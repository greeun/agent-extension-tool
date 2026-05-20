import { describe, test, expect, beforeAll, afterAll } from "bun:test";
import { render } from "ink-testing-library";
import chalk, { type ColorSupportLevel } from "chalk";
import { Table } from "../../../src/tui/components/Table.js";

let originalChalkLevel: ColorSupportLevel;
beforeAll(() => {
  originalChalkLevel = chalk.level;
  chalk.level = 3 as ColorSupportLevel;
});
afterAll(() => {
  chalk.level = originalChalkLevel;
});

const cols = [
  { key: "no", label: "#", width: 3 },
  { key: "name", label: "Name", width: 20 },
];

const rows = Array.from({ length: 16 }, (_, i) => ({
  no: String(i + 1),
  name: `item-${i + 1}`,
}));

describe("Table selection rendering", () => {
  test("selected row shows ▸ pointer and row data", () => {
    const { lastFrame } = render(
      <Table columns={cols} rows={rows} selectedIndex={13} checked={new Set<number>()} maxRows={20} gap={2} />,
    );
    const frame = lastFrame() ?? "";
    // The selected row (display 14) must include the ▸ pointer AND its row data.
    // Regression: previously a structural asymmetry (single Text inverse vs
    // nested Text dim) combined with `inverse`-driven trailing padding caused
    // some terminal multiplexers to drop the ▸/# column of the selected row.
    const lines = frame.split("\n");
    const selectedLine = lines.find((l) => l.includes("item-14"));
    expect(selectedLine).toBeDefined();
    expect(selectedLine).toContain("▸");
    expect(selectedLine).toContain("14");
  });

  test("selected row does NOT use inverse styling (uses foreground color)", () => {
    const { lastFrame } = render(
      <Table columns={cols} rows={rows} selectedIndex={13} checked={new Set<number>()} maxRows={20} gap={2} />,
    );
    const frame = lastFrame() ?? "";
    // Regression: `inverse` (\x1b[7m) pads trailing spaces to keep the
    // background flip visible, which is asymmetric with non-selected rows
    // and trips WezTerm/cmux. The selection highlight is implemented via
    // cyan + bold instead.
    expect(frame.includes("\x1b[7m")).toBe(false);
    const lines = frame.split("\n");
    const selectedLine = lines.find((l) => l.includes("item-14")) ?? "";
    // cyan = \x1b[36m, bold = \x1b[1m. Either is sufficient to indicate styling.
    expect(/\x1b\[(36|1)m/.test(selectedLine)).toBe(true);
  });

  test("selected and non-selected rows share identical structure", () => {
    const { lastFrame } = render(
      <Table columns={cols} rows={rows} selectedIndex={5} checked={new Set<number>()} maxRows={20} gap={2} />,
    );
    const frame = lastFrame() ?? "";
    const lines = frame.split("\n");
    // Find rows by their distinct row-data so we can compare structural shape.
    const row1 = lines.find((l) => l.includes("item-1") && !l.includes("item-10") && !l.includes("item-11") && !l.includes("item-12") && !l.includes("item-13") && !l.includes("item-14") && !l.includes("item-15") && !l.includes("item-16"));
    const row6 = lines.find((l) => l.includes("item-6"));
    expect(row1).toBeDefined();
    expect(row6).toBeDefined();
    // Both rows must contain a prefix glyph (□) and the row data — i.e. they
    // were both rendered as full rows, not collapsed.
    expect(row1).toContain("□");
    expect(row6).toContain("□");
    expect(row1).toContain("item-1");
    expect(row6).toContain("item-6");
    // The selected row must additionally include the ▸ pointer.
    expect(row6).toContain("▸");
    expect(row1).not.toContain("▸");
  });

  test("non-selected rows do not contain the ▸ pointer", () => {
    const { lastFrame } = render(
      <Table columns={cols} rows={rows} selectedIndex={0} checked={new Set<number>()} maxRows={20} gap={2} />,
    );
    const frame = lastFrame() ?? "";
    const pointers = (frame.match(/▸/g) ?? []).length;
    expect(pointers).toBe(1); // only one selected row at a time
  });

  test("checked-mode prefix marks both selection and check state", () => {
    const { lastFrame } = render(
      <Table
        columns={cols}
        rows={rows}
        selectedIndex={2}
        checked={new Set<number>([2, 5])}
        maxRows={20}
        gap={2}
      />,
    );
    const frame = lastFrame() ?? "";
    const lines = frame.split("\n");
    const row3 = lines.find((l) => l.includes("item-3"));
    const row6 = lines.find((l) => l.includes("item-6"));
    // Row 3 (index 2): selected AND checked → ▸ + ■
    expect(row3).toContain("▸");
    expect(row3).toContain("■");
    // Row 6 (index 5): checked but not selected → ■ without ▸
    expect(row6).toContain("■");
    expect(row6).not.toContain("▸");
  });
});
