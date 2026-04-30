import React from "react";
import { Box, Text } from "ink";

interface Props {
  data: { label: string; value: number }[];
  maxWidth?: number;
}

export function BarChart({ data, maxWidth = 40 }: Props) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <Box flexDirection="column">
      {data.map((d, i) => {
        const barLen = Math.round((d.value / max) * maxWidth);
        return (
          <Box key={i}>
            <Box width={8}><Text>{d.label}</Text></Box>
            <Text color="cyan">{"█".repeat(barLen)}</Text>
            <Text dimColor> ${d.value.toFixed(0)}</Text>
          </Box>
        );
      })}
    </Box>
  );
}
