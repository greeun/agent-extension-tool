/**
 * Display locale for all axt TUI date/time/number rendering.
 *
 * Fixed to English, independent of `config.locale` and the OS locale,
 * so the TUI always renders in English. The CLI continues to honor
 * `config.locale`.
 */
export const TUI_LOCALE = "en-US";
