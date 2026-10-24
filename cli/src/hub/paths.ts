import path from 'node:path';
import { caddisHome } from '../util/sessions.js';

/** The hub data folder: `<home>/.caddis/hub`. Home is `CADDIS_HOME` or the user home (R21). */
export function hubDir(home: string = caddisHome()): string {
  return path.join(home, '.caddis', 'hub');
}

export const configPath = (home?: string): string => path.join(hubDir(home), 'config.json');
export const registryPath = (home?: string): string => path.join(hubDir(home), 'repos.json');
export const keyPath = (home?: string): string => path.join(hubDir(home), 'key');
export const lockPath = (home?: string): string => path.join(hubDir(home), 'hub.lock');
export const auditPath = (home?: string): string => path.join(hubDir(home), 'audit.jsonl');
