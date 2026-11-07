// One open PR head, as the collector's --prs-file holds it (plan D2). Used by the hub (github.ts, collector.ts) and the export.
export interface PrHead { number: number; head_ref: string; draft: boolean; fork: boolean; updated_at: string }
