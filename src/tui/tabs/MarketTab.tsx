import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import { Table } from "../components/Table.js";
import { DetailPanel } from "../components/DetailPanel.js";
import { Confirm } from "../components/Confirm.js";
import { PATHS } from "../../core/paths.js";
import {
  listMarketplaces, syncMarketplace, removeMarketplace,
  addMarketplace, parseMarketplaceSource, type MarketplaceInfo,
} from "../../core/marketplace.js";

type Mode = "list" | "syncing" | "confirm-remove" | "add-name" | "add-source";

export function MarketTab() {
  const [markets, setMarkets] = useState<MarketplaceInfo[]>([]);
  const [index, setIndex] = useState(0);
  const [mode, setMode] = useState<Mode>("list");
  const [status, setStatus] = useState("");
  const [addName, setAddName] = useState("");
  const [addSource, setAddSource] = useState("");

  const load = () => listMarketplaces(PATHS.knownMarketplaces).then(setMarkets);
  useEffect(() => { load(); }, []);

  useInput((input, key) => {
    if (mode !== "list") return;
    if (input === "j" || key.downArrow) setIndex((i) => Math.min(i + 1, markets.length - 1));
    if (input === "k" || key.upArrow) setIndex((i) => Math.max(i - 1, 0));
    if (input === "s" && markets[index]) {
      setMode("syncing");
      setStatus(`Syncing ${markets[index].name}...`);
      syncMarketplace(PATHS.knownMarketplaces, markets[index].name)
        .then(() => { setStatus(`Synced "${markets[index].name}"`); return load(); })
        .catch((e: any) => setStatus(`Sync error: ${e.message}`))
        .finally(() => setMode("list"));
    }
    if (input === "r" && markets[index]) setMode("confirm-remove");
    if (input === "a") { setAddName(""); setAddSource(""); setMode("add-name"); }
  });

  const rows = markets.map((m) => {
    const source =
      m.source.source === "github" ? `github:${(m.source as any).repo}`
      : m.source.source === "git" ? `git:${(m.source as any).url}`
      : `dir:${(m.source as any).path}`;
    return { name: m.name, source, updated: m.lastUpdated.slice(0, 10) };
  });

  const selected = markets[index];

  return (
    <Box flexDirection="column">
      <Table
        columns={[
          { key: "name", label: "Marketplace", width: 24 },
          { key: "updated", label: "Updated", width: 12 },
          { key: "source", label: "Source", width: 40 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      {selected ? (
        <DetailPanel
          title={selected.name}
          fields={[
            { label: "Source", value: JSON.stringify(selected.source) },
            { label: "Location", value: selected.installLocation },
            { label: "Updated", value: selected.lastUpdated },
          ]}
          shortcuts="s:sync  r:remove  a:add new"
        />
      ) : (
        <DetailPanel lines={["No marketplace registered. Press 'a' to add one."]} />
      )}

      {mode === "confirm-remove" && selected && (
        <Confirm
          message={`Remove marketplace "${selected.name}"?`}
          onConfirm={async () => {
            try {
              await removeMarketplace(PATHS.knownMarketplaces, PATHS.marketplaces, selected.name);
              setStatus(`Removed "${selected.name}"`);
              setIndex((i) => Math.max(0, i - 1));
              await load();
            } catch (e: any) { setStatus(`Error: ${e.message}`); }
            setMode("list");
          }}
          onCancel={() => setMode("list")}
        />
      )}

      {mode === "add-name" && (
        <Box borderStyle="double" paddingX={1} flexDirection="column">
          <Text bold>Add Marketplace — Step 1/2: Name</Text>
          <Box>
            <Text>Name: </Text>
            <TextInput value={addName} onChange={setAddName} onSubmit={() => {
              if (addName.trim()) setMode("add-source");
            }} />
          </Box>
          <Text dimColor>Enter:next  Ctrl+C:cancel</Text>
        </Box>
      )}

      {mode === "add-source" && (
        <Box borderStyle="double" paddingX={1} flexDirection="column">
          <Text bold>Add Marketplace — Step 2/2: Source</Text>
          <Text dimColor>Format: github:user/repo, git:url, or dir:/path</Text>
          <Box>
            <Text>Source: </Text>
            <TextInput value={addSource} onChange={setAddSource} onSubmit={async (val) => {
              try {
                const src = parseMarketplaceSource(val);
                await addMarketplace(PATHS.knownMarketplaces, PATHS.marketplaces, addName.trim(), src);
                setStatus(`Added "${addName.trim()}"`);
                await load();
              } catch (e: any) { setStatus(`Error: ${e.message}`); }
              setMode("list");
            }} />
          </Box>
          <Text dimColor>Enter:confirm  Ctrl+C:cancel</Text>
        </Box>
      )}

      {status && (
        <Box marginTop={1}><Text dimColor>{status}</Text></Box>
      )}
    </Box>
  );
}
