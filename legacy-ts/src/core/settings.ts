import { readJson, writeJsonAtomic } from "./json-io.js";

interface Settings {
  enabledPlugins?: Record<string, boolean>;
  favoritePlugins?: Record<string, boolean>;
  markedForUpdate?: Record<string, boolean>;
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

export async function readFavoritePlugins(settingsPath: string): Promise<Record<string, boolean>> {
  const settings = await readJson<Settings>(settingsPath, { fallback: {} });
  return settings.favoritePlugins ?? {};
}

export async function setPluginFavorite(settingsPath: string, pluginId: string, favorite: boolean): Promise<void> {
  const settings = await readJson<Settings>(settingsPath, { fallback: {} });
  if (!settings.favoritePlugins) settings.favoritePlugins = {};
  if (favorite) {
    settings.favoritePlugins[pluginId] = true;
  } else {
    delete settings.favoritePlugins[pluginId];
  }
  await writeJsonAtomic(settingsPath, settings);
}

export async function readMarkedForUpdate(settingsPath: string): Promise<Record<string, boolean>> {
  const settings = await readJson<Settings>(settingsPath, { fallback: {} });
  return settings.markedForUpdate ?? {};
}

export async function setMarkedForUpdate(settingsPath: string, pluginId: string, marked: boolean): Promise<void> {
  const settings = await readJson<Settings>(settingsPath, { fallback: {} });
  if (!settings.markedForUpdate) settings.markedForUpdate = {};
  if (marked) {
    settings.markedForUpdate[pluginId] = true;
  } else {
    delete settings.markedForUpdate[pluginId];
  }
  await writeJsonAtomic(settingsPath, settings);
}

export async function readExtraMarketplaces(settingsPath: string): Promise<Record<string, { source: { source: string; repo?: string; url?: string } }>> {
  const settings = await readJson<Settings>(settingsPath, { fallback: {} });
  return settings.extraKnownMarketplaces ?? {};
}
