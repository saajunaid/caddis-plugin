/**
 * The Motion switch: is the logo animated. `on` by default, also when the OS asks for reduced motion
 * (Windows Server reports it by default). `off` shows the still logo. The switch is the way to stop
 * the moving logo (WCAG 2.2.2), so it is always in the footer.
 */
export type MotionChoice = 'on' | 'off';
export const MOTION_KEY = 'caddis-hub-motion';
export const MOTION_CHOICES: MotionChoice[] = ['on', 'off'];

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

function defaultStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** The saved choice. Any problem (no storage, throwing storage, odd value) gives 'on'. */
export function loadMotion(storage: StorageLike | null = defaultStorage()): MotionChoice {
  try {
    return storage?.getItem(MOTION_KEY) === 'off' ? 'off' : 'on';
  } catch {
    return 'on';
  }
}

/** Save the choice. A throwing storage is ignored: the page works for this visit. */
export function saveMotion(choice: MotionChoice, storage: StorageLike | null = defaultStorage()): void {
  try {
    storage?.setItem(MOTION_KEY, choice);
  } catch {
    /* ignore */
  }
}
