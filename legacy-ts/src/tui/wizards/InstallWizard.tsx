import React, { useState } from "react";
import { Box, Text, useInput } from "ink";
import { SearchInput } from "../components/SearchInput.js";

interface Props {
  onDone: () => void;
  onCancel: () => void;
}

export function InstallWizard({ onDone, onCancel }: Props) {
  const [query, setQuery] = useState("");
  const [step, setStep] = useState<"search" | "results">("search");

  useInput((input, key) => {
    if (key.escape) onCancel();
  });

  return (
    <Box flexDirection="column" borderStyle="double" paddingX={1}>
      <Text bold>Install Plugin (Step 1/3: Search)</Text>
      <SearchInput
        value={query}
        onChange={setQuery}
        onSubmit={() => setStep("results")}
      />
      {step === "results" && (
        <Box flexDirection="column" marginTop={1}>
          <Text dimColor>
            Search across marketplaces requires sync. Run: ccx market sync
          </Text>
          <Text dimColor>Esc: cancel</Text>
        </Box>
      )}
    </Box>
  );
}
