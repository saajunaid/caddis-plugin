import { useEffect, useId, useRef } from 'react';
import { phaseMeta, type PhaseView } from './roadmap';
import type { Variant } from './RoadmapTab';

/** PR links and the stage of one phase (R46). A number with no GitHub slot is plain text. */
export function PhasePrs({ phase }: { phase: PhaseView }): JSX.Element {
  return (
    <>
      {phase.prs.map((p) =>
        p.url ? (
          <a key={p.number} className="rm-pr mono" data-testid="rm-pr" href={p.url} target="_blank" rel="noreferrer noopener">
            #{p.number}
          </a>
        ) : (
          <span key={p.number} className="rm-pr mono" data-testid="rm-pr">
            #{p.number}
          </span>
        ),
      )}
      <span className={`rm-stage tile-${phase.tile}`} data-testid="rm-stage">
        {phase.stage}
      </span>
    </>
  );
}

export function Pill({ status }: { status: string }): JSX.Element {
  const done = status === 'done' || status === 'not-needed';
  return <span className={`chip ${done ? 'chip-resolved' : status === 'in-progress' ? 'chip-waiting' : 'chip-hub'}`}>{status}</span>;
}

export function PhasePanel({
  detail,
  note = null,
  variant,
  onClose,
}: {
  detail: { title: string; text: string | null; phase: PhaseView } | null;
  note?: 'loading' | 'error' | null;
  variant: Variant;
  onClose: () => void;
}): JSX.Element | null {
  const id = useId();
  const h = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    h.current?.focus();
  }, [detail?.phase.ref]);
  if (!detail) return null;
  const { title, text, phase } = detail;
  const meta = phaseMeta(phase);
  return (
    <aside className="rm-panel" data-testid="rm-panel" role="dialog" aria-modal="false" aria-labelledby={id}>
      <h3 id={id} data-testid="rm-panel-title" tabIndex={-1} ref={h}>
        {phase.ref} {title}
      </h3>
      <button type="button" className="rm-panel-close" data-testid="rm-panel-close" aria-label="Close" onClick={onClose}>
        ×
      </button>
      <Pill status={phase.tile} />
      {phase.tracker && <p data-testid="rm-panel-tracker">{phase.tracker}</p>}
      {meta && <p data-testid="rm-panel-meta">{meta}</p>}
      <div className="rm-panel-prs">
        <PhasePrs phase={phase} />
      </div>
      {variant !== 'site' &&
        (text !== null ? (
          <pre className="rm-panel-text" data-testid="rm-panel-text">
            {text}
          </pre>
        ) : note === 'loading' ? (
          <p data-testid="rm-panel-note">Loading the plan section…</p>
        ) : note === 'error' ? (
          <p data-testid="rm-panel-note">Could not load the plan section.</p>
        ) : (
          <p data-testid="rm-panel-empty">The plan has no section for this phase.</p>
        ))}
    </aside>
  );
}
