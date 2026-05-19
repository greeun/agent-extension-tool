import { test, expect } from "bun:test";
import { writeFileSync, mkdtempSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { readJsonlRecords } from "../../src/utils/jsonl.js";

test("parses valid lines, skips blank and malformed", async () => {
  const dir = mkdtempSync(join(tmpdir(), "jsonl-"));
  const f = join(dir, "a.jsonl");
  writeFileSync(f, '{"a":1}\n\n  \nnot-json\n{"b":2}\n');
  const recs = await readJsonlRecords(f);
  expect(recs).toEqual([{ a: 1 }, { b: 2 }]);
});

test("returns [] when file is unreadable", async () => {
  const recs = await readJsonlRecords("/no/such/file.jsonl");
  expect(recs).toEqual([]);
});
