#!/usr/bin/env python3
"""Build catalog.json from the two query sources.

Sources (both read as data only, never imported):
  1. The archived repo "iOS_Local_PL_Photos.sqlite_Queries" - Basic and
     Very-Basic query files for iOS 11-17.
  2. The local iLEAPP source tree - the Ph001/Ph002 artifacts, which carry the
     same queries maintained by the same author up to iOS 26.

The catalog is a merged, canonicalized list of output columns plus the join
definitions needed to evaluate them.  Version-specific Core Data join tables
and columns (Z_28ASSETS.Z_28ALBUMS, ...) are replaced by placeholders that the
export tool resolves against the actual database at run time.

Usage:
    python tools/build_catalog.py --repo <repo-dir> --ileapp <ileapp-dir>
                                  [--out catalog.json]
"""

import argparse
import collections
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

try:  # keep Windows consoles from choking on non-cp1252 characters
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------------------
# SQL text utilities
# ---------------------------------------------------------------------------

ALIAS_RE = re.compile(r"\s+AS\s+'((?:[^']|'')*)'\s*$", re.S | re.I)
NUM_ASSET_ALIAS = re.compile(r"\bz\d+Assets\b")
NUM_LIST_ALIAS = re.compile(r"\bz\d+AlbumLists\b")
REF_RE = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*|\{\{[A-Z_]+\}\})")


def read_text(path):
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read().replace("\r\n", "\n").replace("\r", "\n")


def split_top(sql):
    """Split a SELECT list on commas that are outside quotes and parens."""
    items, buf, depth, q = [], [], 0, None
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if q:
            buf.append(c)
            if c == q:
                q = None
        elif c in "'\"":
            q = c
            buf.append(c)
        elif c == "(":
            depth += 1
            buf.append(c)
        elif c == ")":
            depth -= 1
            buf.append(c)
        elif c == "," and depth == 0:
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    return items


def parse_query(sql):
    """Parse one SELECT statement into (select_items, base, joins, order_by).

    select_items: list of (expression, header) with the AS 'header' stripped.
    base:         (table, alias) from the FROM clause.
    joins:        list of (table, alias, on_condition).
    order_by:     text after ORDER BY, or None.
    """
    m = re.search(r"^[ \t]*FROM\s", sql, re.M)
    if not sql.lstrip().upper().startswith("SELECT") or not m:
        raise ValueError("not a plain SELECT statement")
    sel = sql[sql.upper().index("SELECT") + 6:m.start()]
    tail = sql[m.start():]

    base = None
    joins = []
    order_by = None
    clause = []
    clauses = []
    for line in tail.split("\n"):
        if re.match(r"^\s*((LEFT\s+)?JOIN|WHERE|ORDER\s+BY|GROUP\s+BY|HAVING|LIMIT)\b",
                    line, re.I):
            clauses.append(clause)
            clause = [line]
        else:
            clause.append(line)
    clauses.append(clause)
    for chunk in clauses:
        text = " ".join(" ".join(chunk).split())
        jm = re.match(r"FROM\s+(\S+)\s+(\w+)\s*$", text, re.I)
        km = re.match(r"(?:LEFT\s+)?JOIN\s+(\S+)\s+(\w+)\s+ON\s+(.+)$", text, re.I)
        om = re.match(r"ORDER\s+BY\s+(.+)$", text, re.I)
        if jm and base is None:
            base = (jm.group(1), jm.group(2))
        elif km:
            joins.append((km.group(1), km.group(2), " ".join(km.group(3).split())))
        elif om:
            order_by = om.group(1)
        elif text:
            raise ValueError("unparsed FROM-clause line: %r" % text)

    items = []
    for it in split_top(sel):
        am = ALIAS_RE.search(it)
        if not am:
            raise ValueError("select item without AS 'header': %r" % it[:80])
        expr = it[:am.start()].strip()
        header = am.group(1).replace("''", "'")
        items.append((expr, header))
    return items, base, joins, order_by


# ---------------------------------------------------------------------------
# Canonicalization: numbered Core Data join tables -> placeholders
# ---------------------------------------------------------------------------

AA_TABLE_RE = re.compile(r"^Z_\d+ASSETS$")
AL_TABLE_RE = re.compile(r"^Z_\d+ALBUMLISTS$")


def canonicalize_sql(text):
    """Rewrite version-specific aliases/columns in an expression or ON clause."""
    text = NUM_ASSET_ALIAS.sub("zAssetAlbums", text)
    text = NUM_LIST_ALIAS.sub("zAlbumLists", text)
    text = re.sub(r"\bzAssetAlbums\.Z_\d+ASSETS\b",
                  "zAssetAlbums.{{AA_ASSET_FK}}", text)
    text = re.sub(r"\bzAssetAlbums\.Z_\d+ALBUMS\b",
                  "zAssetAlbums.{{AA_ALBUM_FK}}", text)
    text = re.sub(r"\bzAlbumLists\.Z_\d+ALBUMS\b",
                  "zAlbumLists.{{AL_ALBUM_FK}}", text)
    text = re.sub(r"\bzAlbumLists\.Z_\d+ALBUMLISTS\b",
                  "zAlbumLists.{{AL_LIST_FK}}", text)
    return text


def canonicalize_header(header):
    header = NUM_ASSET_ALIAS.sub("zAssetAlbums", header)
    header = NUM_LIST_ALIAS.sub("zAlbumLists", header)
    header = re.sub(r"Z_\d+(ASSETS|ALBUMS|ALBUMLISTS)\b", r"Z_\1", header)
    return header


def canonical_join(table, alias, on, amap):
    """Return a canonical join dict for one parsed JOIN clause."""
    alias = amap.get(alias, alias)
    on_c = rewrite_with_map(canonicalize_sql(on), amap)
    if AA_TABLE_RE.match(table):
        return dict(alias="zAssetAlbums", tables=None, resolve="asset_album_join",
                    on=on_c)
    if AL_TABLE_RE.match(table):
        return dict(alias="zAlbumLists", tables=None, resolve="album_list_join",
                    on=on_c)
    if table in ("ZSHARE", "ZMOMENTSHARE"):
        return dict(alias=alias, tables=["ZSHARE", "ZMOMENTSHARE"], resolve=None,
                    on=on_c)
    return dict(alias=alias, tables=[table], resolve=None, on=on_c)


# Aliases meaning one join in some queries and a different join in others
# (zCldMastMedData) are canonicalized per query from their ON condition, never
# by name alone.
def alias_map_for_query(joins):
    amap = {}
    for table, alias, on in joins:
        if AA_TABLE_RE.match(table):
            amap[alias] = "zAssetAlbums"
        elif AL_TABLE_RE.match(table):
            amap[alias] = "zAlbumLists"
        elif table == "ZCLOUDMASTERMEDIAMETADATA":
            amap[alias] = ("AAAzCldMastMedData"
                           if "zAddAssetAttr.ZMEDIAMETADATA" in on.replace(" ", "")
                           else "CMzCldMastMedData")
    return amap


def rewrite_with_map(text, amap):
    def repl(m):
        return "%s.%s" % (amap.get(m.group(1), m.group(1)), m.group(2))
    return REF_RE.sub(repl, text)


def shape_of(expr):
    e = expr.lstrip()
    if e.upper().startswith("CASE"):
        return "case"
    if re.match(r"(?i)DateTime\s*\(", e):
        return "datetime"
    if re.match(r"^\w+\.\w+$", e):
        return "col"
    return "func"


def refs_of(expr):
    return sorted(set((a, c) for a, c in REF_RE.findall(expr)))


# ---------------------------------------------------------------------------
# Source readers
# ---------------------------------------------------------------------------

class Item(object):
    __slots__ = ("expr", "header", "shape", "refs", "source", "version")

    def __init__(self, expr, header, source, version, amap):
        self.expr = rewrite_with_map(canonicalize_sql(expr), amap)
        self.header = canonicalize_header(header)
        self.shape = shape_of(self.expr)
        self.refs = refs_of(self.expr)
        self.source = source
        self.version = version


def read_repo(repo_dir):
    """Yield (source, version, sql) from the archived repo's Basic/Very-Basic."""
    out = []
    for ver in range(11, 18):
        for stem in ("Basic", "Very-Basic"):
            name = "iOS%d_LPL_Phsql_%s.txt" % (ver, stem)
            path = os.path.join(repo_dir, "iOS%d" % ver, "Previous_Queries", name)
            if os.path.exists(path):
                out.append(("repo-" + stem, "%d" % ver, read_text(path)))
    return out


BRANCH_SPLIT = re.compile(
    r"\n    (?:el)?if \(version\.parse\(iosversion\) >= version\.parse\("
    r'"([\d.]+)"\)\) & \(version\.parse\(iosversion\) < version\.parse\('
    r'"([\d.]+)"\)\):')


def read_ileapp(ileapp_dir):
    """Yield (source, version, sql) from Ph001/Ph002 PhotoData artifacts."""
    specs = [
        ("Ph001BasicAssetData.py", "Ph001_1AssetBasicDataPhDaPsql", "ileapp-Ph001"),
        ("Ph002BasicAssetandAlbumData.py", "Ph002_1AssetBasicGenAlbumDataPhDaPsql",
         "ileapp-Ph002"),
    ]
    out = []
    for fname, func, source in specs:
        src = read_text(os.path.join(ileapp_dir, "scripts", "artifacts", fname))
        m = re.search(r"\ndef %s\(context\):.*?(?=\ndef |\Z)" % func, src, re.S)
        if not m:
            raise ValueError("function %s not found in %s" % (func, fname))
        body = m.group(0)
        parts = BRANCH_SPLIT.split(body)
        for i in range(1, len(parts), 3):
            lo, hi, chunk = parts[i], parts[i + 1], parts[i + 2]
            for q in re.findall(r"query = '''(.*?)'''", chunk, re.S):
                out.append((source, "%s-%s" % (lo, hi), q))
    return out


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge(entries):
    columns = {}          # key -> column dict
    order = []
    stats = collections.Counter()
    all_joins = {}        # (alias, on, resolve) -> canonical join dict

    def join_key(j):
        return (j["alias"], j["on"], j["resolve"])

    parsed = []
    for source, version, sql in entries:
        try:
            items, base, joins, _ = parse_query(sql)
        except ValueError:
            stats["unparsed_query"] += 1
            continue
        if not base or base[1] != "zAsset":
            stats["skipped_non_zasset"] += 1
            continue
        amap = alias_map_for_query(joins)
        parsed.append((source, version, items, joins, amap))
        for table, alias, on in joins:
            j = canonical_join(table, alias, on, amap)
            all_joins.setdefault(join_key(j), j)

    for source, version, items, joins, amap in parsed:
        for expr, header in items:
            it = Item(expr, header, source, version, amap)
            if it.shape == "func":
                key = ("func", " ".join(it.expr.split()), tuple(it.refs))
            else:
                key = (it.shape, tuple(sorted(it.refs)))
            if key in columns:
                col = columns[key]
                col["expr"] = it.expr
                col["name"] = it.header
                col["newest_source"] = it.source
                col["newest_version"] = it.version
                stats["expr_replaced"] += 1
                if it.source not in col["sources"]:
                    col["sources"].append(it.source)
                if it.version not in col["versions"]:
                    col["versions"].append(it.version)
            else:
                columns[key] = dict(
                    name=it.header, expr=it.expr, refs=it.refs,
                    shape=it.shape, sources=[it.source], versions=[it.version],
                    first_source=it.source, first_version=it.version,
                    newest_source=it.source, newest_version=it.version)
                order.append(key)
                stats["first_seen_" + it.source] += 1

    # De-duplicate headers (keep uniqueness in the CSV).
    seen = collections.Counter()
    for key in order:
        col = columns[key]
        seen[col["name"]] += 1
        if seen[col["name"]] > 1:
            col["name"] = "%s (%d)" % (col["name"], seen[col["name"]])

    cols_out = []
    for key in order:
        col = columns[key]
        refs = sorted(set(tuple(r) for r in col["refs"]))
        needed = sorted({a for a, _ in refs})
        cols_out.append(dict(
            name=col["name"], expr=col["expr"], refs=[list(r) for r in refs],
            joins=needed, shape=col["shape"],
            sources=col["sources"], versions=col["versions"],
            first_source=col["first_source"], newest_source=col["newest_source"],
            first_version=col["first_version"], newest_version=col["newest_version"]))
    joins_out = sorted(all_joins.values(),
                       key=lambda j: j["alias"].lower())
    return cols_out, joins_out, stats


# ---------------------------------------------------------------------------
# Filters, profiles, ordering (curated, taken from the WHERE snippets in both
# sources; alternates are tried in order at run time)
# ---------------------------------------------------------------------------

FILTERS = [
    dict(name="hidden", where=["zAsset.ZHIDDEN = 1"]),
    dict(name="trashed", where=["zAsset.ZTRASHEDSTATE = 1"]),
    dict(name="favorite", where=["zAsset.ZFAVORITE = 1"]),
    dict(name="locations", where=[
        "(zAsset.ZLATITUDE != -180.0) OR (zExtAttr.ZLATITUDE != -180.0)",
        "zAsset.ZLATITUDE != -180.0"]),
    dict(name="adjusted", where=[
        "zAsset.ZHASADJUSTMENTS = 1",
        "zAsset.ZADJUSTMENTSSTATE > 0"]),
    dict(name="syndication", where=[
        "zAddAssetAttr.ZSYNDICATIONIDENTIFIER IS NOT NULL"]),
]

PROFILES = {
    # full union, mirrors the repo "Basic" query shape (album + internal
    # resource joins mean one asset can span several rows)
    "basic": ["zAddAssetAttr", "zExtAttr", "zIntResou", "zSceneP",
              "zAssetAlbums", "zGenAlbum", "zUnmAdj", "zAlbumLists",
              "zAlbumList", "ParentzGenAlbum", "zCldMast",
              "AAAzCldMastMedData", "CMzCldMastMedData", "zMedAnlyAstAttr",
              "zShare", "zSideCarFile", "SWYConverszGenAlbum"],
    # one row per asset: only joins keyed on Z_PK, which cannot multiply rows
    "very-basic": ["zAddAssetAttr", "zExtAttr", "zCldMast",
                   "AAAzCldMastMedData", "zMedAnlyAstAttr"],
}


ALIAS_TO_TABLE = {
    "zAddAssetAttr": "ZADDITIONALASSETATTRIBUTES",
    "zExtAttr": "ZEXTENDEDATTRIBUTES",
    "zIntResou": "ZINTERNALRESOURCE",
    "zSceneP": "ZSCENEPRINT",
    "zUnmAdj": "ZUNMANAGEDADJUSTMENT",
    "zCldMast": "ZCLOUDMASTER",
    "AAAzCldMastMedData": "ZCLOUDMASTERMEDIAMETADATA",
    "CMzCldMastMedData": "ZCLOUDMASTERMEDIAMETADATA",
    "zMedAnlyAstAttr": "ZMEDIAANALYSISASSETATTRIBUTES",
    "zShare": "ZSHARE",
    "zSideCarFile": "ZSIDECARFILE",
    "zGenAlbum": "ZGENERICALBUM",
    "ParentzGenAlbum": "ZGENERICALBUM",
    "SWYConverszGenAlbum": "ZGENERICALBUM",
    "zAlbumList": "ZALBUMLIST",
}


def schema_map_from(entries):
    """Per (source, version) table->columns map, used for synthetic test DBs.

    Core Data join tables are emitted under generic names (Z_NASSETS with
    Z_N-prefixed columns); the synthetic DB builder substitutes the real
    numbers for the version being built.
    """
    smap = collections.defaultdict(lambda: collections.defaultdict(set))
    for source, version, sql in entries:
        try:
            items, base, joins, _ = parse_query(sql)
        except ValueError:
            continue
        if not base:
            continue
        amap = alias_map_for_query(joins)
        key = (source, version)
        canon = lambda e: rewrite_with_map(canonicalize_sql(e), amap)

        def generic(table):
            if AA_TABLE_RE.match(table) or AL_TABLE_RE.match(table):
                return re.sub(r"Z_\d+", "Z_N", table)
            return table

        tbl_of = {base[1]: base[0]}
        for table, alias, on in joins:
            tbl_of[amap.get(alias, alias)] = generic(table)

        def record(alias, col):
            tbl = tbl_of.get(alias) or ALIAS_TO_TABLE.get(alias)
            if not tbl:
                return
            if tbl.startswith("Z_N"):
                col = re.sub(r"Z_\d+", "Z_N", col)
            smap[key][tbl].add(col)

        for expr, _ in items:
            for a, c in refs_of(canon(expr)):
                record(a, c)
        # both sides of every ON condition: the foreign-key columns often
        # appear nowhere else in the query
        for table, alias, on in joins:
            smap[key][generic(table)]          # table exists even if unused
            for a, c in refs_of(canon(on)):
                record(a, c)
    return {"%s|%s" % k: {t: sorted(c) for t, c in sorted(v.items())}
            for k, v in smap.items()}


IOS_VERSIONS = [11, 12, 13, 14, 15, 16, "17", "17.6", 18, 26]


def _ver_le(a, b):
    def key(v):
        return float(v)
    return key(a) <= key(b)


def read_ileapp_schemas(ileapp_dir):
    """Scan every Ph*/photos* artifact for version-branched queries.

    Returns {ios_version: {table: set(columns)}} - the union of every column
    referenced by any query in any branch covering that version.  This is the
    best available picture of what each iOS version's schema looks like, and
    what the synthetic test databases are built from.
    """
    import glob
    schemas = collections.defaultdict(lambda: collections.defaultdict(set))
    branches_seen = []
    adir = os.path.join(ileapp_dir, "scripts", "artifacts")
    for path in sorted(glob.glob(os.path.join(adir, "*.py"))):
        base = os.path.basename(path)
        if not (base.startswith("Ph0") or base.startswith("photos")):
            continue
        src = read_text(path)
        for func_m in re.finditer(r"\ndef (\w+)\(context\):", src):
            body = src[func_m.end():]
            nxt = re.search(r"\ndef \w+\(context\):", body)
            if nxt:
                body = body[:nxt.start()]
            parts = BRANCH_SPLIT.split(body)
            for i in range(1, len(parts), 3):
                lo, hi, chunk = parts[i], parts[i + 1], parts[i + 2]
                for sql in re.findall(r"query = '''(.*?)'''", chunk, re.S):
                    try:
                        items, base_t, joins, _ = parse_query(sql)
                    except ValueError:
                        continue
                if not base_t:
                    continue
                amap = alias_map_for_query(joins)
                canon = lambda e: rewrite_with_map(
                    canonicalize_sql(e), amap)
                tbl_of = {base_t[1]: base_t[0]}
                for table, alias, on in joins:
                    tbl_of[amap.get(alias, alias)] = table
                for expr, _ in items:
                    for a, c in refs_of(canon(expr)):
                        t = tbl_of.get(a) or ALIAS_TO_TABLE.get(a)
                        if t:
                            schemas_key_add(schemas, lo, hi, t, c,
                                            branches_seen, base, func_m.group(1))
                for table, alias, on in joins:
                    schemas[(lo, hi)][table]    # table exists in this branch
                    for a, c in refs_of(canon(on)):
                        t = tbl_of.get(a) or ALIAS_TO_TABLE.get(a)
                        if t:
                            schemas_key_add(schemas, lo, hi, t, c,
                                            branches_seen, base, func_m.group(1))
    out = {}
    for v in IOS_VERSIONS:
        tab = {}
        for (lo, hi), tables in schemas.items():
            if float(lo) <= float(v) < float(hi):
                for t, cs in tables.items():
                    tab.setdefault(t, set()).update(cs)
        out[str(v)] = {t: sorted(c) for t, c in sorted(tab.items())}
    return out


def schemas_key_add(schemas, lo, hi, table, col, branches_seen, fname, func):
    key = (lo, hi)
    if key not in schemas:
        branches_seen.append((lo, hi, fname, func))
    schemas[key][table].add(col)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--ileapp", required=True)
    ap.add_argument("--out", default="catalog.json")
    ap.add_argument("--schemas-out", default=None,
                    help="also write per-iOS-version schema knowledge "
                         "(default: <out>.schemas_by_ios.json)")
    args = ap.parse_args()

    entries = read_repo(args.repo) + read_ileapp(args.ileapp)
    print("parsed %d query documents" % len(entries))

    cols, joins, stats = merge(entries)

    catalog = dict(
        meta=dict(
            generated=datetime.now(timezone.utc).isoformat(),
            sources=sorted({s for s, _, _ in entries}),
            notes=("Columns merged from the archived iOS 11-17 repo and the "
                   "iLEAPP Ph001/Ph002 artifacts (iOS 11-26). Where the same "
                   "logical column has different expressions across versions "
                   "the newest source wins. Placeholders {{AA_*}}/{{AL_*}} "
                   "are resolved against the actual database at run time."),
        ),
        base_table=["ZASSET", "ZGENERICASSET"],
        order_by=["zAsset.ZADDEDDATE", "zAsset.ZDATECREATED", "zAsset.Z_PK"],
        columns=cols,
        joins=[{k: v for k, v in j.items() if k != "source_table"}
               for j in joins],
        profiles=PROFILES,
        filters=FILTERS,
    )
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(catalog, fh, indent=1, sort_keys=False)
        fh.write("\n")

    with io.open(os.path.splitext(args.out)[0] + ".schema.json", "w",
                 encoding="utf-8", newline="\n") as fh:
        json.dump(schema_map_from(entries), fh, indent=1, sort_keys=True)
        fh.write("\n")

    schemas_path = args.schemas_out or (
        os.path.splitext(args.out)[0] + ".schemas_by_ios.json")
    ios_schemas = read_ileapp_schemas(args.ileapp)
    with io.open(schemas_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(ios_schemas, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("per-version schema knowledge (tables):",
          {v: len(t) for v, t in sorted(ios_schemas.items(), key=lambda kv: float(kv[0]))})

    print("columns: %d   joins: %d" % (len(cols), len(joins)))
    for k in sorted(stats):
        print("  %-28s %d" % (k, stats[k]))
    by_src = collections.Counter(c["first_source"] for c in cols)
    for k, v in sorted(by_src.items()):
        print("  first-seen %-16s %d" % (k, v))
    newest = collections.Counter(c["newest_source"] for c in cols)
    print("  expression provided by:", dict(newest))


if __name__ == "__main__":
    main()
