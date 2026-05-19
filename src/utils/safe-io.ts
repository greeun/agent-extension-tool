import { readFile, readdir, lstat } from "fs/promises";

export async function safeRead(path: string): Promise<string | null> {
  try {
    const stat = await lstat(path);
    if (!stat.isFile()) return null;
    return await readFile(path, "utf-8");
  } catch {
    return null;
  }
}

export async function safeReaddir(dir: string): Promise<string[]> {
  try { return await readdir(dir); } catch { return []; }
}
