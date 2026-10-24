import type { RepoState } from '../types';
import { disabledReason, statusLine, type ActionSpec } from './model';
import type { ActApi } from './useActions';

interface Props {
  repo: RepoState;
  specs: ActionSpec[];
  act: ActApi;
  /** Small buttons and no reason text (Overview cards). The reason stays in the button title. */
  compact?: boolean;
  /** A reason that replaces the repo's own (for example a PR that is not in the queue). */
  reason?: string | null;
}

/** v1 action buttons for one item. With no live coordinator they show disabled with the reason (spec 7 rule 7). */
export function ActionButtons({ repo, specs, act, compact = false, reason: given }: Props): JSX.Element | null {
  if (specs.length === 0) return null;
  const reason = given !== undefined ? given : disabledReason(repo);
  const seen = new Set<string>();
  const lines: { key: string; text: string; tone: string }[] = [];
  for (const s of specs) {
    if (seen.has(s.key)) continue;
    seen.add(s.key);
    const l = statusLine(repo, s, act.local[s.key]);
    if (l) lines.push({ key: s.key, ...l });
  }
  return (
    <div className={`action-row${compact ? ' compact' : ''}`} data-testid="actions">
      <div className="action-buttons">
        {specs.map((s) => (
          <button
            key={`${s.key}:${s.body.action}`}
            type="button"
            className="btn btn-act"
            disabled={reason !== null || act.local[s.key]?.status === 'sending'}
            title={reason ?? undefined}
            onClick={() => act.run(s)}
            data-testid={`act-${s.body.action}`}
          >
            {s.label}
          </button>
        ))}
      </div>
      {reason && !compact && (
        <span className="action-reason" data-testid="action-reason">
          {reason}
        </span>
      )}
      {lines.map((l) => (
        <span key={l.key} className={`request-status tone-${l.tone}`} data-testid="request-status" role="status">
          {l.text}
        </span>
      ))}
    </div>
  );
}
