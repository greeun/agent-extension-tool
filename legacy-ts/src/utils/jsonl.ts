import { readFile } from "fs/promises";

/**
 * Read a JSONL file and return one parsed record per non-blank line.
 * Blank lines and lines that fail JSON.parse are skipped. An unreadable
 * file yields []. This mirrors the existing per-loader behavior exactly.
 */
export async function readJsonlRecords(filePath: string): Promise<unknown[]> {
  let content: string;
  try {
    content = await readFile(filePath, "utf-8");
  } catch {
    return [];
  }
  const out: unknown[] = [];
  for (const line of content.split("\n")) {
    if (!line.trim()) continue;
    try {
      out.push(JSON.parse(line));
    } catch {
      // skip malformed line
    }
  }
  return out;
}
