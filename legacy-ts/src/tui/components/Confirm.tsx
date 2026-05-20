import React from "react";
import { Box, Text, useInput } from "ink";

interface Props {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function Confirm({ message, onConfirm, onCancel }: Props) {
  useInput((input) => {
    if (input === "y" || input === "Y") onConfirm();
    if (input === "n" || input === "N" || input === "q") onCancel();
  });

  return (
    <Box borderStyle="double" paddingX={1} flexDirection="column">
      <Text>{message}</Text>
      <Text dimColor>y:confirm  n:cancel</Text>
    </Box>
  );
}
