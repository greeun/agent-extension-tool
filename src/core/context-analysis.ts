function isKorean(code: number): boolean {
  return (code >= 0xAC00 && code <= 0xD7A3) ||
         (code >= 0x3130 && code <= 0x318F) ||
         (code >= 0x1100 && code <= 0x11FF);
}

function isCJK(code: number): boolean {
  return isKorean(code) ||
         (code >= 0x4E00 && code <= 0x9FFF) ||
         (code >= 0x3040 && code <= 0x30FF);
}

export function estimateTokens(text: string): number {
  if (!text) return 0;
  let cjkChars = 0;
  let otherChars = 0;
  for (const char of text) {
    const code = char.codePointAt(0)!;
    if (isCJK(code)) {
      cjkChars++;
    } else {
      otherChars++;
    }
  }
  return Math.ceil(cjkChars / 1.5 + otherChars / 3.5);
}
