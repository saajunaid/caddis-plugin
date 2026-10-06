/** Report only a real selection change. */
export function notifySelection(previous: string | null, next: string | null, onSelect?: (id: string | null) => void): void {
  if (previous !== next) onSelect?.(next);
}
