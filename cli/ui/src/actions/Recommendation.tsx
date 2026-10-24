import type { OwnerItem } from '../types';

/** D16: a recommendation is shown with who made it, and never as the approval. */
export function RecommendationBlock({ item }: { item: OwnerItem }): JSX.Element {
  const r = item.recommendation;
  const who = item.from ? `from ${item.from}` : item.source === 'coordinator' ? 'from the coordinator' : 'from the asking session';
  return (
    <div className="detail-block recommendation" data-testid="recommendation">
      <span className="detail-label">Recommendation, {who}</span>
      {r ? (
        <>
          <span>
            <strong className={`rec-${r.decision}`}>{r.decision === 'approve' ? 'Approve' : 'Hold'}</strong>
            {r.reason ? `: ${r.reason}` : ''}
          </span>
          {r.evidence && <span className="rec-evidence">Evidence: {r.evidence}</span>}
        </>
      ) : (
        <span>No recommendation was recorded. Read the source before you decide.</span>
      )}
      <span className="rec-note">A recommendation is not an approval. Only your click approves.</span>
    </div>
  );
}
