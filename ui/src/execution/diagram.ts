import type { ExecutionFunction, ExecutionNode, Exploration, ExplorationView, StudyAnnotation } from "../api/client";
import { anchor, blockKey, studyBlocks, studyKey, type StudyBlock } from "./study";

export interface DiagramNode {
  id: string; step: ExecutionNode; prefix: string; functionName: string; scope: string;
  group?: StudyBlock; members: string[]; annotation?: StudyAnnotation; annotationKey: string;
  detached?: string;
}
export interface DiagramEdge { id: string; source: string; target: string; label: string; detail: boolean; }
export interface DiagramScope { id: string; prefix: string; source?: string; detached?: string; }

/** Collapse is a graph projection: every edge crossing a block's boundary survives. */
export function executionDiagram(functions: Record<string, ExecutionFunction>, saved?: Exploration, view?: ExplorationView) {
  const nodes: DiagramNode[] = [], edges: DiagramEdge[] = [], scopes: DiagramScope[] = [];
  const visible = new Map<string, string[]>();
  const open = new Set(view?.blocks ?? []);
  function scope(prefix: string, id: string, subset?: string[], source?: string, detached?: string) {
    const flow = functions[prefix];
    if (!flow) return;
    const study = saved?.studies?.[studyKey(flow)];
    const { blocks } = studyBlocks(flow, study);
    const allowed = new Set(subset ?? flow.nodes.map((n) => n.id));
    const candidates = blocks.filter((g) => g.members.every((m) => allowed.has(m)) && (!subset || g.members.length < subset.length));
    const outer = candidates.filter((g) => !candidates.some((other) => other !== g &&
      other.members.length > g.members.length && g.members.every((m) => other.members.includes(m))));
    const owner = new Map<string, StudyBlock>();
    outer.forEach((g) => g.members.forEach((m) => owner.set(m, g)));
    const mapped = new Map<string, string>();
    const made = new Set<string>();
    scopes.push({ id, prefix, source, detached });
    for (const step of flow.nodes.filter((n) => allowed.has(n.id))) {
      const group = owner.get(step.id);
      const nid = `${id}/${group?.id ?? step.id}`;
      mapped.set(step.id, nid);
      visible.set(`${prefix}/${step.id}`, [...visible.get(`${prefix}/${step.id}`) ?? [], nid]);
      if (made.has(nid)) continue;
      made.add(nid);
      const annotationKey = group?.id ?? anchor(step);
      const annotation = study?.annotations?.[annotationKey];
      const members = group?.members ?? [step.id];
      const last = flow.nodes.filter((n) => members.includes(n.id));
      const synthetic = group ? { ...step, label: annotation?.title || group.title,
        code: last.filter((n) => n.code && !["Then", "Else", "Continue", "Loop body", "After loop"].includes(n.label)).map((n) => n.code).join("\n"),
        end_line: Math.max(...last.map((n) => n.end_line)), calls: [], objects: last.flatMap((n) => n.objects ?? []) } :
        { ...step, label: annotation?.title || step.label };
      nodes.push({ id: nid, step: synthetic, prefix, functionName: flow.name, scope: id, group, members, annotation, annotationKey, detached });
    }
    const distinct = new Set<string>();
    for (const e of flow.edges) {
      const from = mapped.get(e.source), to = mapped.get(e.target);
      if (!from && !to) continue;
      const target = to ?? (!detached ? visible.get(`${prefix}/${e.target}`)?.[0] : undefined);
      if (!from || !target || from === target) continue;
      const original = flow.nodes.find((n) => n.id === e.source);
      const summarized = from !== `${id}/${e.source}`;
      const label = summarized && original?.kind === "return" ? original.label :
        e.label || (!to ? `exit: ${original?.label ?? "continue"}` : "");
      const signature = `${from}>${target}:${label}`;
      if (distinct.has(signature)) continue;
      distinct.add(signature);
      edges.push({ id: `${id}:edge:${edges.length}`, source: from, target, label, detail: false });
    }
    for (const group of outer) {
      const key = blockKey(detached ? `detached:${detached}` : prefix, group.id);
      if (open.has(key)) scope(prefix, key, group.members, `${id}/${group.id}`, detached);
    }
  }
  for (const prefix of Object.keys(functions)) {
    const original = prefix.slice(0, prefix.lastIndexOf("@"));
    const candidates = (visible.get(original) ?? []).map((id) => nodes.find((n) => n.id === id)!).filter((n) => !n.group);
    const origin = view?.origins?.[prefix];
    const source = origin ? candidates.find((n) => n.scope === origin) : candidates.filter((n) => !n.detached).at(-1) ?? candidates.at(-1);
    if (prefix === "root" || source) scope(prefix, prefix, undefined, source?.id, source?.detached);
    // Inspectors remain usable even when their original scope is folded.
    for (const [id, inspector] of Object.entries(view?.detached ?? {})) {
      if (inspector.function !== prefix) continue;
      const flow = functions[prefix];
      const group = inspector.group ? studyBlocks(flow, saved?.studies?.[studyKey(flow)]).blocks.find((g) => g.id === inspector.group) : undefined;
      if (inspector.group && !group) continue;
      scope(prefix, `detached:${id}`, group?.members, undefined, id);
    }
  }
  for (const s of scopes) {
    const first = nodes.find((n) => n.scope === s.id);
    if (s.source && first) edges.push({ id: `${s.id}:detail`, source: s.source, target: first.id, label: "details", detail: true });
  }
  return { nodes, edges, scopes };
}

/** Independent vertical scopes: adding details never reflows the main sequence. */
export function executionPositions(diagram: ReturnType<typeof executionDiagram>, view?: ExplorationView) {
  const positions: Record<string, { x: number; y: number }> = {};
  const occupied: { x: number; top: number; bottom: number }[] = [];
  for (const scope of diagram.scopes) {
    const cards = diagram.nodes.filter((n) => n.scope === scope.id);
    const source = scope.source && positions[scope.source];
    let x = source ? source.x + 460 : 60;
    const y = source ? source.y : scope.detached ? view?.detached?.[scope.detached]?.position.y ?? 60 : 60;
    if (scope.detached) x = view?.detached?.[scope.detached]?.position.x ?? x;
    const height = cards.length * 180;
    if (source) while (occupied.some((area) => Math.abs(area.x - x) < 400 && y < area.bottom && y + height > area.top)) x += 460;
    cards.forEach((n, index) => { positions[n.id] = view?.positions?.[n.id] ?? { x, y: y + index * 180 }; });
    occupied.push({ x, top: y, bottom: y + height });
  }
  return positions;
}
