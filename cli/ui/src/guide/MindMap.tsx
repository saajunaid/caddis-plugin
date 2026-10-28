import { guideHref } from '../shell/route';
import { mindMap, type MapNode, type PosterModel } from './poster';

const SIZE = 1000;
const HALF = SIZE / 2;

function round1(v: number): number {
  const r = Math.round(v * 10) / 10;
  return Object.is(r, -0) ? 0 : r;
}

function outward(node: MapNode, offset: number): { x: number; y: number } {
  const dx = node.x - HALF;
  const dy = node.y - HALF;
  const dist = Math.hypot(dx, dy) || 1;
  const d = node.r + offset;
  return {
    x: round1(node.x + (dx / dist) * d),
    y: round1(node.y + (dy / dist) * d),
  };
}

export function MindMap({ model }: { model: PosterModel }): JSX.Element {
  const nodes = mindMap(model, SIZE);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const motionOn =
    typeof document === 'undefined' ||
    document.documentElement?.dataset?.motion !== 'off';

  return (
    <svg
      className="gp-map"
      viewBox="0 0 1000 1000"
      role="img"
      aria-label="caddis mind map"
    >
      {nodes.map((node) => {
        if (!node.parent) return null;
        const parent = byId.get(node.parent);
        if (!parent) return null;
        const isBranch = node.kind === 'stage' || node.kind === 'group';
        return (
          <line
            key={`line-${node.id}`}
            x1={parent.x}
            y1={parent.y}
            x2={node.x}
            y2={node.y}
            stroke="var(--border-dim)"
            strokeWidth={isBranch ? 1.5 : 1}
          />
        );
      })}
      {nodes.map((node) => {
        if (node.kind === 'root') {
          return (
            <g key={node.id}>
              <circle cx={node.x} cy={node.y} r={node.r} fill="var(--purple)" />
              <text
                x={node.x}
                y={node.y}
                textAnchor="middle"
                dominantBaseline="central"
                fill="var(--bg-canvas)"
                fontFamily="var(--font-head)"
                fontSize={28}
                fontWeight={700}
              >
                {node.label}
              </text>
            </g>
          );
        }

        if (node.kind === 'stage' || node.kind === 'group') {
          const pos = outward(node, 22);
          const branchAnchor =
            node.x < HALF - 60 ? 'end' : node.x > HALF + 60 ? 'start' : 'middle';
          return (
            <g key={node.id} className={motionOn ? 'gp-pulse' : undefined}>
              <circle cx={node.x} cy={node.y} r={node.r} fill="var(--purple)" />
              <text
                x={pos.x}
                y={pos.y}
                textAnchor={branchAnchor}
                dominantBaseline="central"
                fill="var(--text-main)"
                fontFamily="var(--font-head)"
                fontSize={18}
                fontWeight={600}
              >
                {node.label}
              </text>
            </g>
          );
        }

        const pos = outward(node, 8);
        const textAnchor = node.x >= HALF ? 'start' : 'end';
        const content = (
          <>
            <circle
              cx={node.x}
              cy={node.y}
              r={node.r}
              fill="var(--bg-card)"
              stroke="var(--purple)"
            />
            <text
              x={pos.x}
              y={pos.y}
              textAnchor={textAnchor}
              dominantBaseline="central"
              fill="var(--text-main)"
              fontFamily="var(--font-body)"
              fontSize={11}
            >
              {node.label}
            </text>
          </>
        );

        if (node.anchor !== null) {
          return (
            <a key={node.id} href={guideHref('details', node.anchor)}>
              <title>{node.label}</title>
              {content}
            </a>
          );
        }

        return <g key={node.id}>{content}</g>;
      })}
    </svg>
  );
}
