import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import { Table } from "../components/Table.js";
import { DetailPanel } from "../components/DetailPanel.js";
import { PATHS } from "../../core/paths.js";
import { listInstalledPlugins, type PluginInfo } from "../../core/plugin.js";
import { readEnabledPlugins, setPluginEnabled } from "../../core/settings.js";
import { RemoveWizard } from "../wizards/RemoveWizard.js";
import { InstallWizard } from "../wizards/InstallWizard.js";

type PluginWithEnabled = PluginInfo & { enabled: boolean };

export function PluginsTab() {
  const [plugins, setPlugins] = useState<PluginWithEnabled[]>([]);
  const [index, setIndex] = useState(0);
  const [wizard, setWizard] = useState<"none" | "install" | "remove">("none");
  const [filter, setFilter] = useState("");
  const [searching, setSearching] = useState(false);
  const [status, setStatus] = useState("");

  const load = async () => {
    const list = await listInstalledPlugins(PATHS.installedPlugins);
    const enabled = await readEnabledPlugins(PATHS.settings);
    setPlugins(list.map((p) => ({ ...p, enabled: enabled[p.id] === true })));
  };

  useEffect(() => { load(); }, []);

  const filtered = filter
    ? plugins.filter((p) => p.name.toLowerCase().includes(filter.toLowerCase()))
    : plugins;

  useInput((input, key) => {
    if (searching) {
      if (key.escape) { setSearching(false); setFilter(""); }
      return;
    }
    if (wizard !== "none") return;
    if (input === "j" || key.downArrow) setIndex((i) => Math.min(i + 1, filtered.length - 1));
    if (input === "k" || key.upArrow) setIndex((i) => Math.max(i - 1, 0));
    if (input === "e" && filtered[index]) {
      const p = filtered[index];
      setPluginEnabled(PATHS.settings, p.id, !p.enabled).then(load);
    }
    if (input === "i") setWizard("install");
    if (input === "r" && filtered[index]) setWizard("remove");
    if (input === "u" && filtered[index]) {
      const p = filtered[index];
      setStatus(`Updating ${p.name}...`);
      const proc = Bun.spawn(["git", "-C", p.installPath, "pull", "--ff-only"], {
        stdout: "pipe", stderr: "pipe",
      });
      proc.exited.then((code) => {
        setStatus(code === 0 ? `Updated "${p.name}"` : `Update failed (exit ${code})`);
        load();
      });
    }
    if (input === "/") { setSearching(true); setFilter(""); setIndex(0); }
  });

  const rows = filtered.map((p) => ({
    name: p.name,
    version: p.version,
    status: p.enabled ? "● active" : "○ off",
    scope: p.scope,
    marketplace: p.marketplace,
  }));

  const selected = filtered[index];

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
        ]}
        rows={rows}
        selectedIndex={index}
      />
      {selected ? (
        <DetailPanel
          title={`${selected.name} ${selected.version}`}
          fields={[
            { label: "Marketplace", value: selected.marketplace },
            { label: "Scope", value: selected.scope },
            { label: "Status", value: selected.enabled ? "● active" : "○ disabled", color: selected.enabled ? "green" : "gray" },
            { label: "Path", value: selected.installPath },
          ]}
          shortcuts="e:enable/disable  r:remove  u:update  i:install  /:search"
        />
      ) : (
        <DetailPanel lines={["No plugin selected"]} />
      )}
      {wizard === "remove" && filtered[index] && (
        <RemoveWizard
          pluginId={filtered[index].id}
          installPath={filtered[index].installPath}
          onDone={() => { setWizard("none"); load(); }}
          onCancel={() => setWizard("none")}
        />
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
