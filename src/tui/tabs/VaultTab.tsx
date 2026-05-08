import { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import { Table } from "../components/Table.js";
import { Confirm } from "../components/Confirm.js";
import {
  listVaultItemsWithProjectState,
  linkToProject,
  unlinkFromProject,
  linkToGlobal,
  unlinkFromGlobal,
  migrateToVault,
  syncProject,
} from "../../core/vault.js";
import { listInstalledPlugins } from "../../core/plugin.js";
import { setPluginEnabled } from "../../core/settings.js";
import { PATHS } from "../../core/paths.js";
import type { VaultItem } from "../../core/vault.js";
import { join } from "path";

type FilterType = "all" | "skill" | "command" | "agent" | "plugin";
const FILTERS: FilterType[] = ["all", "skill", "command", "agent", "plugin"];

interface Props {
  isFocused: boolean;
  onFocusUp?: () => void;
}

export function VaultTab({ isFocused, onFocusUp }: Props) {
  const [items, setItems] = useState<VaultItem[]>([]);
  const [index, setIndex] = useState(0);
  const [filter, setFilter] = useState<FilterType>("all");
  const [pending, setPending] = useState<Map<string, boolean>>(new Map());
  const [mode, setMode] = useState<"list" | "confirm">("list");
  const [status, setStatus] = useState("");
  const [projectDir] = useState(() => process.cwd());

  const load = async () => {
    const plugins = await listInstalledPlugins(PATHS.installedPlugins);
    const pluginRefs = plugins.map((p) => ({ id: p.id, name: p.name }));
    const vaultItems = await listVaultItemsWithProjectState(PATHS.vault, projectDir, pluginRefs, PATHS.claudeDir);
    setItems(vaultItems);
    setPending(new Map());
  };

  useEffect(() => { load(); }, []);

  const filtered = items.filter((i) => filter === "all" || i.type === filter);

  const projectKey = (item: VaultItem) => `project:${item.type}:${item.name}`;
  const globalKey = (item: VaultItem) => `global:${item.type}:${item.name}`;

  const isProjectChecked = (item: VaultItem): boolean => {
    const key = projectKey(item);
    return pending.has(key) ? pending.get(key)! : item.isLinked;
  };

  const isGlobalChecked = (item: VaultItem): boolean => {
    const key = globalKey(item);
    return pending.has(key) ? pending.get(key)! : item.isGlobalLinked;
  };

  const checkedSet = new Set<number>();
  filtered.forEach((item, i) => {
    if (isProjectChecked(item)) checkedSet.add(i);
  });

  const pendingChanges = items.filter((item) => {
    const pk = projectKey(item);
    const gk = globalKey(item);
    return (pending.has(pk) && pending.get(pk) !== item.isLinked)
      || (pending.has(gk) && pending.get(gk) !== item.isGlobalLinked);
  });

  const projectToLink = pendingChanges.filter((i) => pending.get(projectKey(i)) === true && !i.isLinked);
  const projectToUnlink = pendingChanges.filter((i) => pending.get(projectKey(i)) === false && i.isLinked);
  const globalToLink = pendingChanges.filter((i) => pending.get(globalKey(i)) === true && !i.isGlobalLinked);
  const globalToUnlink = pendingChanges.filter((i) => pending.get(globalKey(i)) === false && i.isGlobalLinked);

  const rows = filtered.map((item) => ({
    name: item.name,
    type: item.type,
    project: isProjectChecked(item)
      ? (item.type === "plugin" ? "✓ enabled" : "✓ linked")
      : "─",
    global: isGlobalChecked(item)
      ? (item.type === "plugin" ? "✓ enabled" : "✓ linked")
      : "─",
  }));

  const columns = [
    { key: "name", label: "Name", width: 24 },
    { key: "type", label: "Type", width: 10 },
    { key: "project", label: "Project", width: 12 },
    { key: "global", label: "Global", width: 12 },
  ];

  useInput((input, key) => {
    if (!isFocused || mode !== "list") return;

    if (input === "j" || key.downArrow) {
      setIndex((i) => Math.min(i + 1, filtered.length - 1));
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
    }
    if (input === " " && filtered[index]) {
      const item = filtered[index];
      const k = projectKey(item);
      const current = isProjectChecked(item);
      setPending((prev) => {
        const next = new Map(prev);
        next.set(k, !current);
        return next;
      });
    }
    if (input === "g" && filtered[index]) {
      const item = filtered[index];
      const k = globalKey(item);
      const current = isGlobalChecked(item);
      setPending((prev) => {
        const next = new Map(prev);
        next.set(k, !current);
        return next;
      });
    }
    if (key.return && pendingChanges.length > 0) {
      setMode("confirm");
    }
    if (key.escape) {
      setPending(new Map());
      setStatus("Changes discarded");
    }
    if (key.tab) {
      const idx = FILTERS.indexOf(filter);
      setFilter(FILTERS[(idx + 1) % FILTERS.length]);
      setIndex(0);
    }
    if (input === "m") {
      migrateToVault(PATHS.claudeDir, PATHS.vault).then((r) => {
        setStatus(`Migrated: ${r.moved.length} moved, ${r.skipped.length} skipped`);
        load();
      });
    }
    if (input === "s") {
      syncProject(projectDir, PATHS.vault).then((r) => {
        setStatus(`Synced: +${r.linked.length} -${r.unlinked.length} err:${r.errors.length}`);
        load();
      });
    }
  });

  const applyChanges = async () => {
    let ok = 0;
    let err = 0;
    for (const item of pendingChanges) {
      const pk = projectKey(item);
      const gk = globalKey(item);

      if (pending.has(pk) && pending.get(pk) !== item.isLinked) {
        try {
          if (item.type === "plugin") {
            const plugins = await listInstalledPlugins(PATHS.installedPlugins);
            const plugin = plugins.find((p) => p.name === item.name);
            if (plugin) {
              const projSettings = join(projectDir, ".claude", "settings.json");
              await setPluginEnabled(projSettings, plugin.id, !item.isLinked);
            }
          } else if (!item.isLinked) {
            await linkToProject(projectDir, item);
          } else {
            await unlinkFromProject(projectDir, item);
          }
          ok++;
        } catch { err++; }
      }

      if (pending.has(gk) && pending.get(gk) !== item.isGlobalLinked) {
        try {
          if (item.type === "plugin") {
            const plugins = await listInstalledPlugins(PATHS.installedPlugins);
            const plugin = plugins.find((p) => p.name === item.name);
            if (plugin) {
              await setPluginEnabled(PATHS.settings, plugin.id, !item.isGlobalLinked);
            }
          } else if (!item.isGlobalLinked) {
            await linkToGlobal(PATHS.claudeDir, item);
          } else {
            await unlinkFromGlobal(PATHS.claudeDir, item);
          }
          ok++;
        } catch { err++; }
      }
    }
    setStatus(`Applied: ${ok} changed${err > 0 ? `, ${err} errors` : ""}`);
    await load();
    setMode("list");
  };

  const activeCount = filtered.filter((_, i) => checkedSet.has(i)).length;
  const filterLabel = filter === "all" ? "All" : filter.charAt(0).toUpperCase() + filter.slice(1) + "s";

  return (
    <Box flexDirection="column">
      <Box marginBottom={0}>
        <Text dimColor>
          Filter: {filterLabel} ({filtered.length}) │ {activeCount} project-active
          {pendingChanges.length > 0 ? ` │ ${pendingChanges.length} pending` : ""}
        </Text>
      </Box>

      {items.length === 0 ? (
        <Box marginY={1}>
          <Text>Vault is empty. Press <Text bold>m</Text> to migrate global extensions.</Text>
        </Box>
      ) : (
        <Table
          columns={columns}
          rows={rows}
          selectedIndex={index}
          checked={checkedSet}
        />
      )}

      {status && <Text dimColor>{status}</Text>}

      <Text dimColor>
        Space:project  g:global  Enter:apply  Esc:discard  Tab:filter  m:migrate  s:sync
      </Text>

      {mode === "confirm" && (
        <Confirm
          message={`Project: +${projectToLink.length} -${projectToUnlink.length}. Global: +${globalToLink.length} -${globalToUnlink.length}. Apply?`}
          onConfirm={applyChanges}
          onCancel={() => setMode("list")}
        />
      )}
    </Box>
  );
}
