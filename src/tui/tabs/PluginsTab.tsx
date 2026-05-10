import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import { Table } from "../components/Table.js";
import { PATHS } from "../../core/paths.js";
import { listInstalledPlugins, updatePlugin, type PluginInfo } from "../../core/plugin.js";
import {
  readEnabledPlugins, setPluginEnabled,
  readFavoritePlugins, setPluginFavorite,
  readMarkedForUpdate, setMarkedForUpdate,
} from "../../core/settings.js";
import { RemoveWizard } from "../wizards/RemoveWizard.js";
import { InstallWizard } from "../wizards/InstallWizard.js";

type PluginWithState = PluginInfo & { enabled: boolean; favorite: boolean; markedForUpdate: boolean };

interface ActionItem {
  label: string;
  color?: string;
  action: () => void;
}

interface Props {
  isFocused?: boolean;
  onFocusUp?: () => void;
  onSubViewChange?: (inSubView: boolean) => void;
}

export function PluginsTab({ isFocused = true, onFocusUp, onSubViewChange }: Props) {
  const [plugins, setPlugins] = useState<PluginWithState[]>([]);
  const [index, setIndex] = useState(0);
  const [mode, setMode] = useState<"list" | "detail">("list");
  const [actionIndex, setActionIndex] = useState(0);
  const [wizard, setWizard] = useState<"none" | "install" | "remove">("none");
  const [filter, setFilter] = useState("");
  const [searching, setSearching] = useState(false);
  const [status, setStatus] = useState("");

  const load = async () => {
    const list = await listInstalledPlugins(PATHS.installedPlugins);
    const enabled = await readEnabledPlugins(PATHS.settings);
    const favorites = await readFavoritePlugins(PATHS.settings);
    const marked = await readMarkedForUpdate(PATHS.settings);
    setPlugins(list.map((p) => ({
      ...p,
      enabled: enabled[p.id] === true,
      favorite: favorites[p.id] === true,
      markedForUpdate: marked[p.id] === true,
    })));
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    onSubViewChange?.(mode === "detail");
  }, [mode]);

  const filtered = filter
    ? plugins.filter((p) => p.name.toLowerCase().includes(filter.toLowerCase()))
    : plugins;

  const selected = filtered[index];

  const buildActions = (p: PluginWithState): ActionItem[] => {
    const actions: ActionItem[] = [];
    actions.push({
      label: p.enabled ? "Disable plugin" : "Enable plugin",
      action: () => { setPluginEnabled(PATHS.settings, p.id, !p.enabled).then(load); },
    });
    actions.push({
      label: p.favorite ? "Remove from favorites" : "Add to favorites",
      action: () => { setPluginFavorite(PATHS.settings, p.id, !p.favorite).then(load); },
    });
    actions.push({
      label: p.markedForUpdate ? "Unmark for update" : "Mark for update",
      action: () => { setMarkedForUpdate(PATHS.settings, p.id, !p.markedForUpdate).then(load); },
    });
    actions.push({
      label: "Update now",
      color: "cyan",
      action: () => {
        setStatus(`Updating ${p.name}...`);
        updatePlugin(PATHS.installedPlugins, PATHS.knownMarketplaces, p.id)
          .then((result) => { setStatus(result.message); load(); })
          .catch((e: any) => { setStatus(`Update failed: ${e.message}`); load(); });
      },
    });
    actions.push({
      label: "Uninstall",
      color: "red",
      action: () => { setWizard("remove"); },
    });
    if (p.homepage) {
      actions.push({
        label: "Open homepage",
        action: () => { Bun.spawn(["open", p.homepage!]); },
      });
    }
    if (p.repository) {
      actions.push({
        label: "View repository",
        action: () => { Bun.spawn(["open", p.repository!]); },
      });
    }
    actions.push({
      label: "Back to plugin list",
      action: () => { setMode("list"); setActionIndex(0); },
    });
    return actions;
  };

  const actions = selected ? buildActions(selected) : [];

  useInput((input, key) => {
    if (searching) {
      if (key.escape) { setSearching(false); setFilter(""); }
      return;
    }
    if (wizard !== "none") return;
    if (!isFocused) return;

    if (mode === "detail") {
      if (key.escape) { setMode("list"); setActionIndex(0); return; }
      if (input === "j" || key.downArrow) {
        setActionIndex((i) => Math.min(i + 1, actions.length - 1));
      }
      if (input === "k" || key.upArrow) {
        setActionIndex((i) => Math.max(i - 1, 0));
      }
      if (key.return && actions[actionIndex]) {
        actions[actionIndex].action();
      }
      return;
    }

    // list mode
    if (input === "j" || key.downArrow) {
      if (filtered.length > 0) setIndex((i) => Math.min(i + 1, filtered.length - 1));
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
    }
    if (key.return && selected) {
      setMode("detail");
      setActionIndex(0);
    }
    if (input === "i") setWizard("install");
    if (input === "/") { setSearching(true); setFilter(""); setIndex(0); }
  });

  const rows = filtered.map((p) => ({
    name: (p.favorite ? "★ " : "") + p.name,
    version: p.version,
    status: p.enabled ? "● active" : "○ off",
    scope: p.scope,
    marketplace: p.marketplace,
    updated: p.lastUpdated.slice(0, 10),
  }));

  if (mode === "detail" && selected) {
    return (
      <Box flexDirection="column">
        <Box flexDirection="column" borderStyle="single" paddingX={1}>
          <Text bold>{selected.name} @ {selected.marketplace}</Text>
          <Text>Scope: <Text color="white">{selected.scope}</Text></Text>
          <Text>Version: <Text color="green">{selected.version}</Text></Text>
          {selected.description && <Text>{selected.description}</Text>}
          <Text> </Text>
          {selected.author && <Text dimColor>Author: {selected.author}</Text>}
          <Text>Status: <Text color={selected.enabled ? "green" : "gray"}>{selected.enabled ? "Enabled" : "Disabled"}</Text></Text>
          {selected.markedForUpdate && <Text color="yellow">Marked for update</Text>}
          <Text> </Text>
          {actions.map((a, i) => (
            <Box key={i}>
              <Text color={i === actionIndex ? "blue" : undefined} bold={i === actionIndex}>
                {i === actionIndex ? "❯ " : "  "}
              </Text>
              <Text
                color={i === actionIndex ? (a.color ?? "white") : (a.color ?? undefined)}
                bold={i === actionIndex}
              >
                {a.label}
              </Text>
            </Box>
          ))}
        </Box>
        <Box marginTop={1}>
          <Text dimColor>ctrl+p to navigate · Enter to select · Esc to back</Text>
        </Box>
        {status && <Box marginTop={1}><Text dimColor>{status}</Text></Box>}
        {wizard === "remove" && (
          <RemoveWizard
            pluginId={selected.id}
            installPath={selected.installPath}
            onDone={() => { setWizard("none"); setMode("list"); setActionIndex(0); load(); }}
            onCancel={() => setWizard("none")}
          />
        )}
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      {searching && (
        <Box marginBottom={1}>
          <Text>Filter: </Text>
          <TextInput value={filter} onChange={(v) => { setFilter(v); setIndex(0); }} onSubmit={() => setSearching(false)} />
          <Text dimColor>  Enter:apply  Esc:clear</Text>
        </Box>
      )}
      {!searching && filter && (
        <Box marginBottom={1}>
          <Text dimColor>Filter: "{filter}" ({filtered.length}/{plugins.length})  /:edit</Text>
        </Box>
      )}
      <Table
        columns={[
          { key: "name", label: "Plugin", width: 24 },
          { key: "version", label: "Version", width: 10 },
          { key: "status", label: "Status", width: 10 },
          { key: "scope", label: "Scope", width: 9 },
          { key: "marketplace", label: "Marketplace", width: 22 },
          { key: "updated", label: "Updated", width: 12 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      {selected ? (
        <Box marginTop={1} paddingX={1}>
          <Text dimColor>Enter:actions  i:install  /:search</Text>
        </Box>
      ) : (
        <Box marginTop={1} borderStyle="single" paddingX={1}>
          <Text>No plugin selected</Text>
        </Box>
      )}
      {wizard === "install" && (
        <InstallWizard
          onDone={() => { setWizard("none"); load(); }}
          onCancel={() => setWizard("none")}
        />
      )}
      {status && <Box marginTop={1}><Text dimColor>{status}</Text></Box>}
    </Box>
  );
}
