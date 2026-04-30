import { readJson, writeJsonAtomic } from "./json-io.js";

interface Settings {
  enabledPlugins?: Record<string, boolean>;
  extraKnownMarketplaces?: Record<string, { source: { source: string; repo?: string; url?: string } }>;
  [key: string]: unknown;
}

export async function readEnabledPlugins(settingsPath: string): Promise<Record<string, boolean>> {
  const settings = await readJson<Settings>(settingsPath, { fallback: {} });
  return settings.enabledPlugins ?? {};
}

export async function setPluginEnabled(settingsPath: string, pluginId: string, enabled: boolean): Promise<void> {
  const settings = await readJson<Settings>(settingsPath, { fallback: {} });
  if (!settings.enabledPlugins) settings.enabledPlugins = {};
  settings.enabledPlugins[pluginId] = enabled;
  await writeJsonAtomic(settingsPath, settings);
}

export async function removePluginFromSettings(settingsPath: string, pluginId: string): Promise<void> {
  const settings = await readJson<Settings>(settingsPath, { fallback: {} });
  if (settings.enabledPlugins) { delete settings.enabledPlugins[pluginId]; }
  await writeJsonAtomic(settingsPath, settings);
}

export async function readExtraMarketplaces(settingsPath: string): Promise<Record<string, { source: { source: string; repo?: string; url?: string } }>> {
  const settings = await readJson<Settings>(settingsPath, { fallback: {} });
  return settings.extraKnownMarketplaces ?? {};
}
