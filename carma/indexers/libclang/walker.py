"""One translation unit -> partial contract-1 facts.

Runs in worker processes: init_worker() loads libclang once per process, index_tu() handles
one TU and returns plain data that the indexer merges. A worker remembers which project
files it has already walked and skips their declarations in later TUs (header dedupe).
"""

from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path

import clang.cindex as ci

from carma.indexers.libclang import discovery, ids
from carma.indexers.libclang.args import STL_MISMATCH_DEFINE
from carma.paths import matches_any, relpath

K = ci.CursorKind

FUNCTION_KINDS = frozenset({K.FUNCTION_DECL, K.CXX_METHOD, K.CONSTRUCTOR, K.DESTRUCTOR, K.CONVERSION_FUNCTION, K.FUNCTION_TEMPLATE})
RECORD_KINDS = frozenset({K.CLASS_DECL, K.STRUCT_DECL, K.UNION_DECL, K.CLASS_TEMPLATE, K.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION})
TYPE_KINDS = RECORD_KINDS | {K.ENUM_DECL}
ALIAS_KINDS = frozenset({K.TYPEDEF_DECL, K.TYPE_ALIAS_DECL, K.TYPE_ALIAS_TEMPLATE_DECL})
VALUE_KINDS = frozenset({K.FIELD_DECL, K.VAR_DECL, K.ENUM_CONSTANT_DECL})
SYMBOL_KINDS = FUNCTION_KINDS | TYPE_KINDS | ALIAS_KINDS | VALUE_KINDS | {K.NAMESPACE, K.MACRO_DEFINITION, K.CONCEPT_DECL}
SCOPE_KINDS = frozenset({K.NAMESPACE, K.LINKAGE_SPEC, K.UNEXPOSED_DECL})
REF_EXPR_KINDS = frozenset({K.DECL_REF_EXPR, K.MEMBER_REF_EXPR})
TYPE_REF_KINDS = frozenset({K.TYPE_REF, K.TEMPLATE_REF, K.MEMBER_REF})
TEMPLATE_PARAM_KINDS = frozenset({K.TEMPLATE_TYPE_PARAMETER, K.TEMPLATE_NON_TYPE_PARAMETER, K.TEMPLATE_TEMPLATE_PARAMETER})
PREPROCESSOR_KINDS = frozenset({K.MACRO_DEFINITION, K.MACRO_INSTANTIATION, K.INCLUSION_DIRECTIVE})

KIND_NAMES = {
    K.NAMESPACE: "namespace",
    K.CLASS_DECL: "class",
    K.STRUCT_DECL: "struct",
    K.UNION_DECL: "union",
    K.ENUM_DECL: "enum",
    K.ENUM_CONSTANT_DECL: "enum_member",
    K.FUNCTION_DECL: "function",
    K.CXX_METHOD: "method",
    K.CONSTRUCTOR: "constructor",
    K.DESTRUCTOR: "method",
    K.CONVERSION_FUNCTION: "method",
    K.FIELD_DECL: "field",
    K.VAR_DECL: "variable",
    K.MACRO_DEFINITION: "macro",
    K.TYPEDEF_DECL: "type_alias",
    K.TYPE_ALIAS_DECL: "type_alias",
    K.TYPE_ALIAS_TEMPLATE_DECL: "type_alias",
    K.CONCEPT_DECL: "concept",
}

PARSE_OPTIONS = ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD | 0x200  # 0x200: CXTranslationUnit_KeepGoing
DOC_LIMIT = 2048


class _Worker:
    def __init__(self, libclang: str, root: str, ignore: tuple[str, ...]):
        self.info = discovery.load(Path(libclang))
        self.lib = ci.conf.lib
        self.root = Path(root)
        self.ignore = tuple(ignore)
        self.index = ci.Index.create()
        self.done_files: set[str] = set()
        self._classes: dict[str, tuple[str | None, str]] = {}

    def classify(self, name: str) -> tuple[str | None, str]:
        """(relative path, 'project' | 'ignored' | 'outside') for a file name from libclang."""
        hit = self._classes.get(name)
        if hit is None:
            rel = relpath(name, self.root)
            if rel is None:
                hit = (None, "outside")
            elif matches_any(rel, self.ignore):
                hit = (rel, "ignored")
            else:
                hit = (rel, "project")
            self._classes[name] = hit
        return hit


_worker: _Worker | None = None


def init_worker(libclang: str, root: str, ignore: tuple[str, ...]) -> None:
    global _worker
    _worker = _Worker(libclang, root, ignore)


def _same_location(a, b) -> bool:
    la, lb = a.location, b.location
    if la.line != lb.line or la.column != lb.column:
        return False
    fa, fb = la.file, lb.file
    return (fa.name if fa else None) == (fb.name if fb else None)


class _TuWalker:
    def __init__(self, worker: _Worker):
        self.w = worker
        self.lib = worker.lib
        self.symbols: dict[str, dict] = {}
        self.refs: list[tuple] = []
        self.relations: set[tuple[str, str, str]] = set()
        self.seen_files: set[str] = set()
        self._ids: dict[int, str | None] = {}
        self._skip_refs: set[int] = set()
        self._extents: dict[str, list[tuple]] = {}
        self._expansions: list[tuple] = []

    # ---------------------------------------------------------------- locations

    def _file_class(self, cursor) -> tuple[str | None, str]:
        f = cursor.location.file
        if f is None:
            return None, "outside"
        return self.w.classify(f.name)

    def _project_path(self, cursor) -> str | None:
        rel, cls = self._file_class(cursor)
        return rel if cls == "project" else None

    @staticmethod
    def _loc(cursor, path: str) -> dict:
        loc = cursor.location
        line, col = max(loc.line - 1, 0), max(loc.column - 1, 0)
        name_len = len(cursor.spelling.encode("utf-8")) if cursor.spelling else 0
        ext = cursor.extent
        extent = [max(ext.start.line - 1, 0), max(ext.start.column - 1, 0), max(ext.end.line - 1, 0), max(ext.end.column - 1, 0)]
        return {"path": path, "range": [line, col, line, col + name_len], "extent": extent}

    # ---------------------------------------------------------------- canonical IDs

    def _resolve(self, c):
        """Implicit template instantiations map to their pattern, then to the first declaration."""
        template = c.specialized_template
        if template is not None and _same_location(c, template):
            c = template
        return c.canonical

    def symbol_id(self, c) -> str | None:
        c = self._resolve(c)
        key = c.hash
        if key not in self._ids:
            self._ids[key] = self._build_id(c)
        return self._ids[key]

    def _is_transparent(self, c) -> bool:
        k = c.kind
        if k in (K.LINKAGE_SPEC, K.UNEXPOSED_DECL):
            return True
        if k in RECORD_KINDS and c.is_anonymous_record_decl():
            return True
        if k == K.ENUM_DECL and c.is_anonymous():
            return True
        return k == K.NAMESPACE and bool(c.spelling) and bool(self.lib.clang_Cursor_isInlineNamespace(c))

    def _file_segment(self, c) -> str:
        f = c.location.file
        name = f.name if f else "<unknown>"
        rel = relpath(name, self.w.root)
        return ids.file_segment(rel if rel is not None else os.path.basename(name))

    def _type_name(self, c) -> str:
        if c.kind == K.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION:
            return ids.norm_type(c.displayname)
        if c.kind in (K.CLASS_DECL, K.STRUCT_DECL, K.UNION_DECL):
            template = c.specialized_template
            if template is not None:
                if _same_location(c, template):
                    return template.spelling  # implicit instantiation: named as the template
                return ids.norm_type(c.displayname)  # explicit specialization: keep the arguments
        name = c.spelling
        return "(unnamed)" if not name or name.startswith("(") else name

    def _type_descriptor(self, c) -> str:
        """Escape the name only; template arguments of a specialization stay as written."""
        name = self._type_name(c)
        base, bracket, args = name.partition("<")
        if bracket and base and name != "(unnamed)":
            return ids.escape(base) + "<" + args + "#"
        return ids.escape(name) + "#"

    def _function_descriptor(self, c) -> str:
        children = list(c.get_children())
        tparams = ""
        if c.kind == K.FUNCTION_TEMPLATE:
            names = [ch.spelling or "?" for ch in children if ch.kind in TEMPLATE_PARAM_KINDS]
            tparams = "<" + ", ".join(names) + ">"
        params = [ids.norm_type(ch.type.spelling) for ch in children if ch.kind == K.PARM_DECL]
        try:
            if c.type.kind == ci.TypeKind.FUNCTIONPROTO and c.type.is_function_variadic():
                params.append("...")
        except Exception:  # noqa: BLE001 - some declarations have no function type
            pass
        suffix = ""
        if c.kind in (K.CXX_METHOD, K.CONVERSION_FUNCTION, K.FUNCTION_TEMPLATE) and c.is_const_method():
            suffix += "const"
        try:
            qualifier = c.type.get_ref_qualifier()
            if qualifier == ci.RefQualifierKind.LVALUE:
                suffix += "&"
            elif qualifier == ci.RefQualifierKind.RVALUE:
                suffix += "&&"
        except Exception:  # noqa: BLE001
            pass
        name = c.spelling
        if not name.startswith("operator"):
            name = name.partition("<")[0]  # constructors of class templates: `basic_string<_Elem, ...>`
        return ids.escape(name) + tparams + "(" + ", ".join(params) + ")" + suffix + "."

    def _build_id(self, c) -> str | None:
        if c.kind == K.MACRO_DEFINITION:
            return ids.SCHEME + ids.escape(c.spelling) + "!"
        if c.kind not in SYMBOL_KINDS or self._is_transparent(c):
            return None
        parts: list[str] = []
        anonymous_namespace = False
        cur = c
        while cur is not None and cur.kind != K.TRANSLATION_UNIT:
            k = cur.kind
            leaf = cur is c
            if not leaf and (k in FUNCTION_KINDS or k == K.LAMBDA_EXPR):
                return None  # declared inside a function body: local
            if self._is_transparent(cur):
                pass
            elif k == K.NAMESPACE:
                if cur.spelling:
                    parts.append(ids.escape(cur.spelling) + "/")
                else:
                    parts.append(self._file_segment(cur))
                    anonymous_namespace = True
            elif k in TYPE_KINDS:
                parts.append(self._type_descriptor(cur))
            elif k in ALIAS_KINDS or k == K.CONCEPT_DECL:
                parts.append(ids.escape(cur.spelling) + "#")
            elif leaf and k in FUNCTION_KINDS:
                parts.append(self._function_descriptor(cur))
            elif leaf and k in VALUE_KINDS:
                parts.append(ids.escape(cur.spelling) + ".")
            else:
                return None  # an unexpected scope (block, ObjC, ...): treat as local
            cur = cur.semantic_parent
        if (
            c.kind in (K.FUNCTION_DECL, K.FUNCTION_TEMPLATE, K.VAR_DECL)
            and not anonymous_namespace
            and c.linkage == ci.LinkageKind.INTERNAL
            and c.semantic_parent is not None
            and c.semantic_parent.kind not in RECORD_KINDS
        ):
            parts.insert(1, self._file_segment(c))  # file segment right before the leaf
        return ids.SCHEME + "".join(reversed(parts))

    # ---------------------------------------------------------------- symbol records

    def _parent(self, c):
        p = c.semantic_parent
        while p is not None and p.kind != K.TRANSLATION_UNIT:
            if not self._is_transparent(p):
                return p
            p = p.semantic_parent
        return None

    def _kind_name(self, c) -> str:
        k = c.kind
        if k in (K.CLASS_TEMPLATE, K.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION):
            templated = K.from_id(self.lib.clang_getTemplateCursorKind(c))
            return {K.STRUCT_DECL: "struct", K.UNION_DECL: "union"}.get(templated, "class")
        if k == K.FUNCTION_TEMPLATE:
            parent = c.semantic_parent
            return "method" if parent is not None and parent.kind in RECORD_KINDS else "function"
        return KIND_NAMES.get(k, "other")

    @staticmethod
    def _signature(c) -> str | None:
        k = c.kind
        try:
            if k in FUNCTION_KINDS:
                if k in (K.CONSTRUCTOR, K.DESTRUCTOR):
                    text = c.displayname
                else:
                    text = f"{c.result_type.spelling} {c.displayname}"
                if k in (K.CXX_METHOD, K.CONVERSION_FUNCTION) and c.is_const_method():
                    text += " const"
                return text
            if k in VALUE_KINDS and k != K.ENUM_CONSTANT_DECL:
                return f"{c.type.spelling} {c.spelling}"
            if k in ALIAS_KINDS:
                return f"{c.spelling} = {c.underlying_typedef_type.spelling}"
        except Exception:  # noqa: BLE001 - spelling of unusual types can fail
            return None
        return None

    @staticmethod
    def _access(c) -> str | None:
        spec = c.access_specifier
        if spec in (ci.AccessSpecifier.PUBLIC, ci.AccessSpecifier.PROTECTED, ci.AccessSpecifier.PRIVATE):
            return spec.name.lower()
        return None

    @staticmethod
    def _doc(c) -> str | None:
        try:
            text = c.raw_comment
        except Exception:  # noqa: BLE001
            return None
        return text[:DOC_LIMIT] if text else None

    def _new_symbol(self, c, sid: str, external: bool) -> dict:
        parent = self._parent(c)
        parent_id = self.symbol_id(parent) if parent is not None else None
        if c.kind == K.NAMESPACE and not c.spelling:
            display = "(anonymous)"
        elif c.kind in TYPE_KINDS:
            display = self._type_name(c)
        else:
            display = c.spelling or "(unnamed)"
        record = {
            "type": "symbol",
            "id": sid,
            "display_name": display,
            "kind": self._kind_name(c),
            "parent_id": parent_id,
            "signature": self._signature(c),
            "doc": self._doc(c),
            "access": self._access(c),
            "defs": [],
            "decls": [],
            "external": external,
        }
        usr = c.get_usr()
        if usr:
            record["usr"] = usr
        self.symbols[sid] = record
        if parent is not None and parent_id is not None and parent_id not in self.symbols:
            _, cls = self._file_class(parent)
            self._new_symbol(self._resolve(parent), parent_id, external=cls == "outside")
        return record

    @staticmethod
    def _is_definition(c) -> bool:
        """TU-independent: libclang reports `= default` as a definition only where the function is used."""
        if c.kind == K.MACRO_DEFINITION or c.is_definition():
            return True
        if c.kind in (K.CXX_METHOD, K.CONSTRUCTOR, K.DESTRUCTOR, K.CONVERSION_FUNCTION):
            try:
                return c.is_default_method() or c.is_deleted_method()
            except AttributeError:  # older bindings
                return c.is_default_method()
        return False

    def _add_loc(self, record: dict, c, path: str) -> None:
        loc = self._loc(c, path)
        target = record["defs"] if self._is_definition(c) else record["decls"]
        if loc not in target:
            target.append(loc)

    def emit_decl(self, c, path: str | None) -> str | None:
        """A declaration found while walking project code."""
        sid = self.symbol_id(c)
        if sid is None:
            return None
        record = self.symbols.get(sid) or self._new_symbol(c, sid, external=False)
        record["external"] = False
        if path is not None and c.kind != K.NAMESPACE:
            self._add_loc(record, c, path)
        return sid

    def ensure_target(self, target) -> str | None:
        """A referenced symbol: make sure a record exists, with locations if it lives in an ignored file."""
        t = self._resolve(target)
        sid = self.symbol_id(t)
        if sid is None or sid in self.symbols:
            return sid
        rel, cls = self._file_class(t)
        record = self._new_symbol(t, sid, external=cls == "outside")
        if cls == "ignored" and t.kind != K.NAMESPACE:
            self._add_loc(record, t, rel)
            definition = t.get_definition()
            if definition is not None and definition != t:
                def_rel, def_cls = self._file_class(definition)
                if def_cls == "ignored":
                    self._add_loc(record, definition, def_rel)
        return sid

    # ---------------------------------------------------------------- relations

    def _overridden(self, c) -> list:
        array = ctypes.POINTER(ci.Cursor)()
        count = ctypes.c_uint()
        self.lib.clang_getOverriddenCursors(c, ctypes.byref(array), ctypes.byref(count))
        result = []
        for i in range(count.value):
            copy = ci.Cursor.from_buffer_copy(bytes(array[i]))
            copy._tu = c._tu
            result.append(copy)
        if count.value:
            self.lib.clang_disposeOverriddenCursors(array)
        return result

    def _relations_for(self, c, sid: str) -> None:
        k = c.kind
        if k == K.CXX_METHOD and c.is_virtual_method():
            for overridden in self._overridden(c):
                oid = self.ensure_target(overridden)
                if oid:
                    self.relations.add((sid, oid, "overrides"))
        elif k in (K.TYPEDEF_DECL, K.TYPE_ALIAS_DECL):
            try:
                underlying = c.underlying_typedef_type.get_declaration()
            except Exception:  # noqa: BLE001
                return
            if underlying is not None and underlying.kind in TYPE_KINDS | ALIAS_KINDS:
                uid = self.ensure_target(underlying)
                if uid and uid != sid:
                    self.relations.add((sid, uid, "type_definition"))

    # ---------------------------------------------------------------- references

    @staticmethod
    def _is_implicit_member(target) -> bool:
        """Special members the compiler generates carry the location of their class."""
        if target.kind not in (K.CONSTRUCTOR, K.DESTRUCTOR, K.CXX_METHOD):
            return False
        parent = target.semantic_parent
        return parent is not None and _same_location(target, parent)

    def _emit_ref(self, cursor, target, role: str, container: str | None) -> None:
        if target is None or target.kind not in SYMBOL_KINDS or target.kind == K.NAMESPACE:
            return
        if self._is_implicit_member(target):
            return  # construction is already visible as a use of the class type
        path = self._project_path(cursor)
        if path is None:
            return
        tid = self.ensure_target(target)
        if tid is None:
            return
        loc = cursor.location
        line, col = max(loc.line - 1, 0), max(loc.column - 1, 0)
        name_len = len(target.spelling.encode("utf-8")) if target.spelling else 0
        self.refs.append((tid, path, line, col, line, col + name_len, role, container))

    def _emit_call(self, call, container: str | None) -> None:
        target = call.referenced
        if target is None:
            return
        # Point the call at the callee's name and do not report that name again as a reference.
        where = call
        node = call
        for _ in range(4):
            first = next(iter(node.get_children()), None)
            if first is None:
                break
            if first.kind in REF_EXPR_KINDS:
                if first.referenced is not None and first.referenced == target:
                    self._skip_refs.add(first.hash)
                    where = first
                break
            if first.kind != K.UNEXPOSED_EXPR:
                break
            node = first
        self._emit_ref(where, target, "call", container)

    # ---------------------------------------------------------------- walking

    def _add_extent(self, path: str, c, sid: str, is_function: bool) -> None:
        ext = c.extent
        self._extents.setdefault(path, []).append(
            (ext.start.line - 1, ext.start.column - 1, ext.end.line - 1, ext.end.column - 1, sid, is_function)
        )

    def _container_at(self, path: str, line: int, col: int) -> str | None:
        """Innermost function (else class) around a macro expansion, excluding code the expansion produced."""
        best_fn = best_rec = None
        for sl, sc, el, ec, sid, is_function in self._extents.get(path, ()):
            if (sl, sc) == (line, col) or not ((sl, sc) <= (line, col) < (el, ec)):
                continue
            span = (el - sl, ec - sc)
            if is_function:
                if best_fn is None or span < best_fn[0]:
                    best_fn = (span, sid)
            elif best_rec is None or span < best_rec[0]:
                best_rec = (span, sid)
        if best_fn:
            return best_fn[1]
        return best_rec[1] if best_rec else None

    def _preprocessor(self, c, rel: str) -> None:
        if c.kind == K.MACRO_DEFINITION:
            if sum(1 for _ in c.get_tokens()) <= 1:
                return  # only the name: include guards and empty flags
            self.emit_decl(c, rel)
        elif c.kind == K.MACRO_INSTANTIATION:
            target = c.referenced
            if target is None or target.location.file is None:
                return  # builtin macros
            tid = self.ensure_target(target)
            if tid is None:
                return
            loc = c.location
            self._expansions.append((tid, rel, max(loc.line - 1, 0), max(loc.column - 1, 0), len(c.spelling.encode("utf-8"))))

    def walk(self, tu) -> None:
        done = self.w.done_files
        # (cursor, container, record, local, scope-level)
        stack = [(child, None, None, False, True) for child in reversed(list(tu.cursor.get_children()))]
        while stack:
            c, container, record, local, scope = stack.pop()
            k = c.kind
            if scope:
                rel, cls = self._file_class(c)
                if cls != "project" or rel in done:
                    continue
                self.seen_files.add(rel)
                if k in PREPROCESSOR_KINDS:
                    self._preprocessor(c, rel)
                    continue
            child_container, child_record, child_local, child_scope = container, record, local, False

            if k in SCOPE_KINDS:
                if k == K.NAMESPACE and not local:
                    self.emit_decl(c, None)
                child_scope = not local
            elif k in SYMBOL_KINDS:
                if k in FUNCTION_KINDS and c.is_definition():
                    child_local = True
                if not local and not self._is_transparent(c):
                    path = self._project_path(c)
                    sid = self.emit_decl(c, path) if path else None
                    if sid:
                        self._relations_for(c, sid)
                        if k in FUNCTION_KINDS and c.is_definition():
                            child_container = sid
                            self._add_extent(path, c, sid, True)
                        elif k in TYPE_KINDS and c.is_definition():
                            child_container = child_record = sid
                            self._add_extent(path, c, sid, False)
            elif k == K.LAMBDA_EXPR:
                child_local = True
            elif k == K.CXX_BASE_SPECIFIER and record and not local:
                base = c.referenced or c.type.get_declaration()
                if base is not None and base.kind in TYPE_KINDS:
                    bid = self.ensure_target(base)
                    if bid:
                        self.relations.add((record, bid, "inherits"))

            if k == K.CALL_EXPR:
                self._emit_call(c, container)
            elif k in REF_EXPR_KINDS:
                if c.hash not in self._skip_refs:
                    self._emit_ref(c, c.referenced, "reference", container)
            elif k in TYPE_REF_KINDS:
                self._emit_ref(c, c.referenced, "reference", container)

            children = list(c.get_children())
            for child in reversed(children):
                stack.append((child, child_container, child_record, child_local, child_scope))

        for tid, rel, line, col, length in self._expansions:
            self.refs.append((tid, rel, line, col, line, col + length, "expansion", self._container_at(rel, line, col)))
        done |= self.seen_files


def _parse(index, path: str, args: list[str]):
    try:
        return index.parse(path, args=args, options=PARSE_OPTIONS)
    except ci.TranslationUnitLoadError:
        return None


def _diagnostics(tu, worker: _Worker) -> tuple[int, list[str]]:
    count = 0
    messages: list[str] = []
    for d in tu.diagnostics:
        if d.severity < ci.Diagnostic.Error:
            continue
        count += 1
        if len(messages) < 5:
            f = d.location.file
            where = worker.classify(f.name)[0] or os.path.basename(f.name) if f else "<unknown>"
            messages.append(f"{where}:{d.location.line}: {d.spelling}")
    return count, messages


def index_tu(task: tuple[str, str, list[str], str]) -> dict:
    """task = (absolute source path, relative path, libclang arguments, working directory)."""
    source, rel, args, directory = task
    worker = _worker
    assert worker is not None, "init_worker() was not called"
    t0 = time.perf_counter()
    try:
        os.chdir(directory)
    except OSError:
        pass
    stl_workaround = False
    tu = _parse(worker.index, source, args)
    if tu is None:
        return {"tu": rel, "fatal": True, "errors": 1, "messages": [f"{rel}: libclang could not parse the file"],
                "parse_s": time.perf_counter() - t0, "walk_s": 0.0, "stl_workaround": False,
                "symbols": {}, "refs": [], "relations": [], "files": []}
    errors, messages = _diagnostics(tu, worker)
    if errors and any("STL1000" in m for m in messages):
        tu = _parse(worker.index, source, args + [STL_MISMATCH_DEFINE]) or tu
        errors, messages = _diagnostics(tu, worker)
        stl_workaround = True
    t1 = time.perf_counter()
    walker = _TuWalker(worker)
    walker.walk(tu)
    t2 = time.perf_counter()
    result = {
        "tu": rel,
        "fatal": False,
        "errors": errors,
        "messages": messages,
        "parse_s": t1 - t0,
        "walk_s": t2 - t1,
        "stl_workaround": stl_workaround,
        "symbols": walker.symbols,
        "refs": walker.refs,
        "relations": sorted(walker.relations),
        "files": sorted(walker.seen_files),
    }
    del tu
    return result
