import React from "react";
import { Box, Text } from "ink";
import { SOURCE_COLORS } from "../constants.js";

interface SourceSummaryProps {
  items: { source: string }[];
  label: string;
  extra?: React.ReactNode;
}

export function SourceSummary({ items, label, extra }: SourceSummaryProps) {
  const sources = Array.from(new Set(items.map((i) => i.source)));
  return (
    <Box marginTop={1}>
      <Text dimColor>
        {items.length} {label}(s) from {sources.length} source(s)
        {" | "}
        {sources.map((s, i) => (
          <React.Fragment key={s}>
            {i > 0 && " "}
            <Text color={SOURCE_COLORS[s] as any}>{s}</Text>
          </React.Fragment>
        ))}
      </Text>
      {extra}
    </Box>
  );
}
