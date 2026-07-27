/**
 * Binary detection. Wraps `which`, which honours PATHEXT on Windows so a
 * `claude.cmd` / `agy.exe` shim resolves the same as a POSIX binary
 * (plan risk #5, Windows-first correctness).
 */
import whichModule from 'which';

export async function findBin(name: string): Promise<string | null> {
  try {
    const found = await whichModule(name, { nothrow: true });
    return found ?? null;
  } catch {
    return null;
  }
}
