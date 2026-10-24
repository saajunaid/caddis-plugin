export type ThemeChoice = 'dark' | 'light' | 'system';
export const THEME_KEY = 'caddis-hub-theme';
export const THEME_CHOICES: ThemeChoice[] = ['dark', 'light', 'system'];

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

function defaultStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** The saved choice. Any problem (no storage, throwing storage, odd value) gives 'system'. */
export function loadTheme(storage: StorageLike | null = defaultStorage()): ThemeChoice {
  try {
    const v = storage?.getItem(THEME_KEY);
    return v === 'dark' || v === 'light' || v === 'system' ? v : 'system';
  } catch {
    return 'system';
  }
}

/** Save the choice. A throwing storage is ignored: the page works for this visit. */
export function saveTheme(choice: ThemeChoice, storage: StorageLike | null = defaultStorage()): void {
  try {
    storage?.setItem(THEME_KEY, choice);
  } catch {
    /* ignore */
  }
}

export function resolveTheme(choice: ThemeChoice, prefersDark: boolean): 'dark' | 'light' {
  return choice === 'system' ? (prefersDark ? 'dark' : 'light') : choice;
}
