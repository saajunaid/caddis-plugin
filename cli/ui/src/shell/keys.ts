/** True when the event target takes text: keys then belong to the field, not to the page. */
export const isTyping = (t: EventTarget | null): boolean => t instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);

export type InboxKey = 'next' | 'prev' | 'open' | 'copy';

const KEYS: Record<string, InboxKey> = {
  j: 'next',
  J: 'next',
  ArrowDown: 'next',
  k: 'prev',
  K: 'prev',
  ArrowUp: 'prev',
  Enter: 'open',
  c: 'copy',
  C: 'copy',
};

/**
 * The Inbox action of one key press, or null. Keys do nothing while the owner types or holds Ctrl, Meta or Alt
 * (Ctrl+C must copy the selection). Enter on a focused button or link is left to its native click.
 */
export function inboxKey(
  key: string,
  mods: { ctrl: boolean; meta: boolean; alt: boolean },
  typing: boolean,
  onControl: boolean,
): InboxKey | null {
  if (typing || mods.ctrl || mods.meta || mods.alt) return null;
  const action = Object.hasOwn(KEYS, key) ? KEYS[key]! : null;
  if (action === 'open' && onControl) return null;
  return action;
}

/** The next or previous row index, clamped to the list (no wrap). An empty list gives -1. */
export function moveIndex(action: 'next' | 'prev', index: number, length: number): number {
  if (length <= 0) return -1;
  const to = action === 'next' ? index + 1 : index - 1;
  return Math.min(length - 1, Math.max(0, to));
}
