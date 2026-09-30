// The open level lives in the URL hash, so reloads, links and the browser's back button work.
import type { Crumb, TreeNode } from "./api/client";

export const ROOT = "root";

export function scopeFromHash(hash: string): string {
  const raw = hash.replace(/^#\/?/, "");
  return raw ? decodeURIComponent(raw) : ROOT;
}

export function hashForScope(scope: string): string {
  return scope === ROOT ? "#/" : `#/${encodeURIComponent(scope)}`;
}

export function isSelfScope(scope: string): boolean {
  return scope.endsWith("._self");
}

export function crumbLabel(crumb: Crumb, projectName: string | undefined): string {
  if (crumb.scope === ROOT) return projectName || ROOT;
  if (isSelfScope(crumb.scope)) return `own symbols of ${crumb.name}`;
  return crumb.name;
}

export interface FlatComponent {
  id: string;
  name: string;
  kind: string;
  parent: string;
}

/** The component tree as a list, each entry with the scope of the level that shows it. */
export function flattenTree(nodes: TreeNode[], parent = ROOT): FlatComponent[] {
  return nodes.flatMap((node) => [
    { id: node.id, name: node.name, kind: node.kind, parent },
    ...flattenTree(node.children, node.id),
  ]);
}

/** Scopes a node can be opened as: components, their own symbols and the unassigned bucket. */
export function drillScope(nodeId: string, type: string): string | null {
  return type === "component" || type === "self" || type === "unassigned" ? nodeId : null;
}
