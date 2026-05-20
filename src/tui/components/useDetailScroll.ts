import { useState, useCallback, useEffect } from "react";

export interface UseDetailScrollOptions {
  totalLines: number;
  viewportLines: number;
  resetKey?: unknown;
}

export interface InkKeyLike {
  return: boolean;
  escape: boolean;
  downArrow: boolean;
  upArrow: boolean;
  pageDown: boolean;
  pageUp: boolean;
}

export interface UseDetailScrollReturn {
  focused: boolean;
  scroll: number;
  handleInput: (input: string, key: InkKeyLike) => boolean;
  focus: () => void;
  blur: () => void;
}

export function useDetailScroll({
  totalLines,
  viewportLines,
  resetKey,
}: UseDetailScrollOptions): UseDetailScrollReturn {
  const [focused, setFocused] = useState(false);
  const [scroll, setScroll] = useState(0);
  const maxScroll = Math.max(0, totalLines - viewportLines);

  useEffect(() => {
    setScroll(0);
  }, [resetKey]);

  // Clamp scroll if total shrinks under the current position.
  useEffect(() => {
    setScroll((s) => Math.min(s, maxScroll));
  }, [maxScroll]);

  const focus = useCallback(() => setFocused(true), []);
  const blur = useCallback(() => { setFocused(false); setScroll(0); }, []);

  const handleInput = useCallback((_input: string, key: InkKeyLike): boolean => {
    if (!focused) {
      if (key.return && totalLines > 0) {
        setFocused(true);
        return true;
      }
      return false;
    }
    if (key.escape) {
      setFocused(false);
      setScroll(0);
      return true;
    }
    if (_input === "j" || key.downArrow) {
      setScroll((s) => Math.min(s + 1, maxScroll));
      return true;
    }
    if (_input === "k" || key.upArrow) {
      setScroll((s) => Math.max(s - 1, 0));
      return true;
    }
    if (key.pageDown) {
      setScroll((s) => Math.min(s + Math.max(1, viewportLines), maxScroll));
      return true;
    }
    if (key.pageUp) {
      setScroll((s) => Math.max(s - Math.max(1, viewportLines), 0));
      return true;
    }
    // While focused, swallow other input so list/tab keys don't trigger.
    return true;
  }, [focused, totalLines, viewportLines, maxScroll]);

  return { focused, scroll, handleInput, focus, blur };
}
