import { useState, useEffect } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import TextInput from "ink-text-input";
import { Table } from "../components/Table.js";
import { DetailPanel } from "../components/DetailPanel.js";
import { Confirm } from "../components/Confirm.js";
import {
  listVaultItemsWithProjectState,
  linkToProject,
  unlinkFromProject,
  linkToGlobal,
  unlinkFromGlobal,
  importToVault,
  migrateToVault,
  syncProject,
} from "../../core/vault.js";
import { listInstalledPlugins } from "../../core/plugin.js";
import { setPluginEnabled } from "../../core/settings.js";
import { PATHS } from "../../core/paths.js";
import { scanProjectUsage, getProjects, type UsageIndex, type ProjectRef } from "../../core/project-usage.js";
import type { VaultItem } from "../../core/vault.js";
import { join } from "path";

type FilterType = "all" | "skill" | "command" | "agent" | "plugin";
const FILTERS: FilterType[] = ["all", "skill", "command", "agent", "plugin"];

type SortKey = "name" | "added" | "updated" | "type" | "vault" | "project" | "global";
const SORT_KEYS: SortKey[] = ["name", "added", "updated", "type", "vault", "project", "global"];
const SORT_LABELS: Record<SortKey, string> = {
  name: "Name", added: "Added", updated: "Updated", type: "Type", vault: "Vault", project: "Project", global: "Global",
};

type ScanMode = "default" | "full";

function formatDate(d?: Date): string {
  if (!d || d.getTime() === 0) return "─";
  const y = d.getFullYear().toString().slice(2);
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day} ${h}:${min}`;
}

interface Props {
  isFocused: boolean;
  onFocusUp?: () => void;
  onSubViewChange?: (inSubView: boolean) => void;
}

export function VaultTab({ isFocused, onFocusUp, onSubViewChange }: Props) {
  const { stdout } = useStdout();
  const [items, setItems] = useState<VaultItem[]>([]);
  const [index, setIndex] = useState(0);
  const [filter, setFilter] = useState<FilterType>("all");
  const [pending, setPending] = useState<Map<string, boolean>>(new Map());
  const [mode, setMode] = useState<"list" | "confirm">("list");
  const [status, setStatus] = useState("");
  const [projectDir] = useState(() => process.cwd());
  const [usageIndex, setUsageIndex] = useState<UsageIndex>(new Map());
  const [scanMode, setScanMode] = useState<ScanMode>("default");
  const [scanning, setScanning] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("updated");
  const [searchTerm, setSearchTerm] = useState("");
  const [searching, setSearching] = useState(false);

  useEffect(() => { onSubViewChange?.(searching); }, [searching]);

  const load = async () => {
    const plugins = await listInstalledPlugins(PATHS.installedPlugins);
    const pluginRefs = plugins.map((p) => ({ id: p.id, name: p.name, description: p.description, installPath: p.installPath }));
    const vaultItems = await listVaultItemsWithProjectState(PATHS.vault, projectDir, pluginRefs, PATHS.claudeDir);
    setItems(vaultItems);
    setPending(new Map());
  };

  const loadUsage = async (m: ScanMode) => {
    setScanning(true);
    setStatus(`Scanning projects (${m})...`);
    const idx = await scanProjectUsage(PATHS.projects, PATHS.vault, m);
    setUsageIndex(idx);
    setScanning(false);
    setStatus(`Scan complete: ${idx.size} extensions found across projects`);
  };

  useEffect(() => { load(); loadUsage("default"); }, []);

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

  const filtered = items
    .filter((i) => filter === "all" || i.type === filter)
    .filter((i) => !searchTerm || i.name.toLowerCase().includes(searchTerm.toLowerCase()))
    .sort((a, b) => {
      switch (sortKey) {
        case "name": return a.name.localeCompare(b.name);
        case "added": return (b.createdAt?.getTime() ?? 0) - (a.createdAt?.getTime() ?? 0);
        case "updated": return (b.updatedAt?.getTime() ?? 0) - (a.updatedAt?.getTime() ?? 0);
        case "type": return a.type.localeCompare(b.type) || a.name.localeCompare(b.name);
        case "vault": {
          const av = (a.inVault !== false) ? 0 : 1;
          const bv = (b.inVault !== false) ? 0 : 1;
          return av - bv || a.name.localeCompare(b.name);
        }
        case "project": {
          const ap = isProjectChecked(a) ? 0 : 1;
          const bp = isProjectChecked(b) ? 0 : 1;
          return ap - bp || a.name.localeCompare(b.name);
        }
        case "global": {
          const ag = isGlobalChecked(a) ? 0 : 1;
          const bg = isGlobalChecked(b) ? 0 : 1;
          return ag - bg || a.name.localeCompare(b.name);
        }
        default: return 0;
      }
    });

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

  const selectedItem = filtered[index];
  const selectedProjects: ProjectRef[] = selectedItem
    ? getProjects(usageIndex, selectedItem.type, selectedItem.name)
    : [];

  const rows = filtered.map((item, i) => {
    const count = getProjects(usageIndex, item.type, item.name).length;
    return {
      no: String(i + 1),
      name: item.name,
      type: item.type,
      vault: item.inVault !== false ? "✓" : "─",
      added: formatDate(item.createdAt),
      updated: formatDate(item.updatedAt),
      project: isProjectChecked(item)
        ? (item.type === "plugin" ? "✓ enabled" : "✓ linked")
        : "─",
      global: isGlobalChecked(item)
        ? (item.type === "plugin" ? "✓ enabled" : "✓ linked")
        : "─",
      used: count > 0 ? `${count} proj` : "─",
    };
  });

  const termCols = (stdout?.columns ?? 80) - 2;
  const colGap = 2;
  const noWidth = Math.max(2, String(filtered.length).length + 1);
  const fixedWidth = 4 + noWidth + 7 + 7 + 14 + 14 + 9 + 9 + 8 + 8 * colGap;
  const nameWidth = Math.max(10, termCols - fixedWidth - 2);
  const sortIndicator = (key: SortKey) => sortKey === key ? " ▾" : "";
  const columns = [
    { key: "no", label: "#", width: noWidth },
    { key: "name", label: "Name" + sortIndicator("name"), width: nameWidth },
    { key: "type", label: "Type" + sortIndicator("type"), width: 7 },
    { key: "vault", label: "Vault" + sortIndicator("vault"), width: 7 },
    { key: "added", label: "Added" + sortIndicator("added"), width: 14 },
    { key: "updated", label: "Updated" + sortIndicator("updated"), width: 14 },
    { key: "project", label: "Project" + sortIndicator("project"), width: 9 },
    { key: "global", label: "Global" + sortIndicator("global"), width: 9 },
    { key: "used", label: "Used in", width: 8 },
  ];

  useInput((input, key) => {
    if (!isFocused || mode !== "list") return;

    if (searching) {
      if (key.escape) { setSearching(false); setSearchTerm(""); }
      return;
    }

    if (input === "j" || key.downArrow) {
      setIndex((i) => Math.min(i + 1, filtered.length - 1));
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
    }
    if (key.pageDown) {
      setIndex((i) => Math.min(i + 10, filtered.length - 1));
    }
    if (key.pageUp) {
      setIndex((i) => Math.max(i - 10, 0));
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
    if (input === "S") {
      syncProject(projectDir, PATHS.vault).then((r) => {
        setStatus(`Synced: +${r.linked.length} -${r.unlinked.length} err:${r.errors.length}`);
        load();
      });
    }
    if (input === "s") {
      const idx = SORT_KEYS.indexOf(sortKey);
      const next = SORT_KEYS[(idx + 1) % SORT_KEYS.length];
      setSortKey(next);
      setIndex(0);
    }
    if (input === "i" && filtered[index] && filtered[index].inVault === false) {
      const item = filtered[index];
      setStatus(`Importing "${item.name}" to vault...`);
      importToVault(PATHS.claudeDir, PATHS.vault, item).then(() => {
        setStatus(`Imported "${item.name}" to vault`);
        load();
      }).catch((e: any) => {
        setStatus(`Import failed: ${e.message}`);
      });
    }
    if (input === "f" && !scanning) {
      const next: ScanMode = scanMode === "default" ? "full" : "default";
      setScanMode(next);
      loadUsage(next);
    }
    if (input === "/") { setSearching(true); setSearchTerm(""); setIndex(0); }
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
  const scanLabel = scanMode === "full" ? "full" : "profile+symlink";


  return (
    <Box flexDirection="column">
      <Text><Text dimColor>Project: </Text><Text bold color="cyan">{projectDir}</Text></Text>
      <Box marginBottom={0} gap={1}>
        {FILTERS.map((f) => {
          const label = f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1) + "s";
          return (
            <Text key={f} inverse={f === filter} bold={f === filter} dimColor={f !== filter}>
              {` ${label} `}
            </Text>
          );
        })}
        <Text dimColor>
          ({filtered.length}) | {activeCount} active
          {pendingChanges.length > 0 ? ` | ${pendingChanges.length} pending` : ""}
          {" "}| scan: {scanLabel}{scanning ? " ..." : ""}
        </Text>
      </Box>

      {searching && (
        <Box marginBottom={0}>
          <Text>Search: </Text>
          <TextInput value={searchTerm} onChange={(v) => { setSearchTerm(v); setIndex(0); }} onSubmit={() => setSearching(false)} />
          <Text dimColor>  Enter:apply  Esc:clear</Text>
        </Box>
      )}
      {!searching && searchTerm && (
        <Box marginBottom={0}>
          <Text dimColor>Search: "{searchTerm}" ({filtered.length}/{items.filter((i) => filter === "all" || i.type === filter).length})  /:edit</Text>
        </Box>
      )}

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
          maxRows={Math.max(3, (stdout?.rows ?? 24) - 31)}
          gap={colGap}
        />
      )}

      <DetailPanel
        title={selectedItem ? `${selectedItem.name} (${selectedItem.type})` : "No item selected"}
        fields={selectedItem ? [
          { label: "Description", value: selectedItem.description || "—" },
          { label: "Extension path", value: selectedItem.path || "—" },
          { label: "Added", value: selectedItem.createdAt ? selectedItem.createdAt.toLocaleString() : "—" },
          { label: "Updated", value: selectedItem.updatedAt ? selectedItem.updatedAt.toLocaleString() : "—" },
          { label: "Vault", value: selectedItem.inVault !== false ? "in vault" : "global only (press i to import)" },
          { label: "Project", value: isProjectChecked(selectedItem) ? (selectedItem.type === "plugin" ? "enabled" : "linked") : "not linked" },
          { label: "Global", value: isGlobalChecked(selectedItem) ? (selectedItem.type === "plugin" ? "enabled" : "linked") : "not linked" },
          { label: "Used in", value: selectedProjects.length > 0 ? selectedProjects.map((p) => p.name).join(", ") : "—" },
        ] : []}
      />

      <Text dimColor>{`j/k:navigate  PgUp/PgDn:page  Space:project  g:global  i:import  /:search  s:sort(${SORT_LABELS[sortKey]})  Enter:apply  Esc:discard  Tab:filter  f:scan  m:migrate  S:sync`}</Text>
      {(status || pendingChanges.length > 0) && (
        <Text dimColor>
          {[
            status,
            pendingChanges.length > 0 ? `Pending: ${[
              projectToLink.length > 0 ? `+${projectToLink.length} project` : "",
              projectToUnlink.length > 0 ? `-${projectToUnlink.length} project` : "",
              globalToLink.length > 0 ? `+${globalToLink.length} global` : "",
              globalToUnlink.length > 0 ? `-${globalToUnlink.length} global` : "",
            ].filter(Boolean).join(", ")}` : "",
          ].filter(Boolean).join("  |  ")}
        </Text>
      )}

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
