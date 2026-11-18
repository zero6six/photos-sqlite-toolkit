#!/usr/bin/env python3
"""Build synthetic Photos.sqlite databases shaped like each iOS version.

The table/column sets come from the schema knowledge emitted by
tools/build_catalog.py (catalog.schema.json for the exact per-version repo
queries, catalog.schemas_by_ios.json for the iLEAPP artifacts), so each
database carries the tables, columns and Core Data link-table numbering that
the real queries for that version expect.  The rows are small and
deterministic so tests can assert exact results.

These databases exercise the export mechanics.  They are not real device
data and say nothing about values Apple actually stores.
"""

import io
import json
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# version -> (base table, asset entity name, link-table numbers)
#   aa = (album entity no., asset entity no.)   -> Z_<album>ASSETS
#   al = (album entity no., albumlist entity no.) -> Z_<album-1...>ALBUMLISTS
SPECS = {
    "11":   dict(base="ZGENERICASSET", asset_ent="GenericAsset",
                 aa=("Z_20ASSETS", 20, 27), al=("Z_19ALBUMLISTS", 19, 3),
                 share=None),
    "12":   dict(base="ZGENERICASSET", asset_ent="GenericAsset",
                 aa=("Z_23ASSETS", 23, 30), al=("Z_22ALBUMLISTS", 22, 3),
                 share=None),
    "13":   dict(base="ZGENERICASSET", asset_ent="GenericAsset",
                 aa=("Z_26ASSETS", 26, 34), al=("Z_25ALBUMLISTS", 25, 3),
                 share="ZMOMENTSHARE"),
    "14":   dict(base="ZASSET", asset_ent="Asset",
                 aa=("Z_26ASSETS", 26, 3), al=("Z_25ALBUMLISTS", 25, 2),
                 share="ZSHARE"),
    "15":   dict(base="ZASSET", asset_ent="Asset",
                 aa=("Z_27ASSETS", 27, 3), al=("Z_26ALBUMLISTS", 26, 2),
                 share="ZSHARE"),
    "16":   dict(base="ZASSET", asset_ent="Asset",
                 aa=("Z_28ASSETS", 28, 3), al=("Z_27ALBUMLISTS", 27, 2),
                 share="ZSHARE"),
    "17":   dict(base="ZASSET", asset_ent="Asset",
                 aa=("Z_28ASSETS", 28, 3), al=("Z_27ALBUMLISTS", 27, 2),
                 share="ZSHARE"),
    "17.6": dict(base="ZASSET", asset_ent="Asset",
                 aa=("Z_29ASSETS", 29, 3), al=("Z_28ALBUMLISTS", 28, 2),
                 share="ZSHARE"),
    "18":   dict(base="ZASSET", asset_ent="Asset",
                 aa=("Z_30ASSETS", 30, 3), al=("Z_29ALBUMLISTS", 29, 2),
                 share="ZSHARE"),
    "26":   dict(base="ZASSET", asset_ent="Asset",
                 aa=("Z_33ASSETS", 33, 3), al=("Z_32ALBUMLISTS", 32, 2),
                 share="ZSHARE"),
}
VERSIONS = list(SPECS)

LINK_RE = re.compile(r"^Z_(\d+|N)(ASSETS|ALBUMLISTS)$")

# Columns the filter presets rely on, by first/last version carrying them.
ALWAYS_BASE = ["ZHIDDEN", "ZTRASHEDSTATE", "ZFAVORITE", "ZLATITUDE",
               "ZLONGITUDE", "ZADDEDDATE", "ZDATECREATED", "ZFILENAME",
               "ZADDITIONALATTRIBUTES", "ZMASTER"]

N_ASSETS = 5
FACTS = dict(
    hidden={2}, trashed={3}, favorite={1}, located={1, 3}, adjusted={4},
    syndicated={5},
    albums={1: [1, 2], 2: [1]},       # asset -> album PKs
    intres={1: 2},                    # asset -> internal-resource row count
)
UNICODE_NAME = u'\u7167\u7247, "\u6d4b\u8bd5"\n\u7b2c\u4e8c\u884c.jpg'


def _load(name):
    with io.open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return json.load(fh)


def schema_for(version):
    """table -> sorted column list for one iOS version."""
    spec = SPECS[version]
    exact = _load("catalog.schema.json")
    by_ios = _load("catalog.schemas_by_ios.json")

    know = {}

    def merge(tables):
        for t, cols in tables.items():
            know.setdefault(t, set()).update(cols)

    for key, tables in exact.items():
        source, ver = key.split("|")
        if source.startswith("repo") and ver == version:
            merge(tables)
    merge(by_ios.get(version, {}))

    tables = {}
    base_cols = set(ALWAYS_BASE)
    share_cols = set()
    for t, cols in know.items():
        if t in ("ZASSET", "ZGENERICASSET"):
            base_cols |= set(cols)
        elif t in ("ZSHARE", "ZMOMENTSHARE"):
            share_cols |= set(cols)
        elif LINK_RE.match(t):
            continue                      # rebuilt from the spec below
        else:
            tables[t] = set(cols)
    tables[spec["base"]] = base_cols
    if spec["share"]:
        tables[spec["share"]] = share_cols
        base_cols.add("ZMOMENTSHARE")

    # version-accurate presence of the columns iOS 18 replaced
    ver_f = float(version)
    add_attr = tables.setdefault("ZADDITIONALASSETATTRIBUTES", set())
    add_attr.add("ZASSET")
    if ver_f >= 18:
        base_cols.discard("ZHASADJUSTMENTS")
        base_cols.add("ZADJUSTMENTSSTATE")
        add_attr.discard("ZMASTERFINGERPRINT")
        add_attr.discard("ZADJUSTEDFINGERPRINT")
        add_attr.update(["ZORIGINALSTABLEHASH", "ZADJUSTEDSTABLEHASH"])
    else:
        base_cols.add("ZHASADJUSTMENTS")
        base_cols.discard("ZADJUSTMENTSSTATE")
    if ver_f >= 15:
        add_attr.add("ZSYNDICATIONIDENTIFIER")
    else:
        add_attr.discard("ZSYNDICATIONIDENTIFIER")
    if ver_f >= 13:
        base_cols.add("ZEXTENDEDATTRIBUTES")
        tables.setdefault("ZEXTENDEDATTRIBUTES", set()).update(
            ["ZLATITUDE", "ZLONGITUDE"])

    tables.setdefault("ZGENERICALBUM", set()).update(["ZTITLE", "ZPARENTFOLDER"])
    tables.setdefault("ZALBUMLIST", set())
    for cols in tables.values():
        cols.update(["Z_PK", "Z_ENT", "Z_OPT"])

    aa_t, alb_n, ast_n = spec["aa"]
    al_t, alb2_n, lst_n = spec["al"]
    tables[aa_t] = {"Z_%dALBUMS" % alb_n, "Z_%dASSETS" % ast_n}
    tables[al_t] = {"Z_%dALBUMS" % alb2_n, "Z_%dALBUMLISTS" % lst_n}
    return {t: sorted(c) for t, c in sorted(tables.items())}


TEXT_HINT = re.compile(
    r"(UUID|GUID|IDENTIFIER|NAME|TITLE|FINGERPRINT|HASH|STRING|MAKE|MODEL|"
    r"DIRECTORY|PATH|BUNDLEID|CODEC|PROFILE|TYPEIDENTIFIER|DESCRIPTION)$")
DATE_HINT = re.compile(r"(DATE|TIMESTAMP)$")
BLOB_HINT = re.compile(r"(DATA|HINTS|PLIST)$")

FK_VALUES = {
    "ZADDITIONALATTRIBUTES": lambda i: i,
    "ZEXTENDEDATTRIBUTES": lambda i: i,
    "ZMASTER": lambda i: i,
    "ZMEDIAANALYSISATTRIBUTES": lambda i: i,
    "ZMOMENTSHARE": lambda i: 1 if i == 1 else None,
    "ZCONVERSATION": lambda i: None,
    "ZMOMENT": lambda i: None,
    "ZSCENEPRINT": lambda i: i,
    "ZUNMANAGEDADJUSTMENT": lambda i: i,
}


def value_for(table, col, i, version):
    """Deterministic cell value for row i (1-based) of a per-asset table."""
    base = SPECS[version]["base"]
    if col == "Z_PK":
        return i
    if col in ("Z_ENT", "Z_OPT"):
        return 1
    if table == base:
        if col == "ZHIDDEN":
            return 1 if i in FACTS["hidden"] else 0
        if col == "ZTRASHEDSTATE":
            return 1 if i in FACTS["trashed"] else 0
        if col == "ZFAVORITE":
            return 1 if i in FACTS["favorite"] else 0
        if col == "ZHASADJUSTMENTS":
            return 1 if i in FACTS["adjusted"] else 0
        if col == "ZADJUSTMENTSSTATE":
            return 2 if i in FACTS["adjusted"] else 0
        if col == "ZLATITUDE":
            return {1: 31.2304, 3: -33.8688}.get(i, -180.0)
        if col == "ZLONGITUDE":
            return {1: 121.4737, 3: 151.2093}.get(i, -180.0)
        if col == "ZFILENAME":
            return UNICODE_NAME if i == 4 else "IMG_%04d.HEIC" % i
        if col == "ZADDEDDATE":
            return 700000000.0 + i * 1000
        if col in FK_VALUES:
            return FK_VALUES[col](i)
    if table == "ZADDITIONALASSETATTRIBUTES":
        if col == "ZASSET":
            return i
        if col == "ZMEDIAMETADATA":
            return i
        if col == "ZSYNDICATIONIDENTIFIER":
            return "synd-%d" % i if i in FACTS["syndicated"] else None
        if col in FK_VALUES:
            return FK_VALUES[col](i)
    if table == "ZCLOUDMASTER" and col == "ZMEDIAMETADATA":
        return 100 + i
    if table == "ZEXTENDEDATTRIBUTES":
        if col == "ZLATITUDE":
            return {1: 31.2304, 3: -33.8688}.get(i, -180.0)
        if col == "ZLONGITUDE":
            return {1: 121.4737, 3: 151.2093}.get(i, -180.0)
    if table == "ZSIDECARFILE" and col == "ZASSET":
        return i
    if BLOB_HINT.search(col):
        return None if i % 4 == 0 else b"bplist00" + bytes([i, 0xff])
    if DATE_HINT.search(col):
        return None if i % 5 == 0 else 690000000.0 + i * 86400
    if TEXT_HINT.search(col):
        return "%s-%d" % (col.lower(), i)
    return i % 3


def build(path, version, with_primarykey=True, drop_tables=(), drop_columns=(),
          rename_link=None):
    """Create the database.  Returns the schema dict actually written.

    drop_columns: iterable of (table, column) removed from the schema.
    rename_link:  (new_table, new_album_no, new_asset_no) to simulate a future
                  iOS renumbering of the asset-album link table.
    """
    if os.path.exists(path):
        os.remove(path)
    spec = SPECS[version]
    tables = {t: list(c) for t, c in schema_for(version).items()}

    aa_t, alb_n, ast_n = spec["aa"]
    al_t, alb2_n, lst_n = spec["al"]
    if rename_link:
        new_t, new_alb, new_ast = rename_link
        del tables[aa_t]
        aa_t, alb_n, ast_n = new_t, new_alb, new_ast
        tables[aa_t] = ["Z_%dALBUMS" % alb_n, "Z_%dASSETS" % ast_n]

    for t in drop_tables:
        tables.pop(t, None)
    for t, c in drop_columns:
        if t in tables and c in tables[t]:
            tables[t].remove(c)

    conn = sqlite3.connect(path)
    cur = conn.cursor()
    for t, cols in tables.items():
        cur.execute('CREATE TABLE "%s" (%s)'
                    % (t, ", ".join('"%s"' % c for c in cols)))

    if with_primarykey:
        cur.execute("CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY, "
                    "Z_NAME VARCHAR, Z_SUPER INTEGER, Z_MAX INTEGER)")
        ents = {alb_n: "GenericAlbum", ast_n: spec["asset_ent"],
                lst_n: "AlbumList"}
        if alb2_n not in ents:
            ents[alb2_n] = "Album"
        for num, name in sorted(ents.items()):
            cur.execute("INSERT INTO Z_PRIMARYKEY VALUES (?,?,0,0)", (num, name))

    def insert(table, row):
        cols = tables[table]
        cur.execute('INSERT INTO "%s" (%s) VALUES (%s)'
                    % (table, ", ".join('"%s"' % c for c in cols),
                       ", ".join("?" for _ in cols)),
                    [row.get(c) for c in cols])

    per_asset = [t for t in tables
                 if t not in (aa_t, al_t, "ZGENERICALBUM", "ZALBUMLIST",
                              "ZINTERNALRESOURCE", "ZCLOUDMASTERMEDIAMETADATA",
                              spec["share"])]
    for t in per_asset:
        for i in range(1, N_ASSETS + 1):
            insert(t, {c: value_for(t, c, i, version) for c in tables[t]})

    if "ZCLOUDMASTERMEDIAMETADATA" in tables:
        t = "ZCLOUDMASTERMEDIAMETADATA"
        for pk in list(range(1, N_ASSETS + 1)) + \
                [100 + i for i in range(1, N_ASSETS + 1)]:
            row = {c: value_for(t, c, pk % 100 or 1, version) for c in tables[t]}
            row["Z_PK"] = pk
            insert(t, row)

    if "ZINTERNALRESOURCE" in tables:
        t = "ZINTERNALRESOURCE"
        pk = 0
        for i in range(1, N_ASSETS + 1):
            for _ in range(FACTS["intres"].get(i, 1)):
                pk += 1
                row = {c: value_for(t, c, pk, version) for c in tables[t]}
                row["Z_PK"] = pk
                if "ZASSET" in tables[t]:
                    row["ZASSET"] = i
                insert(t, row)

    if spec["share"] and spec["share"] in tables:
        t = spec["share"]
        insert(t, {c: value_for(t, c, 1, version) for c in tables[t]})

    if "ZGENERICALBUM" in tables:
        t = "ZGENERICALBUM"
        for a in (1, 2):
            row = {c: value_for(t, c, a, version) for c in tables[t]}
            row["ZTITLE"] = "Album %d" % a
            row["ZPARENTFOLDER"] = 1 if a == 2 else None
            insert(t, row)
    if "ZALBUMLIST" in tables:
        t = "ZALBUMLIST"
        insert(t, {c: value_for(t, c, 1, version) for c in tables[t]})
    if aa_t in tables:
        for asset, albums in sorted(FACTS["albums"].items()):
            for album in albums:
                insert(aa_t, {"Z_%dALBUMS" % alb_n: album,
                              "Z_%dASSETS" % ast_n: asset})
    if al_t in tables:
        for album in (1, 2):
            insert(al_t, {"Z_%dALBUMS" % alb2_n: album,
                          "Z_%dALBUMLISTS" % lst_n: 1})

    conn.commit()
    conn.close()
    return tables


def expected_basic_rows(tables, version):
    """Row count the basic profile should produce for this schema."""
    spec = SPECS[version]
    aa_ok = any(LINK_RE.match(t) and t.endswith("ASSETS") for t in tables) \
        and "ZGENERICALBUM" in tables
    ir_ok = "ZINTERNALRESOURCE" in tables and \
        "ZASSET" in tables["ZINTERNALRESOURCE"]
    total = 0
    for i in range(1, N_ASSETS + 1):
        n = 1
        if aa_ok:
            n *= max(1, len(FACTS["albums"].get(i, [])))
        if ir_ok:
            n *= FACTS["intres"].get(i, 1)
        total += n
    return total


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    for v in VERSIONS:
        p = os.path.join(out, "Photos_ios%s.sqlite" % v)
        t = build(p, v)
        print("%-6s %s  tables=%d  base cols=%d" % (
            v, os.path.basename(p), len(t), len(t[SPECS[v]["base"]])))
