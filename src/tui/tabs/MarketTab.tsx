import { useState, useEffect, useRef } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import { Table } from "../components/Table.js";
import { DetailView } from "../components/DetailView.js";
import { Confirm } from "../components/Confirm.js";
import { PATHS } from "../../core/paths.js";
import {
  listMarketplaces, syncMarketplace, removeMarketplace,
  addMarketplace, parseMarketplaceSource, getLocalVersion, getMarketplaceVersion, pooledMap,
  type MarketplaceInfo, type VersionInfo,
} from "../../core/marketplace.js";

type Mode = "list" | "syncing" | "confirm-remove" | "add-name" | "add-source";

const remoteCache: Record<string, VersionInfo> = {};

interface Props {
  isFocused?: boolean;
  onFocusUp?: () => void;
}

export function MarketTab({ isFocused = true, onFocusUp }: Props) {
  const [markets, setMarkets] = useState<MarketplaceInfo[]>([]);
  const [localVersions, setLocalVersions] = useState<Record<string, string>>({});
  const [remoteVersions, setRemoteVersions] = useState<Record<string, VersionInfo | null>>({ ...remoteCache });
  const [remoteChecking, setRemoteChecking] = useState(false);
  const [index, setIndex] = useState(0);
  const [mode, setMode] = useState<Mode>("list");
  const [status, setStatus] = useState("");
  const [addName, setAddName] = useState("");
  const [addSource, setAddSource] = useState("");
  const mountedRef = useRef(true);
  const fetchGenRef = useRef(0);

  useEffect(() => () => { mountedRef.current = false; }, []);

  const load = async () => {
    const list = await listMarketplaces(PATHS.knownMarketplaces);
    if (!mountedRef.current) return;
    setMarkets(list);
    const vers: Record<string, string> = {};
    for (const m of list) {
      vers[m.name] = await getLocalVersion(PATHS.knownMarketplaces, m.name);
    }
    if (!mountedRef.current) return;
    setLocalVersions(vers);
    return list;
  };

  const checkRemote = (list: MarketplaceInfo[]) => {
    const gen = ++fetchGenRef.current;
    setRemoteChecking(true);
    pooledMap(list, (m) => getMarketplaceVersion(PATHS.knownMarketplaces, m.name), {
      onResult: (m, ver) => {
        if (!mountedRef.current || fetchGenRef.current !== gen) return;
        remoteCache[m.name] = ver;
        setRemoteVersions((prev) => ({ ...prev, [m.name]: ver }));
      },
      onError: (m, error) => {
        if (!mountedRef.current || fetchGenRef.current !== gen) return;
        const ver: VersionInfo = { current: "?", remote: "?", updatable: false, error: error.message };
        remoteCache[m.name] = ver;
        setRemoteVersions((prev) => ({ ...prev, [m.name]: ver }));
      },
    });
  };

  useEffect(() => {
    (async () => {
      const list = await load();
      if (list && list.length > 0) checkRemote(list);
    })();
  }, []);

  const remoteCount = markets.filter((m) => remoteVersions[m.name] != null).length;
  const allChecked = markets.length > 0 && remoteCount >= markets.length;
  useEffect(() => {
    if (allChecked && remoteChecking) {
      setRemoteChecking(false);
      const updatable = Object.values(remoteVersions).filter((v) => v?.updatable).length;
      if (updatable > 0) setStatus(`${updatable} update(s) available`);
    }
  }, [allChecked]);

  useInput((input, key) => {
    if (mode !== "list") return;
    if (!isFocused) return;
    if (input === "j" || key.downArrow) {
      if (markets.length > 0) setIndex((i) => Math.min(i + 1, markets.length - 1));
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
    }
    if (input === "s" && markets[index]) {
      setMode("syncing");
      setStatus(`Syncing ${markets[index].name}...`);
      syncMarketplace(PATHS.knownMarketplaces, markets[index].name)
        .then(async (result) => {
          const msg = result.updated
            ? `Synced "${markets[index].name}" ${result.before} → ${result.after}`
            : `"${markets[index].name}" ${result.after} (up to date)`;
          setStatus(msg);
          const list = await load();
          if (list && list.length > 0) checkRemote(list);
        })
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
    const current = localVersions[m.name] ?? "…";
    const remote = remoteVersions[m.name];
    const version = remote?.error ? "error" : remote?.updatable ? `${current} → ${remote.remote}` : current;
    return { name: m.name, version, source, updated: m.lastUpdated.slice(0, 10) };
  });

  const selected = markets[index];
  const selRemote = selected ? remoteVersions[selected.name] : null;
  const latestLabel = selRemote
    ? (selRemote.error ? `error: ${selRemote.error}` : selRemote.remote)
    : (remoteChecking ? "checking…" : "—");

  return (
    <Box flexDirection="column">
      <Table
        columns={[
          { key: "name", label: "Marketplace", width: 24 },
          { key: "version", label: "Version", width: 18 },
          { key: "updated", label: "Updated", width: 12 },
          { key: "source", label: "Source", width: 34 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      <DetailView
        item={selected}
        title={selected ? `${selected.name} ${localVersions[selected.name] ?? ""}` : undefined}
        fields={selected ? [
          { label: "Current", value: localVersions[selected.name] ?? "…" },
          { label: "Latest", value: latestLabel },
          { label: "Source", value: JSON.stringify(selected.source) },
          { label: "Location", value: selected.installLocation },
          { label: "Updated", value: selected.lastUpdated },
        ] : []}
        emptyMessage="No marketplace registered. Press 'a' to add one."
        shortcuts="s:sync  r:remove  a:add new"
      />

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

      {mode === "syncing" && (
        <Box marginTop={1}><Text color="yellow">{status}</Text></Box>
      )}
      {mode === "list" && status && (
        <Box marginTop={1}><Text dimColor>{status}</Text></Box>
      )}
    </Box>
  );
}
