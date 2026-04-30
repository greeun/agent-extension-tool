import { rename, copyFile, mkdir } from "fs/promises";
import { dirname, join } from "path";
import { randomUUID } from "crypto";

export async function readJson<T = unknown>(
  filePath: string,
  options?: { fallback: T }
): Promise<T> {
  const file = Bun.file(filePath);
  if (!(await file.exists())) {
    if (options && "fallback" in options) return options.fallback;
    throw new Error(`File not found: ${filePath}`);
  }
  return file.json() as Promise<T>;
}

export async function writeJsonAtomic(
  filePath: string,
  data: unknown
): Promise<void> {
  const dir = dirname(filePath);
  await mkdir(dir, { recursive: true });

  const existing = Bun.file(filePath);
  if (await existing.exists()) {
    await copyFile(filePath, filePath + ".bak");
  }

  const tmpPath = join(dir, `.tmp-${randomUUID()}.json`);
  await Bun.write(tmpPath, JSON.stringify(data, null, 2) + "\n");
  await rename(tmpPath, filePath);
}
