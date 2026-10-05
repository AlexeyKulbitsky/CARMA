"""Extract structured function flow from a TU, without executing project code."""

from pathlib import Path
import hashlib
import re

import clang.cindex as ci

from carma.execution.api import (ExecutionCall, ExecutionEdge, ExecutionEffect, ExecutionFunction,
                                 ExecutionNode, ExecutionObject, ExecutionGroup, ExecutionUnavailable)
from carma.indexers.libclang import walker
from carma.indexers.libclang.args import STL_MISMATCH_DEFINE

K = ci.CursorKind


class FunctionBuilder:
    def __init__(self, cursor, names: walker._TuWalker):
        self.cursor, self.names = cursor, names
        self.path = names._project_path(cursor)
        self.nodes: list[ExecutionNode] = []
        self.edges: list[ExecutionEdge] = []
        self.objects: list[ExecutionObject] = []
        self.warnings: list[str] = []
        self.sources: dict[str, bytes] = {}
        self.exit = "exit"
        self.groups: list[ExecutionGroup] = []
        self.anchor_counts: dict[str, int] = {}

    def text(self, cursor) -> str:
        extent = cursor.extent
        if not extent.start.file or not extent.end.file or extent.start.file.name != extent.end.file.name:
            return cursor.spelling
        path = extent.start.file.name
        if path not in self.sources:
            self.sources[path] = Path(path).read_bytes()
        return self.sources[path][extent.start.offset:extent.end.offset].decode("utf-8", errors="replace")

    def symbol(self, cursor) -> str | None:
        if cursor is None:
            return None
        try:
            return self.names.symbol_id(cursor)
        except (ValueError, AssertionError):
            return None

    def key(self, cursor) -> str | None:
        """Local names are invocation-local; fields use canonical IDs."""
        if cursor is None:
            return None
        if cursor.kind in (K.DECL_REF_EXPR, K.MEMBER_REF_EXPR):
            ref = cursor.referenced
            if ref and ref.kind in (K.FIELD_DECL, K.VAR_DECL, K.PARM_DECL):
                return self.symbol(ref) if ref.kind == K.FIELD_DECL else ref.spelling
        if cursor.kind == K.CALL_EXPR:
            children = list(cursor.get_children())
            ref = cursor.referenced
            if ref and ref.spelling in ("get", "move", "forward", "GetInstance"):
                if ref.spelling == "GetInstance":
                    return None
                for child in children:
                    found = self.key(child)
                    if found:
                        return found
        for child in cursor.get_children():
            found = self.key(child)
            if found:
                return found
        return None

    def type_info(self, typ) -> tuple[str | None, str, str]:
        ownership = "value"
        typ = typ.get_canonical()
        if typ.kind == ci.TypeKind.POINTER:
            ownership, typ = "raw", typ.get_pointee().get_canonical()
        elif typ.kind in (ci.TypeKind.LVALUEREFERENCE, ci.TypeKind.RVALUEREFERENCE):
            ownership, typ = "borrowed", typ.get_pointee().get_canonical()
        spelling = typ.spelling
        if "unique_ptr<" in spelling or "shared_ptr<" in spelling:
            ownership = "unique" if "unique_ptr<" in spelling else "shared"
            item = typ.get_template_argument_type(0)
            if item.kind != ci.TypeKind.INVALID:
                typ = item.get_canonical()
        decl = typ.get_declaration()
        return self.symbol(decl) if decl and decl.kind in walker.RECORD_KINDS else None, typ.spelling, ownership

    def descendants(self, cursor):
        """Lambda bodies and local class methods are deferred, never immediate actions."""
        if cursor.kind in (K.LAMBDA_EXPR, *walker.RECORD_KINDS):
            return
        if cursor.kind == K.CXX_UNARY_EXPR and self.text(cursor).lstrip().startswith(("sizeof", "alignof", "noexcept")):
            return
        yield cursor
        for child in cursor.get_children():
            yield from self.descendants(child)

    def call(self, cursor) -> ExecutionCall:
        ref = cursor.referenced
        receiver = None
        if ref and ref.kind in (K.CXX_METHOD, K.CONVERSION_FUNCTION):
            for child in cursor.get_children():
                if child.kind == K.MEMBER_REF_EXPR:
                    receiver = next((self.key(c) for c in child.get_children() if self.key(c)), "this")
                    break
            receiver = receiver or "this"
        virtual = bool(ref and ref.kind == K.CXX_METHOD and ref.is_virtual_method())
        arguments = list(cursor.get_arguments())
        return ExecutionCall(symbol=self.symbol(ref), name=ref.spelling if ref else self.text(cursor)[:100],
                             receiver=receiver, arguments=[self.key(c) for c in arguments], virtual=virtual,
                             resolution="virtual" if virtual else "direct" if ref else "unknown")

    def details(self, cursor, node: ExecutionNode) -> None:
        all_items = list(self.descendants(cursor))
        for item in all_items:
            if item.kind == K.CALL_EXPR:
                node.calls.append(self.call(item))
            elif item.kind == K.VAR_DECL:
                tid, name, ownership = self.type_info(item.type)
                object_id = f"{item.spelling}:{item.location.line}"
                initializer = list(item.get_children())
                created = any(c.kind == K.CXX_NEW_EXPR or
                              (c.kind == K.CALL_EXPR and c.referenced and c.referenced.spelling in
                               ("make_unique", "make_shared", item.type.spelling)) for c in self.descendants(item))
                created = created or bool(tid and ownership == "value") or any(
                    name in self.text(item) for name in ("std::make_unique<", "std::make_shared<"))
                if tid:
                    self.objects.append(ExecutionObject(id=object_id, name=item.spelling, type_name=name,
                                                        type_symbol=tid, ownership=ownership, created=created,
                                                        line=item.location.line))
                    node.objects.append(object_id)
                node.effects.append(ExecutionEffect(target=item.spelling, type_symbol=tid,
                                                     value=self.key(initializer[-1]) if initializer else None))
            elif item.kind == K.BINARY_OPERATOR:
                children = list(item.get_children())
                if len(children) == 2:
                    gap = self.sources.get(item.extent.start.file.name)
                    if gap is None:
                        self.text(item)
                        gap = self.sources[item.extent.start.file.name]
                    operator = gap[children[0].extent.end.offset:children[1].extent.start.offset].decode(errors="replace").strip()
                    target = self.key(children[0])
                    if operator == "=" and target:
                        node.effects.append(ExecutionEffect(target=target, value=self.key(children[1]),
                                                             ownership=self.type_info(children[0].type)[2]))
        for call in node.calls:
            # unique_ptr::reset(parameter) stores the parameter into the receiver field.
            if call.name == "reset" and call.receiver and call.receiver.startswith("cxx "):
                node.effects.append(ExecutionEffect(target=call.receiver,
                                                     value=call.arguments[0] if call.arguments else None,
                                                     ownership="unique"))
            elif call.name == "operator=" and len(call.arguments) == 2 and call.arguments[0]:
                node.effects.append(ExecutionEffect(target=call.arguments[0], value=call.arguments[1], ownership="unique"
                                                     if "unique_ptr" in (call.symbol or "") else None))
        if any(c.kind == K.LAMBDA_EXPR for c in self._shallow(cursor)):
            node.note = "Registers or creates a callback. Its body runs later, when invoked."
        if len(node.calls) > 1:
            node.note = (node.note + " Calls inside this expression are listed without claiming an evaluation order.").strip()
        if any(c.kind == K.CONDITIONAL_OPERATOR for c in all_items) or any(t.spelling in {"&&", "||"} for t in cursor.get_tokens()):
            node.note = (node.note + " Some calls in this expression are conditional.").strip()

    def _shallow(self, cursor):
        yield cursor
        if cursor.kind != K.LAMBDA_EXPR:
            for child in cursor.get_children():
                yield from self._shallow(child)

    def node(self, kind, cursor=None, code=None) -> ExecutionNode:
        line = cursor.location.line if cursor else self.cursor.location.line
        end = cursor.extent.end.line if cursor else line
        text = code if code is not None else self.text(cursor)
        label = " ".join(text.split())
        nid = f"{kind}:{line}:{cursor.location.column if cursor else 1}:{len(self.nodes)}"
        if kind == "exit":
            nid = self.exit
        node = ExecutionNode(id=nid, kind=kind, label=label[:180], code=text[:4000], path=self.path,
                             line=max(1, line), end_line=max(1, end))
        digest = hashlib.sha256((kind + "|" + text.strip()).encode()).hexdigest()[:20]
        self.anchor_counts[digest] = self.anchor_counts.get(digest, 0) + 1
        node.anchor = f"{digest}:{self.anchor_counts[digest]}"
        self.nodes.append(node)
        return node

    def link(self, sources, target, label=""):
        for source in sources:
            self.edges.append(ExecutionEdge(source=source, target=target, label=label))

    def group(self, label: str, members: list[str], origin="structure"):
        existing = next((g for g in self.groups if g.members == members), None)
        if existing and origin == "comment":
            existing.label, existing.origin = label[:180], origin
        if len(members) < 2 or existing:
            return
        self.groups.append(ExecutionGroup(id="pending", label=label[:180], members=members, origin=origin))

    def statement(self, cursor, incoming, break_to=None, continue_to=None):
        start = len(self.nodes)
        result = self._statement(cursor, incoming, break_to, continue_to)
        if cursor.kind in (K.IF_STMT, K.WHILE_STMT, K.FOR_STMT, K.CXX_FOR_RANGE_STMT, K.DO_STMT):
            members = [n.id for n in self.nodes[start:]]
            if cursor.kind != K.IF_STMT or len(members) > 6:
                self.group(self.nodes[start].label, members)
        return result

    def _statement(self, cursor, incoming, break_to=None, continue_to=None):
        children = list(cursor.get_children())
        if cursor.kind == K.COMPOUND_STMT:
            current = incoming
            sections = []
            label, origin, members = "", "structure", []
            previous = cursor.extent.start.offset + 1
            section_size = 0
            self.text(cursor)
            source = self.sources[cursor.extent.start.file.name]
            for child in children:
                gap = source[previous:child.extent.start.offset].decode("utf-8", errors="replace")
                comments = re.findall(r"(?m)^\s*//\s*([^\n]+)|/\*\s*(.*?)\*/", gap, re.S)
                comment = next((a or b for a, b in comments), "").split("\n")[0].strip(" -/*\r")
                if members and (comment or (len(children) > 16 and section_size >= 4)):
                    sections.append((label, members, origin))
                    members = []
                    label, origin, section_size = "", "structure", 0
                if comment:
                    label, origin = comment, "comment"
                start = len(self.nodes)
                current = self.statement(child, current, break_to, continue_to)
                members.extend(n.id for n in self.nodes[start:])
                section_size += 1
                if not label and len(self.nodes) > start:
                    label = self.nodes[start].label
                previous = child.extent.end.offset
            if members:
                sections.append((label, members, origin))
            # Comment sections are suggestions. Unannotated large scopes get bounded chunks,
            # while small functions retain their individual instructions.
            for label, members, origin in sections:
                if origin == "comment" or len(sections) > 1:
                    self.group(label, members, origin)
            return current
        if cursor.kind == K.IF_STMT:
            has_else = len(children) >= 3 and any(t.spelling == "else" and
                children[-2].extent.end.offset <= t.location.offset <= children[-1].extent.start.offset
                for t in cursor.get_tokens())
            # The final one/two children are the controlled statements, including single-line bodies.
            bodies = children[-2:] if has_else else children[-1:]
            condition = children[:-len(bodies)]
            self.text(cursor)
            header = self.sources[cursor.extent.start.file.name][cursor.extent.start.offset:bodies[0].extent.start.offset].decode("utf-8", errors="replace")
            branch = self.node("branch", cursor, header)
            for c in condition:
                self.details(c, branch)
            self.link(incoming, branch.id)
            true_gate = self.node("action", cursor, "Then")
            self.link([branch.id], true_gate.id, "true")
            yes = self.statement(bodies[0], [true_gate.id], break_to, continue_to)
            if has_else:
                false_gate = self.node("action", cursor, "Else")
                self.link([branch.id], false_gate.id, "false")
                no = self.statement(bodies[1], [false_gate.id], break_to, continue_to)
            else:
                no = [branch.id]
            join = self.node("action", cursor, "Continue")
            self.link(yes, join.id)
            self.link(no, join.id, "false" if not has_else else "")
            return [join.id] if yes or no else []
        if cursor.kind in (K.WHILE_STMT, K.FOR_STMT, K.CXX_FOR_RANGE_STMT, K.DO_STMT):
            body = children[0] if cursor.kind == K.DO_STMT else children[-1]
            head = self.text(cursor).split("{", 1)[0].strip()
            loop = self.node("loop", cursor, head)
            loop.note = "Repeated block. Initializer, condition and increment remain summarized in the loop header."
            after = self.node("action", cursor, "After loop")
            gate = self.node("action", cursor, "Loop body")
            self.link(incoming, gate.id if cursor.kind == K.DO_STMT else loop.id)
            self.link([loop.id], gate.id, "repeat")
            self.link([loop.id], after.id, "done")
            tail = self.statement(body, [gate.id], after.id, loop.id)
            self.link(tail, loop.id, "next iteration")
            self.nodes.remove(after)
            self.nodes.append(after)
            for c in children:
                if c != body:
                    self.details(c, loop)
            return [after.id]
        kind = {K.RETURN_STMT: "return", K.BREAK_STMT: "break", K.CONTINUE_STMT: "continue"}.get(cursor.kind, "action")
        opaque = cursor.kind in (K.SWITCH_STMT, K.CXX_TRY_STMT, K.GOTO_STMT, K.INDIRECT_GOTO_STMT)
        node = self.node("opaque" if opaque else kind, cursor)
        self.link(incoming, node.id)
        if opaque:
            node.note = "Control flow inside this block is not expanded by this version. Open the source to inspect it."
            self.warnings.append(node.note)
        else:
            self.details(cursor, node)
        if kind == "return":
            self.link([node.id], self.exit, "return")
            return []
        if kind in ("break", "continue"):
            target = break_to if kind == "break" else continue_to
            if target:
                self.link([node.id], target, kind)
            return []
        return [node.id]

    def build(self) -> ExecutionFunction | None:
        body = next((c for c in self.cursor.get_children() if c.kind == K.COMPOUND_STMT), None)
        if body is None:
            return None
        entry = self.node("entry", code=self.cursor.displayname)
        tail = self.statement(body, [entry.id])
        self.node("exit", code="Return to caller")
        self.link(tail, self.exit)
        for node in self.nodes:
            digest, occurrence = node.anchor.split(":")
            node.anchor = f"{digest}:{self.anchor_counts[digest]}:{occurrence}"
        anchors = {n.id: n.anchor for n in self.nodes}
        for group in self.groups:
            group.id = "scope:" + hashlib.sha256("|".join(anchors[n] for n in group.members).encode()).hexdigest()[:20]
        # A comment section supersedes an equivalent structural suggestion's title.
        return ExecutionFunction(symbol=self.symbol(self.cursor), name=self.cursor.displayname, path=self.path,
                                 line=self.cursor.location.line, entry=entry.id, exit=self.exit,
                                 parameters=[p.spelling for p in self.cursor.get_arguments()], nodes=self.nodes,
                                 edges=self.edges, objects=self.objects, warnings=sorted(set(self.warnings)), groups=self.groups)


def analyze(source: str, args: list[str], libclang: str, root: str, ignore: tuple[str, ...]) -> dict:
    worker = walker._Worker(libclang, root, ignore)
    tu = walker._parse(worker.index, source, args)
    if tu is None:
        raise ExecutionUnavailable("The source file could not be parsed with its saved build settings.")
    errors, messages = walker._diagnostics(tu, worker)
    if errors and any("STL1000" in message for message in messages):
        tu = walker._parse(worker.index, source, args + [STL_MISMATCH_DEFINE]) or tu
        errors, messages = walker._diagnostics(tu, worker)
    names = walker._TuWalker(worker)
    functions = {}
    stack = list(tu.cursor.get_children())
    while stack:
        cursor = stack.pop()
        if names._project_path(cursor) is None:
            continue
        if cursor.kind in walker.FUNCTION_KINDS and cursor.is_definition():
            flow = FunctionBuilder(cursor, names).build()
            if flow:
                flow.warnings.extend(messages)
                functions[flow.symbol] = flow.model_dump()
            continue
        if cursor.kind in (*walker.SCOPE_KINDS, *walker.RECORD_KINDS):
            stack.extend(cursor.get_children())
    # Every included file is part of the cache signature, including external headers.
    dependencies = {source}
    dependencies.update(i.include.name for i in tu.get_includes() if i.include)
    return {"functions": functions, "dependencies": sorted(dependencies)}
