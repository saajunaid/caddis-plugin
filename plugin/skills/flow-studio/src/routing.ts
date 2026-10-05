// Link routing. A link leaves the right side of a node, runs to a vertical trunk at tx (half way
// across the column gap), and enters the left side of the next node. It is horizontal where it
// touches a node, so every arrowhead points right and the links of one node share one trunk.

export function elbow(x1: number, y1: number, x2: number, y2: number, tx: number): string {
  const r = 8;
  if (Math.abs(y2 - y1) < 1) return `M${x1},${y1} H${x2}`;
  if (Math.abs(y2 - y1) < 2 * r + 2) return `M${x1},${y1} C${tx},${y1} ${tx},${y2} ${x2},${y2}`;
  const dir = y2 > y1 ? 1 : -1;
  return `M${x1},${y1} H${tx - r} Q${tx},${y1} ${tx},${y1 + dir * r} V${y2 - dir * r} Q${tx},${y2} ${tx + r},${y2} H${x2}`;
}
