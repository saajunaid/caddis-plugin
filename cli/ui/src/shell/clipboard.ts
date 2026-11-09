/** Copy text to the clipboard. The clipboard can be blocked (no secure context, no permission): then nothing happens. */
export function copyText(text: string): void {
  try {
    // writeText rejects (not throws) when permission is denied: catch the promise too.
    void navigator.clipboard?.writeText(text)?.catch(() => undefined);
  } catch {
    /* clipboard can be blocked */
  }
}

/** Copy text and report whether it worked. A denied or missing clipboard gives false, never a rejected promise. */
export async function tryCopy(text: string): Promise<boolean> {
  try {
    if (!navigator.clipboard?.writeText) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
