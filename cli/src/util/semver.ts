/**
 * Ordering for caddis pool versions.
 *
 * WHY THIS EXISTS
 * ---------------
 * Drift used to be a string equality test: `installed === bundled ? 'current' : 'stale'`. Equality
 * cannot tell "older" from "newer", so it got both wrong in opposite directions on the same run
 * (measured 2026-08-16, right after publishing caddis 1.3.74):
 *
 *   Claude Code  1.3.74  (the newest thing on the machine)  ->  "update available"
 *   agy          1.3.54  (twenty releases behind)           ->  "current"
 *
 * The second is merely misleading. The first is harmful: `caddis update` drives anything not
 * `current`, and for agy that means installing this package's OWN bundled pool over whatever is
 * there — so the CLI downgraded agy and reported success.
 *
 * The CLI's bundled pool only moves when the CLI is republished to npm, so it drifts behind the
 * plugin marketplace by design. Comparing against it is fine; treating "different" as "behind" is
 * not.
 */

/** `-1` a is older, `0` equal, `1` a is newer, `null` when either side cannot be ordered. */
export function compareVersions(a: string, b: string): -1 | 0 | 1 | null {
  const pa = parse(a);
  const pb = parse(b);
  if (!pa || !pb) return null;
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const da = pa[i] ?? 0;
    const db = pb[i] ?? 0;
    if (da > db) return 1;
    if (da < db) return -1;
  }
  return 0;
}

/**
 * Numeric release parts only. A version this cannot read returns null rather than a guess, and
 * every caller then falls back to the old equality behaviour — an unreadable version must never
 * silently become an ordering claim, because an ordering claim is what authorises a downgrade.
 *
 * A pre-release suffix (`1.3.74-rc.1`) is deliberately ignored for ordering: caddis has never
 * shipped one, and inventing precedence rules for a case that does not exist adds a way to be
 * wrong with no way to be right.
 */
function parse(v: string): number[] | null {
  if (!v || v === 'unknown') return null;
  const core = v.trim().replace(/^v/, '').split(/[-+]/)[0] ?? '';
  const parts = core.split('.');
  if (parts.length === 0 || parts.some((p) => p === '' || !/^\d+$/.test(p))) return null;
  return parts.map((p) => Number.parseInt(p, 10));
}
