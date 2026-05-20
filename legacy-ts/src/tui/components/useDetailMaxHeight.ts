import { useStdout } from "ink";

export function useDetailMaxHeight(reservedRows: number, fallback = 24): number {
  const { stdout } = useStdout();
  const rows = stdout?.rows ?? fallback;
  return Math.max(6, rows - reservedRows);
}
