import { homedir } from "os";
import { join } from "path";

const CLAUDE_DIR = process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), ".claude");
const CODEX_DIR = process.env.CODEX_HOME ?? join(homedir(), ".codex");
const GEMINI_DIR = process.env.GEMINI_CLI_HOME
  ? join(process.env.GEMINI_CLI_HOME, ".gemini")
  : join(homedir(), ".gemini");

export const PATHS = {
  // Claude
  claudeDir: CLAUDE_DIR,
  settings: join(CLAUDE_DIR, "settings.json"),
  knownMarketplaces: join(CLAUDE_DIR, "plugins", "known_marketplaces.json"),
  installedPlugins: join(CLAUDE_DIR, "plugins", "installed_plugins.json"),
  blocklist: join(CLAUDE_DIR, "plugins", "blocklist.json"),
  pluginCache: join(CLAUDE_DIR, "plugins", "cache"),
  marketplaces: join(CLAUDE_DIR, "plugins", "marketplaces"),
  skills: join(CLAUDE_DIR, "skills"),
  projects: join(CLAUDE_DIR, "projects"),
  statsCache: join(CLAUDE_DIR, "stats-cache.json"),

  // Codex
  codexDir: CODEX_DIR,
  codexSessions: join(CODEX_DIR, "sessions"),

  // Gemini
  geminiDir: GEMINI_DIR,
  geminiTmp: join(GEMINI_DIR, "tmp"),
  geminiProjects: join(GEMINI_DIR, "projects.json"),

  // Cursor
  cursorDir: join(homedir(), ".cursor"),
  cursorTrackingDb: join(homedir(), ".cursor", "ai-tracking", "ai-code-tracking.db"),
} as const;

const IS_WINDOWS = process.platform === "win32";

export const AXT_CONFIG_DIR = join(
  IS_WINDOWS
    ? (process.env.APPDATA ?? join(homedir(), "AppData", "Roaming"))
    : (process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config")),
  "axt"
);
export const AXT_CONFIG_PATH = join(AXT_CONFIG_DIR, "config.json");
