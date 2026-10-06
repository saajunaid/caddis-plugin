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

/** A return path leaves and enters the bottom of its nodes. The last segment points up. */
export function loopBack(x1: number, y1: number, x2: number, y2: number, channelY: number,
  detour: { from?: { x: number; y: number }; to?: { x: number; y: number } } = {}): string {
  // Validated models supply finite positions. Guard the pure helper too so malformed input never
  // produces a path containing NaN or Infinity.
  x1 = Number.isFinite(x1) ? x1 : 0;
  x2 = Number.isFinite(x2) ? x2 : 0;
  y1 = Number.isFinite(y1) ? y1 : 0;
  y2 = Number.isFinite(y2) ? y2 : 0;
  channelY = Number.isFinite(channelY) ? channelY : Math.max(y1, y2) + 10;
  channelY = Math.max(channelY, y1, y2);
  const from = detour.from, to = detour.to;
  const startX = from?.x ?? x1, endX = to?.x ?? x2;
  const start = from ? `M${x1},${y1} V${from.y} H${startX}` : `M${x1},${y1}`;
  const finish = to ? ` V${to.y} H${x2} V${y2}` : ` V${y2}`;
  if (from || to) {
    const dir = endX >= startX ? 1 : -1;
    const r = Math.max(0, Math.min(8, Math.abs(endX - startX) / 2, (channelY - (from?.y ?? y1)) / 2, (channelY - (to?.y ?? y2)) / 2));
    return `${start} V${channelY - r} Q${startX},${channelY} ${startX + dir * r},${channelY} H${endX - dir * r} Q${endX},${channelY} ${endX},${channelY - r}${finish}`;
  }
  const dx = x2 - x1;
  const dir = dx >= 0 ? 1 : -1;
  const run = Math.abs(dx) || 32;
  const radius = Math.min(8, run / 2, (channelY - y1) / 2, (channelY - y2) / 2);
  const r = Math.max(0, radius);
  if (dx === 0) {
    // Two gentle opposite turns give a finite return even for vertically aligned boxes.
    return `M${x1},${y1} V${channelY - r} Q${x1},${channelY} ${x1 + r},${channelY} H${x1 + 16} H${x1 - r} Q${x1},${channelY} ${x1},${channelY - r} V${y2}`;
  }
  return `M${x1},${y1} V${channelY - r} Q${x1},${channelY} ${x1 + dir * r},${channelY} H${x2 - dir * r} Q${x2},${channelY} ${x2},${channelY - r} V${y2}`;
}
