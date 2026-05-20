import React from "react";
import { Box, Text, useInput } from "ink";

interface Props {
  onClose: () => void;
}

export function HelpPopup({ onClose }: Props) {
  useInput((input, key) => {
    if (input === "?" || input === "q" || key.escape || key.return) {
      onClose();
    }
  });

  return (
    <Box
      flexDirection="column"
      borderStyle="double"
      borderColor="cyan"
      paddingX={2}
      paddingY={1}
    >
      <Text bold color="cyan">
        axt — Agent eXtension Tool
      </Text>
      <Text> </Text>
      <Text bold>Navigation</Text>
      <Text>  ← →          Switch tab (main or extensions sub-tab)</Text>
      <Text>  ↑/↓           Navigate focus level / scroll list</Text>
      <Text>  1-7           Jump to main tab</Text>
      <Text>  j/k           Scroll list</Text>
      <Text> </Text>
      <Text bold>Main Tabs</Text>
      <Text>  1 Extensions  Skills, Hooks, Commands, Agents, Plugins, Marketplace, Vault</Text>
      <Text>  2 Project     Project context (CLAUDE.md, settings, memory)</Text>
      <Text>  3 Dashboard   All platforms summary + cost projection</Text>
      <Text>  4 Claude      Claude Code usage (tokens, cost, blocks)</Text>
      <Text>  5 Codex       OpenAI Codex CLI usage</Text>
      <Text>  6 Gemini      Google Gemini CLI usage</Text>
      <Text>  7 Cursor      Cursor IDE AI code metrics</Text>
      <Text> </Text>
      <Text bold>Extensions Shortcuts</Text>
      <Text>  Skills:       u:unlink  l:link</Text>
      <Text>  Plugins:      e:enable/disable  r:remove  u:update  i:install  /:search</Text>
      <Text>  Marketplace:  s:sync  r:remove  a:add</Text>
      <Text>  Vault:        Space:project  g:global  Enter:apply  Esc:discard  Tab:filter  m:migrate  s:sync</Text>
      <Text> </Text>
      <Text bold>General</Text>
      <Text>  r             Refresh data</Text>
      <Text>  ?             This help</Text>
      <Text>  q / Esc       Quit</Text>
      <Text> </Text>
      <Text dimColor>Press ? or Esc to close</Text>
    </Box>
  );
}
