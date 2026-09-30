// One node of a level: a component, the own symbols of a parent, a symbol, or a group of symbols.
import { Handle, type Node, type NodeProps, Position } from "@xyflow/react";
import { memo } from "react";

import type { ViewNode } from "../api/client";

export interface CardData extends Record<string, unknown> {
  node: ViewNode;
  boundary: boolean;
}

export type CardNode = Node<CardData, "card">;

export const CARD_WIDTH = 220;

export function cardHeight(node: ViewNode): number {
  if (node.type === "symbol" || node.type === "file" || node.type === "folder") return 58;
  return node.intent_short ? 96 : 72;
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

export const NodeCard = memo(function NodeCard({ data, selected }: NodeProps<CardNode>) {
  const { node, boundary } = data;
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
