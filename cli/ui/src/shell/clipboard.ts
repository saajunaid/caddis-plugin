/** Copy text to the clipboard. The clipboard can be blocked (no secure context, no permission): then nothing happens. */
export function copyText(text: string): void {
  try {
    // writeText rejects (not throws) when permission is denied: catch the promise too.
    void navigator.clipboard?.writeText(text)?.catch(() => undefined);
  } catch {
    /* clipboard can be blocked */
  }
}
