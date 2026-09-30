"""Fact store v0 on SQLite: the only module in CARMA that contains SQL."""

from __future__ import annotations

import sqlite3
from array import array
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from carma.paths import glob_match
from carma.store.api import (
    CONTRACT_VERSION,
    CallEdge,
    ComponentEdge,
    FactsHeader,
    Loc,
    Ref,
    Relation,
    StoreStats,
    Symbol,
)

ROLE_BITS = {"call": 1, "reference": 2, "expansion": 4, "definition": 8, "forward_decl": 16, "read": 32, "write": 64}
DECLARATION_ROLES = ROLE_BITS["definition"] | ROLE_BITS["forward_decl"]
TYPE_KINDS = ("class", "struct", "union", "enum", "type_alias", "concept")
EXTERNAL_COMPONENT = "_external"
BATCH = 10_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, sha256 TEXT, language TEXT, load_hash TEXT);
CREATE TABLE IF NOT EXISTS symbols(
  key INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, display_name TEXT, kind TEXT, parent_key INTEGER,
  signature TEXT, doc TEXT, access TEXT, usr TEXT, external INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS symbol_locs(
  symbol_key INTEGER NOT NULL, is_def INTEGER NOT NULL, path TEXT NOT NULL,
  sl INT, sc INT, el INT, ec INT, esl INT, esc INT, eel INT, eec INT,
  UNIQUE(symbol_key, is_def, path, sl, sc));
CREATE TABLE IF NOT EXISTS refs(
  symbol_key INTEGER NOT NULL, path TEXT NOT NULL, sl INT, sc INT, el INT, ec INT,
  roles INT NOT NULL, container_key INTEGER);
CREATE TABLE IF NOT EXISTS relations(from_key INTEGER NOT NULL, to_key INTEGER NOT NULL, kind TEXT NOT NULL,
  UNIQUE(from_key, to_key, kind));
CREATE TABLE IF NOT EXISTS membership(symbol_key INTEGER PRIMARY KEY, component TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS component_edges(src TEXT NOT NULL, dst TEXT NOT NULL, refs INT, calls INT, uses INT,
  PRIMARY KEY(src, dst));
CREATE INDEX IF NOT EXISTS refs_symbol ON refs(symbol_key);
CREATE INDEX IF NOT EXISTS refs_container ON refs(container_key);
CREATE INDEX IF NOT EXISTS refs_path ON refs(path);
CREATE INDEX IF NOT EXISTS symbols_name ON symbols(display_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS symbols_parent ON symbols(parent_key);
CREATE INDEX IF NOT EXISTS locs_symbol ON symbol_locs(symbol_key);
CREATE INDEX IF NOT EXISTS locs_path ON symbol_locs(path);
CREATE INDEX IF NOT EXISTS relations_to ON relations(to_key);
"""


def _roles(bits: int) -> frozenset[str]:
    return frozenset(name for name, bit in ROLE_BITS.items() if bits & bit)


class _CallGraph:
    """Call edges in CSR arrays: offsets and targets for both directions."""

    def __init__(self, edges: list[tuple[int, int, str, int]]):
        keys = sorted({k for edge in edges for k in edge[:2]})
        self.keys = keys
        self.index = {k: i for i, k in enumerate(keys)}
        forward: list[list[int]] = [[] for _ in keys]
        backward: list[list[int]] = [[] for _ in keys]
        self.where: dict[tuple[int, int], tuple[str, int]] = {}
        for caller, callee, path, line in edges:
            a, b = self.index[caller], self.index[callee]
            forward[a].append(b)
            backward[b].append(a)
            self.where[(caller, callee)] = (path, line)
        self.f_off, self.f_tgt = self._csr(forward)
        self.b_off, self.b_tgt = self._csr(backward)

    @staticmethod
    def _csr(lists: list[list[int]]) -> tuple[array, array]:
        offsets, targets = array("q", [0]), array("q")
        for items in lists:
            targets.extend(sorted(items))
            offsets.append(len(targets))
        return offsets, targets

    def out(self, i: int) -> array:
        return self.f_tgt[self.f_off[i]:self.f_off[i + 1]]

    def into(self, i: int) -> array:
        return self.b_tgt[self.b_off[i]:self.b_off[i + 1]]


class _Load:
    def __init__(self, store: SQLiteStore, header: FactsHeader):
        self.s = store
        self.header = header
        self.db = store._db
        self.db.execute("PRAGMA synchronous=OFF")
        self.db.execute("BEGIN")
        self.db.execute("DELETE FROM relations")  # every session carries the complete relation set
        self.keys: dict[str, int] = dict(self.db.execute("SELECT id, key FROM symbols"))
        self.locs: list[tuple] = []
        self.refs: list[tuple] = []
        self.relations: list[tuple] = []

    def _key(self, sid: str) -> int:
        key = self.keys.get(sid)
        if key is None:
            key = self.db.execute("INSERT INTO symbols(id) VALUES (?)", (sid,)).lastrowid
            self.keys[sid] = key
        return key

    def _flush(self) -> None:
        if self.locs:
            self.db.executemany("INSERT OR IGNORE INTO symbol_locs VALUES (?,?,?,?,?,?,?,?,?,?,?)", self.locs)
            self.locs.clear()
        if self.refs:
            self.db.executemany("INSERT INTO refs VALUES (?,?,?,?,?,?,?,?)", self.refs)
            self.refs.clear()
        if self.relations:
            self.db.executemany("INSERT OR IGNORE INTO relations VALUES (?,?,?)", self.relations)
            self.relations.clear()

    def put(self, record: dict) -> None:
        kind = record["type"]
        if kind == "file":
            self.db.execute(
                "INSERT OR REPLACE INTO files(path, sha256, language, load_hash) VALUES (?,?,?,?)",
                (record["path"], record["sha256"], record["language"], record.get("load_hash", record["sha256"])),
            )
        elif kind == "symbol":
            key = self._key(record["id"])
            parent = record.get("parent_id")
            self.db.execute(
                "UPDATE symbols SET display_name=?, kind=?, parent_key=?, signature=?, doc=?, access=?, usr=?, external=? WHERE key=?",
                (record["display_name"], record["kind"], self._key(parent) if parent else None, record.get("signature"),
                 record.get("doc"), record.get("access"), record.get("usr"), int(record["external"]), key),
            )
            for is_def, locs in ((1, record["defs"]), (0, record["decls"])):
                for loc in locs:
                    self.locs.append((key, is_def, loc["path"], *loc["range"], *loc["extent"]))
        elif kind == "ref":
            bits = 0
            for role in record["roles"]:
                bits |= ROLE_BITS[role]
            container = record["container"]
            self.refs.append((self._key(record["symbol"]), record["path"], *record["range"], bits,
                              self._key(container) if container else None))
        elif kind == "relation":
            self.relations.append((self._key(record["from"]), self._key(record["to"]), record["kind"]))
        if len(self.locs) + len(self.refs) + len(self.relations) >= BATCH:
            self._flush()

    def delete_file(self, path: str) -> None:
        self._flush()
        self.db.execute("DELETE FROM refs WHERE path=?", (path,))
        self.db.execute("DELETE FROM symbol_locs WHERE path=?", (path,))
        self.db.execute("DELETE FROM files WHERE path=?", (path,))

    def commit(self) -> None:
        self._flush()
        while True:  # remove symbols nothing points to any more; parents go on the next round
            removed = self.db.execute(
                """DELETE FROM symbols WHERE
                     NOT EXISTS (SELECT 1 FROM symbol_locs l WHERE l.symbol_key = symbols.key)
                 AND NOT EXISTS (SELECT 1 FROM refs r WHERE r.symbol_key = symbols.key)
                 AND NOT EXISTS (SELECT 1 FROM refs r WHERE r.container_key = symbols.key)
                 AND NOT EXISTS (SELECT 1 FROM relations x WHERE x.from_key = symbols.key OR x.to_key = symbols.key)
                 AND NOT EXISTS (SELECT 1 FROM symbols c WHERE c.parent_key = symbols.key)"""
            ).rowcount
            if not removed:
                break
        self.db.execute("DELETE FROM membership WHERE symbol_key NOT IN (SELECT key FROM symbols)")
        meta = {
            "facts_version": self.header.facts_version,
            "platform": self.header.platform,
            "indexer": f"{self.header.indexer_name} {self.header.indexer_version}",
            "clang": self.header.clang_version or "",
            "project_root": self.header.project_root,
            "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.db.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", meta.items())
        self.s._recompute_edges()
        self.db.execute("COMMIT")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.s._graph = None


class SQLiteStore:
    """FactStore on SQLite; path ':memory:' gives a throwaway store."""

    contract_version = CONTRACT_VERSION

    def __init__(self, path: Path | str):
        self.path = path
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._graph: _CallGraph | None = None

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------------------------------------------------------- loading

    def begin_load(self, header: FactsHeader) -> _Load:
        return _Load(self, header)

    def file_hashes(self) -> dict[str, str]:
        return dict(self._db.execute("SELECT path, load_hash FROM files"))

    def meta(self) -> dict[str, str]:
        return dict(self._db.execute("SELECT key, value FROM meta"))

    # ---------------------------------------------------------------- lookup

    _SYMBOL_SELECT = """SELECT s.key, s.id, s.display_name, s.kind, p.id, s.signature, s.doc, s.access, s.external, s.usr
                        FROM symbols s LEFT JOIN symbols p ON p.key = s.parent_key"""

    def _symbol(self, row) -> Symbol:
        key = row[0]
        defs, decls = [], []
        for is_def, path, sl, sc, el, ec, esl, esc, eel, eec in self._db.execute(
            "SELECT is_def, path, sl, sc, el, ec, esl, esc, eel, eec FROM symbol_locs WHERE symbol_key=? ORDER BY path, sl, sc",
            (key,),
        ):
            (defs if is_def else decls).append(Loc(path, (sl, sc, el, ec), (esl, esc, eel, eec)))
        return Symbol(id=row[1], display_name=row[2], kind=row[3], parent_id=row[4], signature=row[5], doc=row[6],
                      access=row[7], defs=tuple(defs), decls=tuple(decls), external=bool(row[8]), usr=row[9])

    def _key_of(self, sid: str) -> int | None:
        row = self._db.execute("SELECT key FROM symbols WHERE id=?", (sid,)).fetchone()
        return row[0] if row else None

    def get_symbol(self, id: str) -> Symbol | None:
        row = self._db.execute(self._SYMBOL_SELECT + " WHERE s.id=? AND s.kind IS NOT NULL", (id,)).fetchone()
        return self._symbol(row) if row else None

    def search_symbols(self, text: str, kinds: list[str] | None = None, limit: int = 50) -> list[Symbol]:
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql = self._SYMBOL_SELECT + " WHERE s.kind IS NOT NULL AND s.kind != 'namespace' AND s.display_name LIKE ? ESCAPE '\\'"
        params: list = [f"%{escaped}%"]
        if kinds:
            sql += f" AND s.kind IN ({','.join('?' * len(kinds))})"
            params += kinds
        sql += (" ORDER BY lower(s.display_name) = lower(?) DESC, s.display_name LIKE ? ESCAPE '\\' DESC,"
                " s.external, length(s.display_name), s.id LIMIT ?")
        params += [text, f"{escaped}%", limit]
        return [self._symbol(row) for row in self._db.execute(sql, params).fetchall()]

    def symbols_in_file(self, path: str) -> list[Symbol]:
        rows = self._db.execute(
            self._SYMBOL_SELECT + " JOIN (SELECT symbol_key, MIN(sl) AS line FROM symbol_locs WHERE path=? GROUP BY symbol_key) l"
            " ON l.symbol_key = s.key ORDER BY l.line, s.id",
            (path,),
        ).fetchall()
        return [self._symbol(row) for row in rows]

    def list_files(self, glob: str | None = None) -> list[str]:
        paths = [row[0] for row in self._db.execute("SELECT path FROM files ORDER BY path")]
        return [p for p in paths if glob is None or glob_match(p, glob)]

    def symbol_at(self, path: str, line: int) -> Symbol | None:
        """Innermost symbol whose extent contains the 0-based line."""
        row = self._db.execute(
            """SELECT symbol_key FROM symbol_locs WHERE path=? AND esl <= ? AND eel >= ?
               ORDER BY (eel - esl), esl DESC, esc DESC LIMIT 1""",
            (path, line, line),
        ).fetchone()
        if not row:
            return None
        return self._symbol(self._db.execute(self._SYMBOL_SELECT + " WHERE s.key=?", (row[0],)).fetchone())

    _REF_SELECT = """SELECT t.id, r.path, r.sl, r.sc, r.el, r.ec, r.roles, c.id
                     FROM refs r JOIN symbols t ON t.key = r.symbol_key LEFT JOIN symbols c ON c.key = r.container_key"""

    @staticmethod
    def _ref(row) -> Ref:
        return Ref(symbol=row[0], path=row[1], range=(row[2], row[3], row[4], row[5]), roles=_roles(row[6]), container=row[7])

    def refs_to(self, id: str, limit: int = 500) -> list[Ref]:
        rows = self._db.execute(self._REF_SELECT + " WHERE t.id=? ORDER BY r.path, r.sl, r.sc LIMIT ?", (id, limit))
        return [self._ref(row) for row in rows]

    def refs_from(self, container_id: str, limit: int = 500) -> list[Ref]:
        rows = self._db.execute(self._REF_SELECT + " WHERE c.id=? ORDER BY r.path, r.sl, r.sc LIMIT ?", (container_id, limit))
        return [self._ref(row) for row in rows]

    def relations(self, id: str, kind: str | None = None, direction: str = "out") -> list[Relation]:
        side = "a.id" if direction == "out" else "b.id"
        sql = f"""SELECT a.id, b.id, x.kind FROM relations x JOIN symbols a ON a.key = x.from_key
                  JOIN symbols b ON b.key = x.to_key WHERE {side}=?"""
        params: list = [id]
        if kind:
            sql += " AND x.kind=?"
            params.append(kind)
        sql += " ORDER BY a.id, b.id, x.kind"
        return [Relation(a, b, k) for a, b, k in self._db.execute(sql, params)]

    # ---------------------------------------------------------------- derived data

    def set_membership(self, mapping: Iterable[tuple[str, str]]) -> None:
        self._db.execute("BEGIN")
        self._db.execute("DELETE FROM membership")
        keys = dict(self._db.execute("SELECT id, key FROM symbols"))
        self._db.executemany(
            "INSERT OR REPLACE INTO membership VALUES (?,?)",
            ((keys[sid], component) for sid, component in mapping if sid in keys),
        )
        self._recompute_edges()
        self._db.execute("COMMIT")

    def _recompute_edges(self) -> None:
        kinds = ",".join(f"'{k}'" for k in TYPE_KINDS)
        self._db.execute("DELETE FROM component_edges")
        self._db.execute(
            f"""INSERT INTO component_edges(src, dst, refs, calls, uses)
                SELECT mc.component, mt.component, COUNT(*),
                       SUM(CASE WHEN r.roles & 1 THEN 1 ELSE 0 END),
                       SUM(CASE WHEN (r.roles & 2) AND t.kind IN ({kinds}) THEN 1 ELSE 0 END)
                FROM refs r
                JOIN membership mc ON mc.symbol_key = r.container_key
                JOIN membership mt ON mt.symbol_key = r.symbol_key
                JOIN symbols t ON t.key = r.symbol_key
                WHERE mc.component <> mt.component AND (r.roles & {DECLARATION_ROLES}) = 0
                GROUP BY mc.component, mt.component"""
        )

    def component_edges(self, include_external: bool = False) -> list[ComponentEdge]:
        sql = "SELECT src, dst, refs, calls, uses FROM component_edges"
        if not include_external:
            sql += f" WHERE src <> '{EXTERNAL_COMPONENT}' AND dst <> '{EXTERNAL_COMPONENT}'"
        sql += " ORDER BY src, dst"
        return [ComponentEdge(*row) for row in self._db.execute(sql)]

    def edge_samples(self, src: str, dst: str, limit: int = 20) -> list[Ref]:
        rows = self._db.execute(
            self._REF_SELECT + f""" JOIN membership mc ON mc.symbol_key = r.container_key
                JOIN membership mt ON mt.symbol_key = r.symbol_key
                WHERE mc.component=? AND mt.component=? AND (r.roles & {DECLARATION_ROLES}) = 0
                ORDER BY r.path, r.sl, r.sc LIMIT ?""",
            (src, dst, limit),
        )
        return [self._ref(row) for row in rows]

    # ---------------------------------------------------------------- traversals

    def _call_graph(self) -> _CallGraph:
        if self._graph is None:
            rows = self._db.execute(
                f"""SELECT container_key, symbol_key, MIN(path), MIN(sl) FROM refs
                    WHERE (roles & {ROLE_BITS['call']}) AND container_key IS NOT NULL
                    GROUP BY container_key, symbol_key"""
            ).fetchall()
            self._graph = _CallGraph(rows)
        return self._graph

    def _ids(self, keys: Iterable[int]) -> dict[int, str]:
        keys = list(set(keys))
        result: dict[int, str] = {}
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            result.update(self._db.execute(f"SELECT key, id FROM symbols WHERE key IN ({','.join('?' * len(chunk))})", chunk))
        return result

    def _walk(self, id: str, depth: int, forward: bool) -> list[CallEdge]:
        graph = self._call_graph()
        key = self._key_of(id)
        if key is None or key not in graph.index:
            return []
        start = graph.index[key]
        seen = {start}
        frontier = [start]
        found: list[tuple[int, int, int]] = []
        for level in range(1, depth + 1):
            nxt = []
            for node in frontier:
                for other in (graph.out(node) if forward else graph.into(node)):
                    found.append((node, other, level) if forward else (other, node, level))
                    if other not in seen:
                        seen.add(other)
                        nxt.append(other)
            frontier = nxt
            if not frontier:
                break
        names = self._ids(graph.keys[i] for edge in found for i in edge[:2])
        edges = []
        for a, b, level in found:
            ka, kb = graph.keys[a], graph.keys[b]
            path, line = graph.where[(ka, kb)]
            edges.append(CallEdge(caller=names[ka], callee=names[kb], path=path, line=line, depth=level))
        return edges

    def callers(self, id: str, depth: int = 1) -> list[CallEdge]:
        return self._walk(id, depth, forward=False)

    def callees(self, id: str, depth: int = 1) -> list[CallEdge]:
        return self._walk(id, depth, forward=True)

    def paths(self, src: str, dst: str, max_depth: int = 6, limit: int = 5) -> list[list[str]]:
        """Shortest call chains from src to dst (BFS with a depth limit)."""
        graph = self._call_graph()
        ks, kd = self._key_of(src), self._key_of(dst)
        if ks is None or kd is None or ks not in graph.index or kd not in graph.index:
            return []
        start, goal = graph.index[ks], graph.index[kd]
        if start == goal:
            return [[src]]
        preds: dict[int, list[int]] = {start: []}
        frontier = [start]
        for _ in range(max_depth):
            nxt: list[int] = []
            for node in frontier:
                for other in graph.out(node):
                    if other not in preds:
                        preds[other] = [node]
                        nxt.append(other)
                    elif other in nxt:
                        preds[other].append(node)
            if goal in preds or not nxt:
                break
            frontier = nxt
        if goal not in preds:
            return []
        chains: list[list[int]] = []

        def back(node: int, tail: list[int]) -> None:
            if len(chains) >= limit:
                return
            if node == start:
                chains.append([start, *tail])
                return
            for prev in preds[node]:
                back(prev, [node, *tail])

        back(goal, [])
        names = self._ids(graph.keys[i] for chain in chains for i in chain)
        return [[names[graph.keys[i]] for i in chain] for chain in chains]

    def stats(self) -> StoreStats:
        count = lambda sql: self._db.execute(sql).fetchone()[0]  # noqa: E731
        meta = self.meta()
        return StoreStats(
            files=count("SELECT COUNT(*) FROM files"),
            symbols=count("SELECT COUNT(*) FROM symbols WHERE kind IS NOT NULL"),
            refs=count("SELECT COUNT(*) FROM refs"),
            relations=count("SELECT COUNT(*) FROM relations"),
            facts_version=meta.get("facts_version"),
            platform=meta.get("platform"),
            loaded_at=meta.get("loaded_at"),
        )
