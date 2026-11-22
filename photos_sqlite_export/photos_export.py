#!/usr/bin/env python3
"""photos_export.py - export any iOS Photos.sqlite to CSV.

Works from a merged query catalog (catalog.json, built from the archived
iOS 11-17 query repo and the iLEAPP Ph001/Ph002 artifacts covering iOS 11-26).
Every table and column reference is checked against the actual database before
the query runs: missing tables drop their JOIN, missing columns drop their
output column (or become NULL with --keep-missing).  A prepare-time retry loop
catches anything the schema check missed.  The goal is always to produce a
CSV, never to fail on a schema the catalog does not know.

When a non-empty <database>-wal sidecar is present the export automatically
becomes a WAL replay differential: every committed transaction boundary in
the WAL is replayed on a COPY (db + the wal truncated to that commit - the
exact state a crash at that point would leave), including state 0 (the
pre-WAL snapshot of the main file, via immutable=1).  All states are merged
per asset (zAsset-zPK) into one CSV with wal-diff-status = unchanged /
added / modified / removed plus wal-first-commit / wal-last-commit
provenance (0 = snapshot).  Assets that only ever existed inside the WAL
(created and later deleted before any checkpoint) come out as removed with
the values of the last state that saw them - e.g. still carrying the trash
markers from the deletion commit.  The originals are never modified, so
re-running sees the same WAL.  --no-wal-diff restores the plain
single-pass export.  Residue beyond committed WAL history (rollback
journal, free blocks, uncommitted frames) needs a carver such as
sqlite4n6.

Usage:
    python photos_export.py <Photos.sqlite> [-o OUTDIR] [--profile basic]
        [--filter hidden trashed ...] [--all-filters] [--where "SQL"]
        [--keep-missing] [--limit N] [--dump-sql] [--list] [--catalog PATH]
        [--no-wal-diff] [--keep-wal-work] [--wal-replay-limit N]

Exit codes: 0 every requested CSV was written; 1 some outputs were skipped
    (or the WAL diff had to fall back to single-pass); 2 the file is not a
    usable Photos database.
"""

import argparse
import csv
import io
import json
import os
import re
import shutil
import sqlite3
import struct
import sys
from pathlib import Path

DEFAULT_CATALOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "catalog.json")

# asset-album join table number -> iOS versions it appears in (informational;
# numbers refer to Z_<N>ASSETS, the asset<->album link table)
JOIN_TABLE_IOS_HINT = {
    20: "iOS 11", 23: "iOS 12", 26: "iOS 13/14", 27: "iOS 15",
    28: "iOS 16-17.5", 29: "iOS 17.6", 30: "iOS 18", 33: "iOS 26",
}

REF_RE = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*|\{\{[A-Z_]+\}\})")
COLPAIR_RE = re.compile(r"^Z_(\d+)(ASSETS|ALBUMS|ALBUMLISTS)$")


class Report(object):
    def __init__(self):
        self.lines = []

    def add(self, text=""):
        self.lines.append(text)

    def dump(self, path):
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(self.lines) + "\n")


class Schema(object):
    """Case-insensitive view of the database's tables and columns."""

    def __init__(self, conn):
        self.tables = {}          # lower name -> (real name, {col lower: real})
        for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"):
            cols = {}
            try:
                info = conn.execute('PRAGMA table_info("%s")' % name)
            except sqlite3.Error:
                continue
            for _cid, cname, _typ, _nn, _dflt, _pk in info:
                cols[cname.lower()] = cname
            self.tables[name.lower()] = (name, cols)

    def table(self, name):
        return self.tables.get(name.lower())

    def has_column(self, table, column):
        t = self.tables.get(table.lower())
        return bool(t) and column.lower() in t[1]

    def real_column(self, table, column):
        t = self.tables.get(table.lower())
        return t[1].get(column.lower()) if t else None


# ---------------------------------------------------------------------------
# Dynamic Core Data join discovery
# ---------------------------------------------------------------------------

def _entity_map(conn):
    ents = {}
    try:
        for ent, name in conn.execute("SELECT Z_ENT, Z_NAME FROM Z_PRIMARYKEY"):
            ents[int(ent)] = (name or "").strip()
    except sqlite3.Error:
        pass
    return ents


def _find_link_table(schema, ents, table_re, want):
    """Common walker for Z_<N>ASSETS / Z_<N>ALBUMLISTS link tables.

    want maps the column-numbering role (ASSETS/ALBUMS/ALBUMLISTS) to the
    entity names that column stands for.  Returns
    (table, {role: column}) for the first table where every role resolves,
    preferring Z_PRIMARYKEY entity names, falling back to pattern matching.
    """
    def by_entities(real, cols):
        found = {}
        for cr in cols.values():
            cm = COLPAIR_RE.match(cr)
            if not cm:
                continue
            role, num = cm.group(2), cm.group(1)
            ent = ents.get(int(num), "")
            for want_role, names in want.items():
                if role == want_role and ent in names:
                    found[want_role] = cr
        return found if len(found) == len(want) else None

    def by_pattern(real, cols):
        found = {}
        for cr in cols.values():
            cm = COLPAIR_RE.match(cr)
            if not cm:
                continue
            role = cm.group(2)
            if role in want and role not in found:
                found[role] = cr
        if len(found) == len(want) and len(set(found.values())) == len(want):
            return found
        return None

    for matcher in (by_entities, by_pattern):
        for lname, (real, cols) in sorted(schema.tables.items()):
            if not table_re.match(lname):
                continue
            got = matcher(real, cols)
            if got:
                return real, got
    return None


def discover_asset_album_join(schema, conn):
    """(table, album_col, asset_col) or None.

    Core Data names the link table and its columns after entity numbers, and
    the numbering shifts between releases (Z_28ASSETS on iOS 16/17, Z_29ASSETS
    on 17.6, Z_30ASSETS on 18, Z_33ASSETS on 26...).  Z_PRIMARYKEY maps the
    numbers to entity names, so the table is found by meaning, not by version.
    """
    ents = _entity_map(conn)
    got = _find_link_table(
        schema, ents, re.compile(r"^z_\d+assets$"),
        {"ALBUMS": ("Album", "GenericAlbum"),
         "ASSETS": ("Asset", "GenericAsset")})
    if got:
        return got[0], got[1]["ALBUMS"], got[1]["ASSETS"]
    return None


def discover_album_list_join(schema, conn):
    """(table, album_col, list_col) or None."""
    ents = _entity_map(conn)
    got = _find_link_table(
        schema, ents, re.compile(r"^z_\d+albumlists$"),
        {"ALBUMS": ("Album", "GenericAlbum"),
         "ALBUMLISTS": ("AlbumList", "GenericAlbumList")})
    if got:
        return got[0], got[1]["ALBUMS"], got[1]["ALBUMLISTS"]
    return None


class QueryBuilder(object):
    """Resolve the catalog against one database and build runnable SQL."""

    def __init__(self, catalog, conn, schema, profile, keep_missing=False):
        self.cat = catalog
        self.conn = conn
        self.schema = schema
        self.profile = profile
        self.keep_missing = keep_missing
        self.report = Report()
        self.base = None            # real base table name
        self.aliases = {}           # alias -> {"table": real, "ph": {token: col}}
        self.joins_kept = []        # canonical join dicts that survived
        self.joins_dropped = []     # (alias, reason)
        self.columns = []           # surviving column dicts
        self.null_columns = []      # kept as NULL placeholders
        self.dropped_columns = []   # (name, reason)
        self.where = None
        self.limit = None

    # -- join resolution ---------------------------------------------------

    def resolve_joins(self):
        for cand in self.cat["base_table"]:
            if self.schema.table(cand):
                self.base = self.schema.table(cand)[0]
                break
        if self.base is None:
            return

        aa = discover_asset_album_join(self.schema, self.conn)
        al = discover_album_list_join(self.schema, self.conn)
        placeholders = {}
        if aa:
            placeholders["asset_album_join"] = {
                "table": aa[0],
                "{{AA_ALBUM_FK}}": aa[1], "{{AA_ASSET_FK}}": aa[2]}
        if al:
            placeholders["album_list_join"] = {
                "table": al[0],
                "{{AL_ALBUM_FK}}": al[1], "{{AL_LIST_FK}}": al[2]}

        self.report.add("base table: %s" % self.base)
        if aa:
            n = re.match(r"Z_(\d+)ASSETS", aa[0])
            hint = JOIN_TABLE_IOS_HINT.get(int(n.group(1)), "unknown version") \
                if n else "unknown"
            self.report.add(
                "asset-album join: %s (album FK %s, asset FK %s) - looks like %s"
                % (aa[0], aa[1], aa[2], hint))
        else:
            self.report.add("asset-album join: none found in this database")
        if al:
            self.report.add("album-list join: %s (album FK %s, list FK %s)"
                            % (al[0], al[1], al[2]))
        else:
            self.report.add("album-list join: none found in this database")

        wanted = set(self.cat["profiles"][self.profile])
        pending = [j for j in self.cat["joins"] if j["alias"] in wanted]
        self.aliases = {"zAsset": {"table": self.base, "ph": {}}}

        # dependency-ordered passes: a join resolves once every alias its ON
        # condition mentions is available; one whose dependency is still
        # pending waits for the next pass rather than being dropped
        while pending:
            progress = False
            waiting = {j["alias"] for j in pending}
            for j in list(pending):
                if j["resolve"]:
                    spec = placeholders.get(j["resolve"])
                    if not spec:
                        self.joins_dropped.append(
                            (j["alias"], "link table not present"))
                        pending.remove(j)
                        progress = True
                        continue
                    table, ph = spec["table"], dict(spec)
                else:
                    table = next((self.schema.table(t)[0] for t in j["tables"]
                                  if self.schema.table(t)), None)
                    ph = {}
                    if table is None:
                        self.joins_dropped.append(
                            (j["alias"], "no table %s" % "/".join(j["tables"])))
                        pending.remove(j)
                        progress = True
                        continue
                state, detail = self._on_state(j["on"], j["alias"], table, ph,
                                               waiting)
                if state == "defer":
                    continue
                pending.remove(j)
                progress = True
                if state == "fail":
                    self.joins_dropped.append((j["alias"], detail))
                    continue
                self.aliases[j["alias"]] = {"table": table, "ph": ph}
                self.joins_kept.append(j)
            if not progress:
                for j in pending:
                    self.joins_dropped.append(
                        (j["alias"], "depends on an unavailable join"))
                break

        for alias, reason in self.joins_dropped:
            self.report.add("join dropped: %-22s %s" % (alias, reason))

    def _on_state(self, on, own_alias, table, ph, waiting):
        """('ok'|'defer'|'fail', reason) for one join's ON condition."""
        defer = False
        for a, c in REF_RE.findall(on):
            if a == own_alias:
                if c not in ph and not self.schema.has_column(table, c):
                    return "fail", "%s.%s missing" % (table, c)
                continue
            info = self.aliases.get(a)
            if not info:
                if a in waiting:
                    defer = True
                    continue
                return "fail", "depends on unavailable join %s" % a
            if c not in info["ph"] and \
                    not self.schema.has_column(info["table"], c):
                return "fail", "%s.%s missing" % (info["table"], c)
        return ("defer", None) if defer else ("ok", None)

    # -- column resolution -------------------------------------------------

    def resolve_columns(self):
        for col in self.cat["columns"]:
            reason = self._column_problem(col)
            if reason is None:
                self.columns.append(col)
            elif self.keep_missing:
                self.null_columns.append(col)
            else:
                self.dropped_columns.append((col["name"], reason))
        self.report.add("columns: %d kept, %d dropped, %d as NULL"
                        % (len(self.columns), len(self.dropped_columns),
                           len(self.null_columns)))
        if self.dropped_columns:
            self.report.add("dropped columns (%d):" % len(self.dropped_columns))
            for name, why in self.dropped_columns:
                self.report.add("  %-55s %s" % (name, why))

    def _column_problem(self, col):
        for a, c in col["refs"]:
            info = self.aliases.get(a)
            if not info:
                return "join %s unavailable" % a
            if c.startswith("{{"):
                if c not in info["ph"]:
                    return "link table lacks the FK column"
            elif not self.schema.has_column(info["table"], c):
                return "%s.%s missing" % (info["table"], c)
        return None

    # -- SQL assembly ------------------------------------------------------

    def substitute(self, expr):
        def repl(m):
            a, c = m.group(1), m.group(2)
            info = self.aliases.get(a)
            if info and c in info["ph"]:
                c = info["ph"][c]
            elif info:
                c = self.schema.real_column(info["table"], c) or c
            return '"%s"."%s"' % (a, c)
        return REF_RE.sub(repl, expr)

    def build_sql(self):
        items = []
        for col in self.columns:
            items.append("%s AS '%s'" % (self.substitute(col["expr"]),
                                         col["name"].replace("'", "''")))
        for col in self.null_columns:
            items.append("NULL AS '%s'" % col["name"].replace("'", "''"))
        sql = ["SELECT", ",\n  ".join(items)]
        sql.append('FROM "%s" AS "zAsset"' % self.base)
        for j in self.joins_kept:
            sql.append('LEFT JOIN "%s" AS "%s" ON %s'
                       % (self.aliases[j["alias"]]["table"], j["alias"],
                          self.substitute(j["on"])))
        if self.where:
            sql.append("WHERE " + self.where)
        for cand in self.cat["order_by"]:
            a, c = cand.split(".")
            info = self.aliases.get(a)
            if info and self.schema.has_column(info["table"], c):
                sql.append("ORDER BY " + self.substitute(cand))
                break
        if self.limit:
            sql.append("LIMIT %d" % int(self.limit))
        return "\n".join(sql)

    # -- safety net --------------------------------------------------------

    def prepare(self, sql):
        """EXPLAIN-compile; repair on no-such-column/table and retry."""
        for _ in range(len(self.columns) + 5):
            try:
                self.conn.execute("EXPLAIN " + sql)
                return sql
            except sqlite3.OperationalError as ex:
                m = re.match(r"no such column: (\S+)", str(ex))
                t = re.match(r"no such table: (\S+)", str(ex))
                if m and self._drop_ref(m.group(1)):
                    sql = self.build_sql()
                    continue
                if t and self._drop_join(t.group(1)):
                    sql = self.build_sql()
                    continue
                return self._per_column_probe()
            except sqlite3.Error:
                return self._per_column_probe()
        return self._per_column_probe()

    def _drop_ref(self, ref):
        parts = ref.strip('"').split(".")
        alias_l = parts[0].lower() if len(parts) == 2 else None
        col_l = parts[-1].lower()
        hit = False
        for col in list(self.columns):
            refs_l = [(a.lower(), c.lower()) for a, c in col["refs"]]
            if any((alias_l is None or a == alias_l) and c == col_l
                   for a, c in refs_l):
                self.columns.remove(col)
                self.dropped_columns.append(
                    (col["name"], "missing at prepare time (%s)" % ref))
                hit = True
        return hit

    def _drop_join(self, name):
        alias = name.split(".")[0].strip('"').lower()
        for j in list(self.joins_kept):
            if j["alias"].lower() == alias:
                self.joins_kept.remove(j)
                self.joins_dropped.append(
                    (j["alias"], "missing at prepare time"))
                self.aliases.pop(j["alias"], None)
                for col in list(self.columns):
                    if self._column_problem(col) is not None:
                        self.columns.remove(col)
                        self.dropped_columns.append(
                            (col["name"], "join lost at prepare time"))
                return True
        return False

    def _per_column_probe(self):
        """Last resort: compile each select item alone; keep what compiles."""
        kept = []
        for col in self.columns:
            probe = ('EXPLAIN SELECT %s AS x FROM "%s" AS "zAsset" LIMIT 0'
                     % (self.substitute(col["expr"]), self.base))
            try:
                self.conn.execute(probe)
                kept.append(col)
            except sqlite3.Error:
                self.dropped_columns.append(
                    (col["name"], "failed per-column probe"))
        self.columns = kept
        return self.build_sql()


# ---------------------------------------------------------------------------
# Export driver
# ---------------------------------------------------------------------------

def open_readonly(path, force_immutable=False):
    """Open without writing.  force_immutable pins the pre-checkpoint
    snapshot (WAL invisible) - used as pass 1 of the differential export;
    the default chain prefers mode=ro and only warns on the immutable
    fallback."""
    p = Path(path).resolve()
    suffixes = ("?mode=ro&immutable=1",) if force_immutable else \
        ("?mode=ro", "?mode=ro&immutable=1")
    for suffix in suffixes:
        try:
            conn = sqlite3.connect(p.as_uri() + suffix, uri=True)
            conn.execute("SELECT count(*) FROM sqlite_master")
            if suffix == "?mode=ro&immutable=1" and not force_immutable:
                sys.stderr.write("note: opened immutable; uncheckpointed WAL "
                                 "content, if any, is not visible\n")
            return conn
        except sqlite3.Error:
            continue
    return None


def blob_to_text(v):
    if isinstance(v, bytes):
        return "0x" + v.hex()
    return v


def write_csv(conn, sql, path):
    cur = conn.execute(sql)
    header = [d[0] for d in cur.description]
    n = 0
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        while True:
            rows = cur.fetchmany(500)
            if not rows:
                break
            for row in rows:
                w.writerow([blob_to_text(v) for v in row])
                n += 1
    return len(header), n


# ---------------------------------------------------------------------------
# WAL replay differential export
# ---------------------------------------------------------------------------

WAL_STATUS_COL = "wal-diff-status"
WAL_FIRST_COL = "wal-first-commit"
WAL_LAST_COL = "wal-last-commit"
WAL_MAGICS = (0x377F0682, 0x377F0683)


def wal_size(path):
    """Bytes in the <db>-wal sidecar, 0 when absent."""
    try:
        return os.path.getsize(str(path) + "-wal")
    except OSError:
        return 0


def wal_commits(path):
    """Committed-transaction boundaries of a -wal file.

    Returns (page_size, offsets, live_frames, dead_frames): offsets[i] is
    the wal byte length that yields the database state right after
    committed transaction i+1 - truncating a copy of db+wal there leaves
    exactly what a crash at that point would, and SQLite recovers it on
    open.  Frame layout follows the SQLite file format (32-byte header
    with the salt generation, 24-byte frame headers; a frame with
    db_size_after_commit != 0 ends a transaction): frames whose salts stop
    matching the header are leftovers from an earlier checkpoint
    generation and everything from there on is dead, just like SQLite
    itself treats them.  Raises ValueError on a header we cannot parse.
    """
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        hdr = fh.read(32)
        if len(hdr) < 32:
            raise ValueError("wal sidecar shorter than a header")
        magic, _ver, page = struct.unpack(">III", hdr[:12])
        if magic not in WAL_MAGICS:
            raise ValueError("not a wal header (magic 0x%08x)" % magic)
        if page < 512 or page > 65536 or page & (page - 1):
            raise ValueError("wal page size %d is not a power of two" % page)
        salt1, salt2 = struct.unpack(">II", hdr[16:24])
        offsets, live = [], 0
        pos, stride = 32, 24 + page
        while pos + stride <= size:
            fh.seek(pos)
            pgno, dbsize, fs1, fs2 = struct.unpack(">IIII", fh.read(16))
            if (fs1, fs2) != (salt1, salt2) or pgno == 0:
                break                          # dead generation / garbage
            live += 1
            pos += stride
            if dbsize:                         # commit frame
                offsets.append(pos)
        dead = (size - pos) // stride
    return page, offsets, live, dead


def open_wal_prefix(workdir, db_name, orig_db, orig_wal, offset, tag):
    """Open one replay state in its OWN subdirectory of the work dir.

    Copies the db plus the wal truncated to a commit boundary - exactly
    the state a crash at that point would leave.  Every state gets fresh
    files because a state sharing files with a still-open connection from
    another state (or trusting its stale -shm) corrupts the wal-index and
    fails with disk I/O errors.  mode=ro only, never the immutable
    fallback: immutable would silently hide the truncated wal and show
    the snapshot - the wrong state.  Returns (conn, state_dir) or
    (None, None) when the state will not open.
    """
    sdir = Path(workdir) / ("state_%s" % tag)
    shutil.rmtree(sdir, ignore_errors=True)
    sdir.mkdir(parents=True)
    db_copy = sdir / db_name
    wal_copy = sdir / (db_name + "-wal")
    shutil.copyfile(orig_db, db_copy)
    shutil.copyfile(orig_wal, wal_copy)
    with open(wal_copy, "r+b") as fh:
        fh.truncate(offset)
    try:
        conn = sqlite3.connect(db_copy.resolve().as_uri() + "?mode=ro",
                               uri=True)
        conn.execute("SELECT count(*) FROM sqlite_master")
        return conn, sdir
    except sqlite3.Error:
        return None, sdir


def _key_index(header):
    for i, h in enumerate(header):
        if h.lower() == "zasset-zpk":
            return i
    return None


def _proj(rows, idxs):
    """Rows projected onto the given column indices, as hashable tuples."""
    return [tuple(r[i] for i in idxs) for r in rows]


class ReplayFold(object):
    """Fold one output CSV's query results across WAL replay states.

    feed() is called once per state (0 = pre-WAL snapshot, 1..K = WAL
    commit prefixes, in order); write() merges everything.  Classification
    per asset key: present in the final state -> unchanged / added /
    modified (versus state 0, comparing per-key row multisets on the
    columns both states share); absent from the final state but seen in
    any state -> removed, keeping the rows of the LAST state that saw the
    asset.  For a create-and-delete-inside-the-WAL case those rows carry
    the values as of the deletion commit - e.g. already marked as trashed.
    """

    def __init__(self):
        self.snap = None            # (header, {key: rows}) state 0
        self.final = None           # (header, {key: rows}) state K
        self.final_state = 0
        self.headers = []           # [(state, header)] in feed order
        self.first_seen = {}        # key -> state
        self.last_seen = {}         # key -> (state, header, rows)

    def feed(self, state, header, rows):
        if state == 0:
            self.snap = (header, rows)
        self.final = (header, rows)
        self.final_state = state
        self.headers.append((state, header))
        for key in rows:
            self.first_seen.setdefault(key, state)
            self.last_seen[key] = (state, header, rows[key])

    def write(self, path):
        hdr_f, rows_f = self.final
        hdr_s, rows_s = self.snap
        # union of columns: final order first, earlier states newest-first
        header = list(hdr_f)
        for _state, hdr in reversed(self.headers[:-1]):
            for h in hdr:
                if h not in header:
                    header.append(h)
        out_f = [hdr_f.index(h) if h in hdr_f else None for h in header]
        common_s = [i for i, h in enumerate(hdr_s) if h in hdr_f]
        common_f = [hdr_f.index(hdr_s[i]) for i in common_s]

        counts = dict.fromkeys(("unchanged", "added", "removed", "modified"), 0)
        n = 0
        with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header + [WAL_STATUS_COL, WAL_FIRST_COL, WAL_LAST_COL])

            def emit(vals, idxs, status, first, last):
                w.writerow([vals[i] if i is not None else "" for i in idxs]
                           + [status, first, last])

            for key, rws in rows_f.items():      # full-state order
                if key not in rows_s:
                    status = "added"
                elif (sorted(_proj(rows_s[key], common_s), key=repr)
                      == sorted(_proj(rws, common_f), key=repr)):
                    status = "unchanged"
                else:
                    status = "modified"
                counts[status] += 1
                for r in rws:
                    emit(r, out_f, status, self.first_seen.get(key, 0),
                         self.final_state)
                    n += 1
            for key, (state, hdr_l, rws) in self.last_seen.items():
                if key in rows_f:
                    continue
                out_l = [hdr_l.index(h) if h in hdr_l else None for h in header]
                counts["removed"] += 1
                for r in rws:
                    emit(r, out_l, "removed", self.first_seen.get(key, 0),
                         state)
                    n += 1
        return len(header) + 3, n, counts


def pick_filter_where(builder, filt):
    """First alternate whose column references all resolve, else None."""
    for where in filt["where"]:
        ok = True
        for a, c in REF_RE.findall(where):
            info = builder.aliases.get(a)
            if not info:
                ok = False
                break
            if c not in info["ph"] and \
                    not builder.schema.has_column(info["table"], c):
                ok = False
                break
        if ok:
            if len(filt["where"]) > 1:
                builder.report.add("filter %s: using %s" % (filt["name"], where))
            return where
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Export any iOS Photos.sqlite to CSV, degrading "
                    "gracefully on unknown schemas.")
    ap.add_argument("database")
    ap.add_argument("-o", "--outdir", default=None)
    ap.add_argument("--profile", default="basic")
    ap.add_argument("--filter", action="append", nargs="+", default=[],
                    metavar="NAME",
                    help="also write one CSV per filter preset: hidden trashed "
                         "favorite locations adjusted syndication "
                         "(repeat the flag or list several names)")
    ap.add_argument("--all-filters", action="store_true")
    ap.add_argument("--where", default=None, metavar="SQL",
                    help="extra CSV with this custom WHERE clause")
    ap.add_argument("--keep-missing", action="store_true",
                    help="keep absent columns in the CSV as NULL")
    ap.add_argument("--no-wal-diff", action="store_true",
                    help="with a non-empty -wal sidecar, skip the "
                         "differential two-pass export and do a plain "
                         "single-pass export")
    ap.add_argument("--keep-wal-work", action="store_true",
                    help="keep the _wal_work directory holding the "
                         "replay copies used by the differential export")
    ap.add_argument("--wal-replay-limit", type=int, default=2000,
                    metavar="N",
                    help="replay at most N WAL commits (safety cap for huge "
                         "sidecars; history beyond the cap needs a carver "
                         "such as sqlite4n6)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--catalog", default=DEFAULT_CATALOG)
    ap.add_argument("--dump-sql", action="store_true",
                    help="print each final SQL statement to stderr")
    ap.add_argument("--list", action="store_true",
                    help="print catalog summary and exit")
    args = ap.parse_args(argv)

    with io.open(args.catalog, encoding="utf-8") as fh:
        cat = json.load(fh)

    if args.profile not in cat["profiles"]:
        ap.error("unknown profile %r (catalog has: %s)"
                 % (args.profile, ", ".join(sorted(cat["profiles"]))))
    if args.list:
        print("profiles: %s" % ", ".join(sorted(cat["profiles"])))
        print("filters:  %s" % ", ".join(f["name"] for f in cat["filters"]))
        print("columns:  %d" % len(cat["columns"]))
        print("joins:    %d" % len(cat["joins"]))
        return 0

    db = args.database
    if not os.path.exists(db):
        sys.stderr.write("file not found: %s\n" % db)
        return 2

    outdir = args.outdir or os.path.join(
        os.path.dirname(os.path.abspath(db)), "photos_export")
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(db))[0]

    # -- WAL differential setup (before anything else touches the db) -------
    exit_code = 0
    wsize = wal_size(db)
    use_wal_diff = wsize > 0 and not args.no_wal_diff
    wal = None                      # bookkeeping for the report + cleanup
    conn = conn1 = builder1 = None  # conn1/builder1 = state 0 (snapshot)
    if use_wal_diff:
        print("wal sidecar detected (%d bytes): differential export "
              "(--no-wal-diff to disable)" % wsize)
        workdir = os.path.join(outdir, "_wal_work")
        try:
            page, offsets, live, dead = wal_commits(str(db) + "-wal")
            if not offsets:
                raise ValueError("wal sidecar has no committed transactions")
            limit_note = ""
            if args.wal_replay_limit and \
                    len(offsets) > args.wal_replay_limit:
                limit_note = ("replay truncated at %d of %d commits "
                              "(--wal-replay-limit); deeper history needs a "
                              "carver such as sqlite4n6"
                              % (args.wal_replay_limit, len(offsets)))
                offsets = offsets[:args.wal_replay_limit]
            workdir_p = Path(workdir)
            workdir_p.mkdir(parents=True, exist_ok=True)
            conn1 = open_readonly(db, force_immutable=True)
            conn, _fdir = open_wal_prefix(workdir, Path(db).name, db,
                                          str(db) + "-wal", offsets[-1],
                                          "final")
            if conn1 is None or conn is None:
                raise sqlite3.Error("cannot open snapshot or replayed copy")
            wal = {"workdir": workdir, "size": wsize, "page": page,
                   "commits": len(offsets), "live": live, "dead": dead,
                   "limit_note": limit_note, "offsets": offsets}
        except (OSError, ValueError, sqlite3.Error) as ex:
            sys.stderr.write("wal diff unavailable (%s); falling back to "
                             "single-pass export\n" % ex)
            exit_code = 1
            for c in (conn, conn1):
                if c is not None:
                    c.close()
            conn = conn1 = None
            use_wal_diff = False
            if not args.keep_wal_work:
                shutil.rmtree(workdir, ignore_errors=True)
    if conn is None:
        conn = open_readonly(db)
    if conn is None:
        sys.stderr.write("cannot open as SQLite (or not a database): %s\n" % db)
        if conn1 is not None:
            conn1.close()
        return 2
    schema = Schema(conn)

    builder = QueryBuilder(cat, conn, schema, args.profile,
                           keep_missing=args.keep_missing)
    builder.resolve_joins()
    if builder.base is None:
        sys.stderr.write("no ZASSET/ZGENERICASSET table - not a Photos "
                         "database: %s\n" % db)
        conn.close()
        if conn1 is not None:
            conn1.close()
        return 2
    builder.resolve_columns()

    if use_wal_diff:
        schema1 = Schema(conn1)
        builder1 = QueryBuilder(cat, conn1, schema1, args.profile,
                                keep_missing=args.keep_missing)
        builder1.resolve_joins()
        if builder1.base is None:
            builder.report.add(
                "wal diff off: pre-WAL snapshot has no asset table; "
                "exported the full state single-pass")
            sys.stderr.write("wal diff off: snapshot has no asset table\n")
            exit_code = 1
            conn1.close()
            conn1 = builder1 = None
            use_wal_diff = False
        else:
            builder1.resolve_columns()
            only1 = [c["name"] for c in builder1.columns
                     + builder1.null_columns
                     if c["name"] not in
                     {c["name"] for c in builder.columns + builder.null_columns}]
            if only1:
                builder.report.add(
                    "wal: columns only in earlier states (appended): %s"
                    % ", ".join(only1))
            builder.report.add(
                "wal: %d-byte sidecar, page %d: %d live frames, %d commits,"
                " %d dead frames" % (wsize, wal["page"], wal["live"],
                                     wal["commits"], wal["dead"]))
            builder.report.add(
                "wal: replayed states 0 (snapshot) .. %d (final); the "
                "wal-first/last-commit columns give provenance (0 = snapshot)"
                % wal["commits"])
            if wal["limit_note"]:
                builder.report.add("wal: " + wal["limit_note"])
                sys.stderr.write("wal: " + wal["limit_note"] + "\n")

    filters = []
    for group in args.filter:              # nargs="+" yields a list per flag
        for name in group:
            if name not in filters:
                filters.append(name)
    if args.all_filters:
        filters = [f["name"] for f in cat["filters"]]
    for name in filters:
        if not any(f["name"] == name for f in cat["filters"]):
            sys.stderr.write("unknown filter: %s (catalog has: %s)\n" % (
                name, ", ".join(f["name"] for f in cat["filters"])))
            conn.close()
            return 1

    jobs = [("%s_%s.csv" % (stem, args.profile), None)]
    for name in filters:
        filt = next(f for f in cat["filters"] if f["name"] == name)
        jobs.append(("%s_%s_%s.csv" % (stem, args.profile, name), filt))
    if args.where:
        jobs.append(("%s_%s_custom.csv" % (stem, args.profile),
                     {"name": "custom", "where": [args.where]}))

    def report_job(fname, ncols, nrows, counts):
        builder.report.add(
            "wrote %s: %d columns x %d rows (wal diff: %d unchanged, %d "
            "added, %d removed, %d modified)"
            % (fname, ncols, nrows, counts["unchanged"], counts["added"],
               counts["removed"], counts["modified"]))
        print("%s: %d columns x %d rows (wal: %d unchanged, %d added, %d "
              "removed, %d modified)"
              % (fname, ncols, nrows, counts["unchanged"], counts["added"],
                 counts["removed"], counts["modified"]))

    if use_wal_diff:
        # -- replay every state (0 = snapshot, 1..K = WAL commits) ----------
        n_states = wal["commits"] + 1
        folds = {fname: ReplayFold() for fname, _ in jobs}
        dead_jobs = set()          # skipped entirely (red line 4)
        mid_notes = set()
        cur = None                 # open state connection (middle states)
        try:
            for state in range(n_states):
                cur_sdir = None
                if state == 0:
                    sconn, sb = conn1, builder1
                elif state == n_states - 1:
                    sconn, sb = conn, builder
                else:
                    sconn, cur_sdir = open_wal_prefix(
                        wal["workdir"], Path(db).name, db, str(db) + "-wal",
                        wal["offsets"][state - 1], state)
                    if sconn is None:
                        raise sqlite3.Error(
                            "cannot open replay state %d" % state)
                    cur = sconn
                    sb = QueryBuilder(cat, sconn, Schema(sconn), args.profile,
                                      keep_missing=args.keep_missing)
                    sb.resolve_joins()
                    sb.resolve_columns()
                for fname, filt in jobs:
                    if fname in dead_jobs:
                        continue
                    sb.where = None
                    if filt is not None:
                        sb.where = pick_filter_where(sb, filt)
                        if sb.where is None:
                            where = "snapshot" if state == 0 else "final state"
                            if state in (0, n_states - 1):
                                builder.report.add(
                                    "SKIPPED %s: filter %s has no usable "
                                    "condition on the %s"
                                    % (fname, filt["name"], where))
                                sys.stderr.write("skipped %s (filter not "
                                                 "applicable on the %s)\n"
                                                 % (fname, where))
                                exit_code = 1
                                dead_jobs.add(fname)
                            elif fname not in mid_notes:
                                mid_notes.add(fname)
                                builder.report.add(
                                    "wal: filter %s unresolvable in some "
                                    "middle states; those states are not "
                                    "observed for %s" % (filt["name"], fname))
                            continue
                    sb.limit = args.limit
                    sql = sb.prepare(sb.build_sql())
                    if args.dump_sql and state in (0, n_states - 1):
                        sys.stderr.write(
                            "=== %s (state %d: %s) ===\n%s\n\n"
                            % (fname, state,
                               "snapshot" if state == 0 else "final", sql))
                    try:
                        cur = sconn.execute(sql)
                        header = [d[0] for d in cur.description]
                        k = _key_index(header)
                        if k is None:
                            raise ValueError("no zAsset-zPK column")
                        rows = {}
                        for row in cur.fetchall():
                            nrow = [blob_to_text(v) for v in row]
                            rows.setdefault(nrow[k], []).append(nrow)
                        folds[fname].feed(state, header, rows)
                    except (sqlite3.Error, ValueError) as ex:
                        builder.report.add(
                            "FAILED %s (replay state %d): %s"
                            % (fname, state, ex))
                        sys.stderr.write("failed %s (state %d): %s\n"
                                         % (fname, state, ex))
                        exit_code = 1
                        dead_jobs.add(fname)
                if cur is not None:
                    # close + drop this state's copy before the next one
                    # (Windows refuses to delete open files anyway)
                    cur.close()
                    cur = None
                    if not args.keep_wal_work and cur_sdir is not None:
                        shutil.rmtree(cur_sdir, ignore_errors=True)
        except (OSError, sqlite3.Error) as ex:
            sys.stderr.write("wal replay aborted (%s); falling back to "
                             "single-pass export\n" % ex)
            builder.report.add("wal replay aborted: %s" % ex)
            exit_code = 1
            use_wal_diff = False
        finally:
            if cur is not None:
                cur.close()
        if use_wal_diff:
            for fname, _filt in jobs:
                if fname in dead_jobs:
                    continue
                try:
                    ncols, nrows, counts = folds[fname].write(
                        os.path.join(outdir, fname))
                except (OSError, ValueError) as ex:
                    builder.report.add("FAILED %s: %s" % (fname, ex))
                    sys.stderr.write("failed %s: %s\n" % (fname, ex))
                    exit_code = 1
                    continue
                report_job(fname, ncols, nrows, counts)

    if not use_wal_diff:
        for fname, filt in jobs:
            builder.where = None
            if filt is not None:
                builder.where = pick_filter_where(builder, filt)
                if builder.where is None:
                    builder.report.add(
                        "SKIPPED %s: filter %s has no usable condition in this "
                        "database" % (fname, filt["name"]))
                    sys.stderr.write("skipped %s (filter not applicable)\n" % fname)
                    exit_code = 1
                    continue
            builder.limit = args.limit
            sql = builder.prepare(builder.build_sql())
            if args.dump_sql:
                sys.stderr.write("=== %s ===\n%s\n\n" % (fname, sql))
            try:
                ncols, nrows = write_csv(conn, sql, os.path.join(outdir, fname))
            except (sqlite3.Error, ValueError) as ex:
                builder.report.add("FAILED %s: %s" % (fname, ex))
                sys.stderr.write("failed %s: %s\n" % (fname, ex))
                exit_code = 1
                continue
            builder.report.add("wrote %s: %d columns x %d rows"
                               % (fname, ncols, nrows))
            print("%s: %d columns x %d rows" % (fname, ncols, nrows))

    report_path = os.path.join(outdir, "export_report.txt")
    conn.close()
    if conn1 is not None:
        conn1.close()
    if wal is not None:
        # after conn.close(): Windows refuses to delete files an open
        # sqlite connection still holds
        if args.keep_wal_work:
            builder.report.add("wal: work copy kept at %s" % wal["workdir"])
        else:
            shutil.rmtree(wal["workdir"], ignore_errors=True)
            builder.report.add("wal: work copy removed (%s)" % wal["workdir"])
    builder.report.dump(report_path)
    print("report: %s" % report_path)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
