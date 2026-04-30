import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import { Table } from "../components/Table.js";
import { DetailPanel } from "../components/DetailPanel.js";
import { Confirm } from "../components/Confirm.js";
import { PATHS } from "../../core/paths.js";
import { listAllSkills, unlinkSkill, linkSkill, isSymlinkSupported, type SkillInfo } from "../../core/skill.js";

const SOURCE_COLORS: Record<string, string> = {
  user: "cyan",
  project: "green",
  plugin: "magenta",
};

export function SkillsTab() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [index, setIndex] = useState(0);
  const [mode, setMode] = useState<"list" | "confirm-unlink" | "link-input">("list");
  const [linkPath, setLinkPath] = useState("");
  const [status, setStatus] = useState("");
  const symlinkOk = isSymlinkSupported();

  const load = () => listAllSkills({ projectDir: process.cwd() }).then(setSkills);
  useEffect(() => { load(); }, []);

  useInput((input, key) => {
    if (mode !== "list") return;
    if (input === "j" || key.downArrow) setIndex((i) => Math.min(i + 1, skills.length - 1));
    if (input === "k" || key.upArrow) setIndex((i) => Math.max(i - 1, 0));
    if (symlinkOk && input === "u" && skills[index]?.isSymlink && skills[index]?.source === "user") {
      setMode("confirm-unlink");
    }
    if (symlinkOk && input === "l") {
      setLinkPath("");
      setMode("link-input");
    }
  });

  const rows = skills.map((s) => ({
    name: s.name,
    source: s.source,
    type: s.isSymlink ? "symlink" : "dir",
    target: s.isSymlink ? s.target ?? "" : s.path,
  }));

  const selected = skills[index];

  return (
    <Box flexDirection="column">
      <Table
        columns={[
          { key: "name", label: "Skill", width: 28 },
          { key: "source", label: "Source", width: 9 },
          { key: "type", label: "Type", width: 10 },
          { key: "target", label: "Path", width: 35 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      {selected ? (
        <DetailPanel
          title={selected.name}
          fields={[
            { label: "Source", value: selected.source, color: SOURCE_COLORS[selected.source] },
            { label: "Type", value: selected.isSymlink ? "symlink" : "directory" },
            { label: "Path", value: selected.path },
            ...(selected.target ? [{ label: "Target", value: selected.target }] : []),
            ...(selected.plugin ? [{ label: "Plugin", value: selected.plugin }] : []),
          ]}
          shortcuts={symlinkOk ? "u:unlink  l:link" : ""}
        />
      ) : (
        <DetailPanel lines={[symlinkOk ? "No skills found. Press 'l' to link one." : "No skills found."]} />
      )}

      {mode === "confirm-unlink" && selected && (
        <Confirm
          message={`Unlink skill "${selected.name}"?`}
          onConfirm={async () => {
            try {
              await unlinkSkill(PATHS.skills, selected.name);
              setStatus(`Unlinked "${selected.name}"`);
              setIndex((i) => Math.max(0, i - 1));
              await load();
            } catch (e: any) { setStatus(`Error: ${e.message}`); }
            setMode("list");
          }}
          onCancel={() => setMode("list")}
        />
      )}

      {mode === "link-input" && (
        <Box borderStyle="double" paddingX={1} flexDirection="column">
          <Text bold>Link Skill — enter target path:</Text>
          <Box>
            <Text>Path: </Text>
            <TextInput
              value={linkPath}
              onChange={setLinkPath}
              onSubmit={async (val) => {
                try {
                  await linkSkill(PATHS.skills, val);
                  setStatus(`Linked "${val}"`);
                  await load();
                } catch (e: any) { setStatus(`Error: ${e.message}`); }
                setMode("list");
              }}
            />
          </Box>
          <Text dimColor>Enter:confirm  Ctrl+C:cancel</Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text dimColor>
          {skills.length} skill(s) from {new Set(skills.map((s) => s.source)).size} source(s)
          {" | "}
          <Text color="cyan">user</Text> <Text color="green">project</Text>{" "}
          <Text color="magenta">plugin</Text>
        </Text>
        {status && <Text> {status}</Text>}
      </Box>
    </Box>
  );
}
