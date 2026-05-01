import { useState, useCallback, useRef } from "react";
import { Box, Text } from "ink";
import { DetailPanel, type DetailField } from "./DetailPanel.js";
import { PreviewPanel, previewScrollHandler } from "./PreviewPanel.js";

export type { DetailField } from "./DetailPanel.js";

export type DetailViewMode = "detail" | "preview" | "loading";

/* ── Hook ── */

interface UseDetailViewOptions<T> {
  item: T | undefined;
  previewLoader?: (item: T) => Promise<string[]> | string[];
}

interface UseDetailViewReturn {
  mode: DetailViewMode;
  previewLines: string[] | null;
  previewScroll: number;
  handleInput: (input: string, key: { escape: boolean; return: boolean; downArrow: boolean; upArrow: boolean; pageDown: boolean; pageUp: boolean }) => boolean;
  openPreview: () => void;
  closePreview: () => void;
}

export function useDetailView<T>({ item, previewLoader }: UseDetailViewOptions<T>): UseDetailViewReturn {
  const [mode, setMode] = useState<DetailViewMode>("detail");
  const [previewLines, setPreviewLines] = useState<string[] | null>(null);
  const [previewScroll, setPreviewScroll] = useState(0);
  const loadingRef = useRef(false);

  const openPreview = useCallback(() => {
    if (!item || !previewLoader || loadingRef.current) return;
    const result = previewLoader(item);
    if (result instanceof Promise) {
      loadingRef.current = true;
      setMode("loading");
      result
        .then((lines) => {
          setPreviewLines(lines);
          setPreviewScroll(0);
          setMode("preview");
        })
        .catch(() => {
          setPreviewLines(["(failed to load preview)"]);
          setPreviewScroll(0);
          setMode("preview");
        })
        .finally(() => { loadingRef.current = false; });
    } else {
      setPreviewLines(result);
      setPreviewScroll(0);
      setMode("preview");
    }
  }, [item, previewLoader]);

  const closePreview = useCallback(() => {
    setPreviewLines(null);
    setPreviewScroll(0);
    setMode("detail");
  }, []);

  const handleInput = useCallback((
    input: string,
    key: { escape: boolean; return: boolean; downArrow: boolean; upArrow: boolean; pageDown: boolean; pageUp: boolean },
  ): boolean => {
    if (mode !== "preview" || !previewLines) return false;
    if (key.escape || key.return || input === "q") {
      closePreview();
      return true;
    }
    setPreviewScroll((s) => previewScrollHandler(input, key, s, previewLines.length));
    return true;
  }, [mode, previewLines, closePreview]);

  return { mode, previewLines, previewScroll, handleInput, openPreview, closePreview };
}

/* ── Component ── */

interface DetailViewProps {
  item: unknown | undefined;
  fields: DetailField[];
  title?: string;
  emptyMessage?: string;
  mode?: DetailViewMode;
  previewLines?: string[] | null;
  previewScroll?: number;
  previewTitle?: string;
  previewSubtitle?: string;
  showLineNumbers?: boolean;
  shortcuts?: string;
  previewShortcuts?: string;
}

export function DetailView({
  item,
  fields,
  title,
  emptyMessage = "No items found.",
  mode = "detail",
  previewLines,
  previewScroll = 0,
  previewTitle,
  previewSubtitle,
  showLineNumbers = true,
  shortcuts,
  previewShortcuts,
}: DetailViewProps) {
  if (mode === "preview" && previewLines) {
    return (
      <PreviewPanel
        title={previewTitle ?? ""}
        subtitle={previewSubtitle}
        lines={previewLines}
        scroll={previewScroll}
        showLineNumbers={showLineNumbers}
        shortcuts={previewShortcuts}
      />
    );
  }

  if (mode === "loading") {
    return (
      <Box marginTop={1} borderStyle="single" paddingX={1}>
        <Text color="yellow">Loading preview...</Text>
      </Box>
    );
  }

  if (!item) {
    return <DetailPanel lines={[emptyMessage]} />;
  }

  return (
    <DetailPanel
      title={title}
      fields={fields}
      shortcuts={shortcuts}
    />
  );
}
