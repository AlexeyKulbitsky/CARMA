import type { ExecutionFunction, ExecutionNode, FunctionStudy } from "../api/client";

export const studyKey = (flow: ExecutionFunction) => `${flow.symbol}@${flow.path}`;
export const anchor = (node: ExecutionNode) => node.anchor || node.id;
export const blockKey = (prefix: string, group: string) => `${prefix}|${group}`;
export interface StudyBlock { id: string; title: string; members: string[]; automatic: boolean; }

/** Suggestions and personal knowledge stay separate from the adapter's control-flow facts. */
export function studyBlocks(flow: ExecutionFunction, study?: FunctionStudy) {
  const byAnchor = new Map(flow.nodes.map((n) => [anchor(n), n.id]));
  const dismissed = new Set(study?.dismissed ?? []);
  const blocks: StudyBlock[] = (flow.groups ?? []).filter((g) => !dismissed.has(g.id))
    .map((g) => ({ id: g.id, title: g.label, members: g.members, automatic: true }));
  const stale: string[] = [];
  for (const group of study?.groups ?? []) {
    const members = group.members.map((a) => byAnchor.get(a));
    if (members.some((m) => !m)) { stale.push(group.title); continue; }
    const ids = members as string[];
    const compatible = blocks.filter((b) => !b.members.some((m) => ids.includes(m)) ||
      b.members.every((m) => ids.includes(m)) || ids.every((m) => b.members.includes(m)));
    blocks.splice(0, blocks.length, ...compatible.filter((b) => !(b.members.length === ids.length && b.members.every((m) => ids.includes(m)))));
    blocks.push({ id: group.id, title: group.title, members: ids, automatic: false });
  }
  const known = new Set([...flow.nodes.map(anchor), ...blocks.map((g) => g.id)]);
  const unbound = Object.keys(study?.annotations ?? {}).filter((id) => !known.has(id));
  return { blocks, stale, unbound };
}

export function groupSelection(flow: ExecutionFunction, ordered: string[][], chosen: number[]) {
  const sorted = [...new Set(chosen)].sort((a, b) => a - b);
  if (sorted.length < 2 || sorted.some((n, i) => i > 0 && n !== sorted[i - 1] + 1))
    return { error: "Choose at least two consecutive blocks in this scope.", members: [] as string[] };
  const members = sorted.flatMap((i) => ordered[i] ?? []);
  const incoming = new Set(flow.edges.filter((e) => !members.includes(e.source) && members.includes(e.target)).map((e) => e.target));
  if (incoming.size > 1 || members.some((id) => [flow.entry, flow.exit].includes(id)))
    return { error: "This selection crosses control-flow entries. Select complete branches or loops.", members: [] as string[] };
  return { error: null, members: flow.nodes.filter((n) => members.includes(n.id)).map(anchor) };
}
