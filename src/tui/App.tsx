import { useState, useEffect } from "react";
import { render, Box, Text, useInput, useApp, useStdout } from "ink";
import { TabBar, type TabName, TABS } from "./components/TabBar.js";
import { HelpPopup } from "./components/HelpPopup.js";
import { OverviewTab } from "./tabs/OverviewTab.js";
import { UsageTab } from "./tabs/UsageTab.js";
import { CursorTab } from "./tabs/CursorTab.js";
import { ExtensionsTab } from "./tabs/ExtensionsTab.js";
import { ProjectTab } from "./tabs/ProjectTab.js";
import { ContextTab } from "./tabs/ContextTab.js";

function useTerminalSize() {
  const { stdout } = useStdout();
  const [size, setSize] = useState({
    columns: stdout?.columns ?? 80,
    rows: stdout?.rows ?? 24,
  });

  useEffect(() => {
    if (!stdout) return;
    const onResize = () => {
      setSize({ columns: stdout.columns, rows: stdout.rows });
    };
    stdout.on("resize", onResize);
    return () => { stdout.off("resize", onResize); };
  }, [stdout]);

  return size;
}

function App() {
  const [tab, setTab] = useState<TabName>("extensions");
  const [focusLayer, setFocusLayer] = useState<"mainTab" | "subTab" | "content">("content");
  const [showHelp, setShowHelp] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [contextInSubView, setContextInSubView] = useState(false);
  const [extensionsInSubView, setExtensionsInSubView] = useState(false);
  const { exit } = useApp();
  const { columns: termWidth, rows: termHeight } = useTerminalSize();

  useInput((input, key) => {
    if (showHelp) return;
    if (input === "q" || key.escape) {
      if (tab === "context" && contextInSubView) return;
      if (tab === "extensions" && extensionsInSubView) return;
      if (tab === "claude" && focusLayer !== "mainTab") {
        setFocusLayer(focusLayer === "content" ? "subTab" : "mainTab");
        return;
      }
      exit();
    }
    if (input === "?") { setShowHelp(true); return; }
    if (input === "r") { setRefreshKey((k) => k + 1); return; }

    if (focusLayer === "mainTab" && (key.downArrow || key.return)) {
      setFocusLayer(tab === "extensions" || tab === "claude" ? "subTab" : "content");
      return;
    }

    const tabDefaultFocus = (t: TabName) => (t === "claude" ? "subTab" : "content") as "subTab" | "content";

    if (key.leftArrow) {
      if ((tab === "extensions" || tab === "claude") && focusLayer !== "mainTab") return;
      const idx = TABS.findIndex((t) => t.key === tab);
      const next = TABS[(idx - 1 + TABS.length) % TABS.length];
      setTab(next.key);
      setFocusLayer(tabDefaultFocus(next.key));
    }
    if (key.rightArrow) {
      if ((tab === "extensions" || tab === "claude") && focusLayer !== "mainTab") return;
      const idx = TABS.findIndex((t) => t.key === tab);
      const next = TABS[(idx + 1) % TABS.length];
      setTab(next.key);
      setFocusLayer(tabDefaultFocus(next.key));
    }

    const num = parseInt(input);
    if (num >= 1 && num <= TABS.length) {
      const next = TABS[num - 1];
      setTab(next.key);
      setFocusLayer(tabDefaultFocus(next.key));
    }
  });

  const contentHeight = termHeight - 2;

  if (showHelp) {
    return (
      <Box flexDirection="column" height={termHeight}>
        <TabBar active={tab} focused={focusLayer === "mainTab"} />
        <Box height={1} overflow="hidden"><Text dimColor>{"─".repeat(termWidth)}</Text></Box>
        <Box height={contentHeight} justifyContent="center" alignItems="center" overflow="hidden">
          <HelpPopup onClose={() => setShowHelp(false)} />
        </Box>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" height={termHeight}>
      <TabBar active={tab} focused={focusLayer === "mainTab"} />
      <Box height={1} overflow="hidden"><Text dimColor>{"─".repeat(termWidth)}</Text></Box>
      <Box flexDirection="column" height={contentHeight} paddingX={1} paddingY={1} overflow="hidden">
        {tab === "extensions" && <ExtensionsTab focusLayer={focusLayer} setFocusLayer={setFocusLayer} onSubViewChange={setExtensionsInSubView} />}
        {tab === "context" && <ContextTab key={`context-${refreshKey}`} onSubViewChange={setContextInSubView} />}
        {tab === "project" && <ProjectTab key={refreshKey} isFocused={focusLayer === "content"} onFocusUp={() => setFocusLayer("mainTab")} />}
        {tab === "dashboard" && <OverviewTab key={refreshKey} />}
        {tab === "claude" && <UsageTab platform="claude" isFocused refreshKey={refreshKey} focusLayer={focusLayer} setFocusLayer={setFocusLayer} />}
        {tab === "codex" && <UsageTab platform="codex" isFocused refreshKey={refreshKey} />}
        {tab === "gemini" && <UsageTab platform="gemini" isFocused refreshKey={refreshKey} />}
        {tab === "cursor" && <CursorTab isFocused={focusLayer === "content"} onFocusUp={() => setFocusLayer("mainTab")} refreshKey={refreshKey} />}
      </Box>
    </Box>
  );
}

export async function launchTui() {
  process.stdout.write("\x1b[?1049h");
  process.stdout.write("\x1b[H\x1b[2J");

  const instance = render(<App />);

  try {
    await instance.waitUntilExit();
  } finally {
    process.stdout.write("\x1b[?1049l");
  }
}
