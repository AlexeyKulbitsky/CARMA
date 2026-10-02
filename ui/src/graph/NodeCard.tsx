// One node of a level: a component, the own symbols of a parent, a symbol, or a group of symbols.
import { Handle, type Node, type NodeProps, Position } from "@xyflow/react";
import { memo } from "react";

import type { ViewMember, ViewNode } from "../api/client";
import { useMap } from "../store";

export interface CardData extends Record<string, unknown> {
  node: ViewNode;
  boundary: boolean;
}

export type CardNode = Node<CardData, "card">;

export const CARD_WIDTH = 220;

const FIELD_KINDS = new Set(["field", "variable"]);

export function cardWidth(node: ViewNode): number {
  return node.type === "symbol" && (node.members?.length ?? 0) > 0 ? 300 : CARD_WIDTH;
}

export function cardHeight(node: ViewNode): number {
  const base = node.type === "symbol" || node.type === "file" || node.type === "folder" ? 58 : node.intent_short ? 96 : 72;
  const fields = (node.members ?? []).filter((member) => FIELD_KINDS.has(member.kind)).length;
  const methods = (node.members?.length ?? 0) - fields;
  const groupHeight = (count: number) => count ? 22 + 20 * Math.min(count, 3) : 0;
  return base + groupHeight(fields) + groupHeight(methods)
    + (node.issues.length ? 24 * Math.ceil(node.issues.length / 2) : 0);
}

export function cardTitle(node: ViewNode): string {
  return node.type === "self" ? `own symbols of ${node.name}` : node.name;
}

function basename(path: string | null): string {
  return path ? path.slice(path.lastIndexOf("/") + 1) : "";
}

export function cardMeta(node: ViewNode): string {
  const count = `${node.symbols} symbol${node.symbols === 1 ? "" : "s"}`;
  switch (node.type) {
    case "component":
      return [node.kind, count, node.children ? `${node.children} inside` : ""].filter(Boolean).join(" · ");
    case "symbol":
      return [node.kind, basename(node.file)].filter(Boolean).join(" · ");
    case "file":
      return `file · ${count}`;
    case "folder":
      return `folder · ${count}`;
    default:
      return count;
  }
}

function MemberList({ title, nodeName, members }: { title: string; nodeName: string; members: ViewMember[] }) {
  const showSymbol = useMap((s) => s.showSymbol);
  if (!members.length) return null;
  return (
    <section className="card-member-section" aria-label={`${title} of ${nodeName}`}>
      <div className="card-member-heading">{title} <span className="count">{members.length}</span></div>
      <ul className="card-member-list nowheel nodrag">
        {members.map((member) => (
          <li key={member.id}>
            <button type="button" className="link card-member-link nodrag"
              title={`${member.access ? `${member.access} ` : ""}${member.signature ?? member.name}`}
              aria-label={`${member.access ? `${member.access} ` : ""}${member.kind} ${member.signature ?? member.name}`}
              onClick={(event) => { event.stopPropagation(); void showSymbol(member.id); }}>
              <span className="card-member-signature">{member.signature ?? member.name}</span>
              {member.access && <span className="card-member-access">{member.access}</span>}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export const NodeCard = memo(function NodeCard({ data, selected }: NodeProps<CardNode>) {
  const { node, boundary } = data;
  const fields = (node.members ?? []).filter((member) => FIELD_KINDS.has(member.kind));
  const methods = (node.members ?? []).filter((member) => !FIELD_KINDS.has(member.kind));
  const classes = ["card", `card-${node.type}`];
  if (boundary) classes.push("card-boundary");
  if (selected) classes.push("card-focused");
  if (node.lifecycle === "planned") classes.push("card-planned");
  if (node.lifecycle === "deprecated") classes.push("card-deprecated");
  return (
    <div className={classes.join(" ")} title={node.id}>
      <Handle type="target" position={Position.Top} className="handle" isConnectable={false} />
      <div className="card-head">
        <span className="card-name">{cardTitle(node)}</span>
        {node.lifecycle && node.lifecycle !== "current" && (
          <span className={`badge badge-${node.lifecycle}`}>{node.lifecycle}</span>
        )}
      </div>
      <div className="card-meta">{cardMeta(node)}</div>
      {node.intent_short && <div className="card-intent">{node.intent_short}</div>}
      <MemberList title="Fields" nodeName={node.name} members={fields} />
      <MemberList title="Methods" nodeName={node.name} members={methods} />
      {node.issues.length > 0 && (
        <div className="card-issues">
          {node.issues.map((code) => (
            <span key={code} className="badge badge-issue">
              {code.replaceAll("_", " ")}
            </span>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="handle" isConnectable={false} />
    </div>
  );
});
