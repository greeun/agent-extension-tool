import { useState, useEffect } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import TextInput from "ink-text-input";
import { Table } from "../components/Table.js";
import { DetailView } from "../components/DetailView.js";
import { SourceSummary } from "../components/SourceSummary.js";
import { Confirm } from "../components/Confirm.js";
import { SOURCE_COLORS } from "../constants.js";
import { PATHS } from "../../core/paths.js";
import { listAllSkills, unlinkSkill, linkSkill, isSymlinkSupported, type SkillInfo } from "../../core/skill.js";
import { getProjectCount, type UsageIndex } from "../../core/project-usage.js";
import { useDetailScroll } from "../components/useDetailScroll.js";
import { useDetailMaxHeight } from "../components/useDetailMaxHeight.js";
import { flattenDetailFields } from "../components/flattenDetailFields.js";

interface Props {
  isFocused?: boolean;
  onFocusUp?: () => void;
  usageIndex?: UsageIndex;
}

export function SkillsTab({ isFocused = true, onFocusUp, usageIndex }: Props) {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [index, setIndex] = useState(0);
  const [mode, setMode] = useState<"list" | "confirm-unlink" | "link-input">("list");
  const [linkPath, setLinkPath] = useState("");
  const [status, setStatus] = useState("");
  const symlinkOk = isSymlinkSupported();

  const load = () => listAllSkills({ projectDir: process.cwd() }).then(setSkills);
  useEffect(() => { load(); }, []);

  const rows = skills.map((s) => {
    const count = usageIndex ? getProjectCount(usageIndex, "skill", s.name) : 0;
    return {
      name: s.name,
      source: s.source,
      type: s.isSymlink ? "symlink" : "dir",
      target: s.isSymlink ? s.target ?? "" : s.path,
      projects: count > 0 ? `${count}` : "─",
    };
  });

  const selected = skills[index];

  const { stdout } = useStdout();
  const cols = stdout?.columns ?? 80;
  const detailFields = selected ? [
    { label: "Source", value: selected.source, color: SOURCE_COLORS[selected.source] },
    { label: "Type", value: selected.isSymlink ? "symlink" : "directory" },
    { label: "Path", value: selected.path },
    ...(selected.target ? [{ label: "Target", value: selected.target }] : []),
    ...(selected.plugin ? [{ label: "Plugin", value: selected.plugin }] : []),
  ] : [];
  const detailMaxHeight = useDetailMaxHeight(10);
  const flat = flattenDetailFields(detailFields, cols - 4);
  const viewport = Math.max(1, detailMaxHeight - 4);
  const detailScroll = useDetailScroll({
    totalLines: flat.length,
    viewportLines: viewport,
    resetKey: selected?.path,
  });

  useInput((input, key) => {
    if (mode !== "list") return;
    if (!isFocused) return;
    if (detailScroll.handleInput(input, key)) return;
    if (input === "j" || key.downArrow) {
      if (skills.length > 0) setIndex((i) => Math.min(i + 1, skills.length - 1));
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
    }
    if (symlinkOk && input === "u" && skills[index]?.isSymlink && skills[index]?.source === "user") {
      setMode("confirm-unlink");
    }
    if (symlinkOk && input === "l") {
      setLinkPath("");
      setMode("link-input");
    }
  });

  return (
    <Box flexDirection="column">
      <Table
        columns={[
          { key: "name", label: "Skill", width: 24 },
          { key: "source", label: "Source", width: 9 },
          { key: "type", label: "Type", width: 8 },
          { key: "projects", label: "Proj", width: 6 },
          { key: "target", label: "Path", width: 35 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      <DetailView
        item={selected}
        title={selected?.name}
        fields={detailFields}
        emptyMessage={symlinkOk ? "No skills found. Press 'l' to link one." : "No skills found."}
        shortcuts={(symlinkOk ? "u:unlink  l:link  " : "") + "Enter:detail  Esc:back  j/k:scroll"}
        detailFocused={detailScroll.focused}
        detailScroll={detailScroll.scroll}
        detailMaxHeight={detailMaxHeight}
        detailContentWidth={cols - 4}
      />

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

      <SourceSummary
        items={skills}
        label="skill"
        extra={status ? <Text> {status}</Text> : undefined}
      />
    </Box>
  );
}
