import { GROUP_ORDER, type PaletteItem } from './items';

export const MAX_RESULTS = 50;

const isWordStart = (s: string, i: number): boolean => i === 0 || !/[a-z0-9]/.test(s[i - 1]!);

/**
 * The score of `token` as a subsequence of `text` (both lower case), or null when it is not one. Each start position
 * of the first character is tried; from there the earliest next match is taken. A matched character scores 1, plus 5
 * when it follows the last match, plus 4 (first character) or 3 (later ones) at the start of a word; a gap costs 0.1 per
 * skipped character.
 */
export function tokenScore(token: string, text: string): number | null {
  let best: number | null = null;
  for (let start = text.indexOf(token[0]!); start !== -1; start = text.indexOf(token[0]!, start + 1)) {
    let score = 1 + (isWordStart(text, start) ? 4 : 0);
    let at = start;
    let ok = true;
    for (let k = 1; k < token.length; k++) {
      const next = text.indexOf(token[k]!, at + 1);
      if (next === -1) {
        ok = false;
        break;
      }
      score += 1 + (next === at + 1 ? 5 : 0) + (isWordStart(text, next) ? 3 : 0) - (next - at - 1) * 0.1;
      at = next;
    }
    // No later start can match when this one ran out of text.
    if (!ok) break;
    if (best === null || score > best) best = score;
  }
  return best;
}

/** The score of one item, or null when a token does not match. A token found only in the keywords counts half. */
function itemScore(item: PaletteItem, tokens: string[]): number | null {
  const label = item.label.toLowerCase();
  const all = `${label} ${item.keywords.join(' ').toLowerCase()}`;
  let total = 0;
  for (const t of tokens) {
    const inLabel = tokenScore(t, label);
    if (inLabel !== null) {
      total += inLabel + (label.startsWith(t) ? 5 : 0);
      continue;
    }
    const inAll = tokenScore(t, all);
    if (inAll === null) return null;
    total += inAll / 2;
  }
  return total - label.length * 0.05;
}

const groupRank = (item: PaletteItem): number => GROUP_ORDER.indexOf(item.group);

/**
 * The palette results for `query`, best first, at most 50. Case-insensitive; every space-separated token must match
 * the label and keywords as a subsequence. Ties keep the group order, then the list order. An empty query gives the
 * list in group order (pages first, then repos).
 */
export function rankItems(items: PaletteItem[], query: string): PaletteItem[] {
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
  const indexed = items.map((item, index) => ({ item, index, score: tokens.length ? itemScore(item, tokens) : 0 }));
  return indexed
    .filter((x): x is { item: PaletteItem; index: number; score: number } => x.score !== null)
    .sort((a, b) => b.score - a.score || groupRank(a.item) - groupRank(b.item) || a.index - b.index)
    .slice(0, MAX_RESULTS)
    .map((x) => x.item);
}

/** Ranked results under group headings: groups in the order of their best result, rows in rank order inside. */
export function groupResults(ranked: PaletteItem[]): [PaletteItem['group'], PaletteItem[]][] {
  const groups = new Map<PaletteItem['group'], PaletteItem[]>();
  for (const item of ranked) {
    const list = groups.get(item.group);
    if (list) list.push(item);
    else groups.set(item.group, [item]);
  }
  return [...groups];
}
