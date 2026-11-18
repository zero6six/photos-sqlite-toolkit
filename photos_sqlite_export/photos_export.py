#!/usr/bin/env python3
"""photos_export.py - export any iOS Photos.sqlite to CSV.

Works from a merged query catalog (catalog.json, built from the archived
iOS 11-17 query repo and the iLEAPP Ph001/Ph002 artifacts covering iOS 11-26).
Every table and column reference is checked against the actual database before
the query runs: missing tables drop their JOIN, missing columns drop their
output column (or become NULL with --keep-missing).  A prepare-time retry loop
catches anything the schema check missed.  The goal is always to produce a
CSV, never to fail on a schema the catalog does not know.

Usage:
    python photos_export.py <Photos.sqlite> [-o OUTDIR] [--profile basic]
        [--filter hidden trashed ...] [--all-filters] [--where "SQL"]
        [--keep-missing] [--limit N] [--dump-sql] [--list] [--catalog PATH]
        [--version]

Exit codes: 0 every requested CSV was written; 1 some outputs were skipped;
2 the file is not a usable Photos database.
"""

import argparse
import csv
import io
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

__version__ = "0.1.0"

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

def open_readonly(path):
    p = Path(path).resolve()
    for suffix in ("?mode=ro", "?mode=ro&immutable=1"):
        try:
            conn = sqlite3.connect(p.as_uri() + suffix, uri=True)
            conn.execute("SELECT count(*) FROM sqlite_master")
            if suffix == "?mode=ro&immutable=1":
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
    ap.add_argument("--version", action="version",
                    version="%(prog)s " + __version__)
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
    conn = open_readonly(db)
    if conn is None:
        sys.stderr.write("cannot open as SQLite (or not a database): %s\n" % db)
        return 2
    schema = Schema(conn)

    builder = QueryBuilder(cat, conn, schema, args.profile,
                           keep_missing=args.keep_missing)
    builder.resolve_joins()
    if builder.base is None:
        sys.stderr.write("no ZASSET/ZGENERICASSET table - not a Photos "
                         "database: %s\n" % db)
        conn.close()
        return 2
    builder.resolve_columns()

    outdir = args.outdir or os.path.join(
        os.path.dirname(os.path.abspath(db)), "photos_export")
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(db))[0]

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

    exit_code = 0
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
        except sqlite3.Error as ex:
            builder.report.add("FAILED %s: %s" % (fname, ex))
            sys.stderr.write("failed %s: %s\n" % (fname, ex))
            exit_code = 1
            continue
        builder.report.add("wrote %s: %d columns x %d rows"
                           % (fname, ncols, nrows))
        print("%s: %d columns x %d rows" % (fname, ncols, nrows))

    report_path = os.path.join(outdir, "export_report.txt")
    builder.report.dump(report_path)
    print("report: %s" % report_path)
    conn.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
