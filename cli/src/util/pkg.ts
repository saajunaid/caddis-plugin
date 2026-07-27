/**
 * Locating the package's own files at runtime.
 *
 * The same code runs from three layouts: `dist/cli.js` (published),
 * `src/**` under vitest/tsx (dev), and a `npm link`ed checkout. Rather than
 * hard-code a `../` depth per layout, walk up from this module until a
 * directory holds our own package.json.
 */
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export interface PackageInfo {
  root: string;
  name: string;
  version: string;
}

function findPackageRoot(startDir: string): string | null {
  let dir = startDir;
  for (let depth = 0; depth < 8; depth += 1) {
    const candidate = path.join(dir, 'package.json');
    if (existsSync(candidate)) {
      try {
        const parsed = JSON.parse(readFileSync(candidate, 'utf8'));
        if (parsed?.name === '@caddis/cli') return dir;
      } catch {
        /* keep walking */
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

let cached: PackageInfo | null = null;

export function packageInfo(): PackageInfo {
  if (cached) return cached;
  const here = path.dirname(fileURLToPath(import.meta.url));
  const root = findPackageRoot(here);
  if (!root) {
    cached = { root: here, name: '@caddis/cli', version: '0.0.0-unknown' };
    return cached;
  }
  const parsed = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
  cached = { root, name: parsed.name, version: parsed.version };
  return cached;
}

/** Absolute path to a shipped bundle directory, or null if it was not packed. */
export function bundlePath(name: string): string | null {
  const dir = path.join(packageInfo().root, 'bundles', name);
  return existsSync(path.join(dir, 'plugin.json')) ? dir : null;
}

export interface BundleManifest {
  poolVersion: string;
  bundles: Record<string, string>;
}

/**
 * The pool version shipped inside this package — what every agent gets driven
 * TO. Read from bundles/manifest.json (written by scripts/copy-bundles.mjs),
 * falling back to the agy bundle's own plugin.json.
 */
export function bundleManifest(): BundleManifest {
  const root = packageInfo().root;
  const manifestFile = path.join(root, 'bundles', 'manifest.json');
  if (existsSync(manifestFile)) {
    try {
      const parsed = JSON.parse(readFileSync(manifestFile, 'utf8'));
      if (parsed?.poolVersion) return { poolVersion: parsed.poolVersion, bundles: parsed.bundles ?? {} };
    } catch {
      /* fall through */
    }
  }
  const agy = bundlePath('antigravity-plugin');
  if (agy) {
    try {
      const parsed = JSON.parse(readFileSync(path.join(agy, 'plugin.json'), 'utf8'));
      if (parsed?.version) {
        return { poolVersion: parsed.version, bundles: { 'antigravity-plugin': parsed.version } };
      }
    } catch {
      /* fall through */
    }
  }
  return { poolVersion: 'unknown', bundles: {} };
}
