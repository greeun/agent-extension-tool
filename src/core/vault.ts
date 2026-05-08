import { join } from "path";
import { writeJsonAtomic } from "./json-io.js";

export type ExtensionType = "skill" | "command" | "agent" | "plugin";

export interface VaultItem {
  name: string;
  type: ExtensionType;
  path: string;
  isLinked: boolean;
}

export interface AxtProfile {
  extensions: {
    skills: string[];
    commands: string[];
    agents: string[];
    plugins: string[];
  };
}

export interface SyncResult {
  linked: string[];
  unlinked: string[];
  errors: string[];
}

export interface MigrateResult {
  moved: string[];
  skipped: string[];
  errors: string[];
}

const PROFILE_NAME = ".axt-profile.json";

export function emptyProfile(): AxtProfile {
  return { extensions: { skills: [], commands: [], agents: [], plugins: [] } };
}

export async function readProfile(projectDir: string): Promise<AxtProfile | null> {
  const file = Bun.file(join(projectDir, PROFILE_NAME));
  if (!(await file.exists())) return null;
  return file.json() as Promise<AxtProfile>;
}

export async function writeProfile(projectDir: string, profile: AxtProfile): Promise<void> {
  await writeJsonAtomic(join(projectDir, PROFILE_NAME), profile);
}
