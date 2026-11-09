import { formatEur, spendView } from './format';

export type RingTone = 'good' | 'prog' | 'warn' | 'muted';

/** The `stroke-dasharray` of a progress ring: the filled arc, then the whole circle. The fraction is clamped to
    0..1 and NaN counts as 0, so a repo with no data draws an empty ring, never a broken one. */
export function ringDash(fraction: number, r: number): string {
  const f = Number.isNaN(fraction) ? 0 : Math.min(1, Math.max(0, fraction));
  const c = 2 * Math.PI * r;
  return `${(c * f).toFixed(1)} ${c.toFixed(1)}`;
}

interface RingProps {
  fraction: number;
  size: number;
  stroke?: number;
  tone: RingTone;
  label: string;
  text?: string;
}

/** A progress ring (SVG presentation attributes only: the CSP has no inline style). */
export function Ring({ fraction, size, stroke = 5, tone, label, text }: RingProps): JSX.Element {
  const c = size / 2;
  const r = c - stroke / 2 - 1.5;
  return (
    <svg className={`ring ring-${tone}`} width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label}>
      <circle className="ring-track" cx={c} cy={c} r={r} fill="none" strokeWidth={stroke} />
      <circle
        className="ring-fill"
        cx={c}
        cy={c}
        r={r}
        fill="none"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={ringDash(fraction, r)}
        transform={`rotate(-90 ${c} ${c})`}
      />
      {text !== undefined && (
        <text className="ring-text" x={c} y={c} textAnchor="middle" dominantBaseline="central">
          {text}
        </text>
      )}
    </svg>
  );
}

/** agy spend in the last 24 h as a ring against the advise level, with the amount and the note level. */
export function SpendBlock({ slot, size }: { slot: Record<string, unknown> | null | undefined; size: number }): JSX.Element {
  const v = spendView(slot);
  const advise = formatEur(v.adviseEur);
  return (
    <div className="spend-block">
      <Ring
        fraction={v.pct / 100}
        size={size}
        tone={v.advisory ? 'warn' : 'good'}
        label={`agy spend in the last 24 h: EUR ${v.committedEur.toFixed(2)}. Note level EUR ${advise}.`}
      />
      <span className="spend-text">
        <span className="spend-line">
          <span className="spend-amount">€{v.committedEur.toFixed(2)}</span> <span className="spend-label">agy, 24 h</span>
        </span>
        <span className={`spend-note${v.advisory ? ' hot' : ''}`}>Note at €{advise}</span>
      </span>
    </div>
  );
}
