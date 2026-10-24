/**
 * Local time with the zone (L22). Times are stored in UTC. The locale and the zone are parameters, so a test does not
 * depend on the machine. In the browser both default to the reader's own.
 */
export function localTime(iso: string | null | undefined, locale?: string, zone?: string): string {
  if (!iso) return 'unknown';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'unknown';
  try {
    return new Intl.DateTimeFormat(locale, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
      timeZone: zone,
      timeZoneName: 'short',
    }).format(d);
  } catch {
    return d.toISOString();
  }
}
