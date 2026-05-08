import { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import { Table } from "../components/Table.js";
import { Confirm } from "../components/Confirm.js";
import {
  listVaultItemsWithProjectState,
  linkToProject,
  unlinkFromProject,
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
    const vaultItems = await listVaultItemsWithProjectState(PATHS.vault, projectDir, pluginRefs);
    setItems(vaultItems);
    setPending(new Map());
  };

  useEffect(() => { load(); }, []);

  const filtered = items.filter((i) => filter === "all" || i.type === filter);

  const itemKey = (item: VaultItem) => `${item.type}:${item.name}`;

  const isChecked = (item: VaultItem): boolean => {
    const key = itemKey(item);
    return pending.has(key) ? pending.get(key)! : item.isLinked;
  };

  const checkedSet = new Set<number>();
  filtered.forEach((item, i) => {
    if (isChecked(item)) checkedSet.add(i);
  });

  const pendingChanges = items.filter((item) => {
    const key = itemKey(item);
    return pending.has(key) && pending.get(key) !== item.isLinked;
  });

  const toLink = pendingChanges.filter((i) => !i.isLinked);
  const toUnlink = pendingChanges.filter((i) => i.isLinked);

  const rows = filtered.map((item) => ({
    name: item.name,
    type: item.type,
    status: isChecked(item)
      ? (item.type === "plugin" ? "✓ enabled" : "✓ linked")
      : "─",
  }));

  const columns = [
    { key: "name", label: "Name", width: 28 },
    { key: "type", label: "Type", width: 10 },
    { key: "status", label: "Status", width: 14 },
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
      const k = itemKey(item);
      const current = isChecked(item);
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
      } catch {
        err++;
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
          Filter: {filterLabel} ({filtered.length}) │ {activeCount} active in project
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
        Space:toggle  Enter:apply  Esc:discard  Tab:filter  m:migrate  s:sync
      </Text>

      {mode === "confirm" && (
        <Confirm
          message={`Link ${toLink.length}, Unlink ${toUnlink.length}. Apply?`}
          onConfirm={applyChanges}
          onCancel={() => setMode("list")}
        />
      )}
    </Box>
  );
}
