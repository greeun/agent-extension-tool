import React from "react";
import { Box, Text } from "ink";

export interface DetailField {
  label: string;
  value: string;
  color?: string;
}

interface Props {
  title?: string;
  fields?: DetailField[];
  shortcuts?: string;
  lines?: string[];
}

export function DetailPanel({ title, fields, shortcuts, lines }: Props) {
  if (lines) {
    return (
      <Box flexDirection="column" marginTop={1} borderStyle="single" paddingX={1}>
        {lines.map((line, i) => (
          <Text key={i}>{line}</Text>
        ))}
      </Box>
    );
  }

  return (
    <Box flexDirection="column" marginTop={1} borderStyle="single" paddingX={1}>
      {title && (
        <Box marginBottom={1}>
          <Text bold color="cyan">{title}</Text>
        </Box>
      )}
      {fields?.map((f, i) => (
        <Box key={i} gap={1}>
          <Text dimColor>{f.label}:</Text>
          <Text color={f.color as any}>{f.value}</Text>
        </Box>
      ))}
      {shortcuts && (
        <Box marginTop={1}>
          <Text dimColor>{shortcuts}</Text>
        </Box>
      )}
    </Box>
  );
}
