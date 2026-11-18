#!/usr/bin/env python3
"""Tests for photos_export.py.

Run from the project root:  python -m unittest discover -s tests -v

The tests build synthetic Photos.sqlite databases shaped like each iOS
version (tests/make_synthetic_db.py) and run the exporter as a subprocess.
Differential tests compare against the original query texts when the source
directories are present next to this project (the archived repo and the
iLEAPP source tree); they skip otherwise.
"""

import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import make_synthetic_db as synth  # noqa: E402
import photos_export as px  # noqa: E402

EXPORT = os.path.join(ROOT, "photos_export.py")
REPO = os.environ.get("PSE_REPO") or os.path.normpath(os.path.join(
    ROOT, "..", "iOS_Local_PL_Photos.sqlite_Queries"))
ILEAPP = os.environ.get("PSE_ILEAPP") or os.path.normpath(
    os.path.join(ROOT, "..", "iLEAPP"))


def run_tool(db, *extra):
    out = tempfile.mkdtemp(prefix="pse_test_")
    proc = subprocess.run(
        [sys.executable, EXPORT, db, "-o", out] + list(extra),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, timeout=120)
    return proc, out


def read_csv(path):
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


def col(rows, header, name):
    return [r[header.index(name)] for r in rows]


def find_header(header, prefix):
    """First header starting with prefix (merged names carry suffixes)."""
    for h in header:
        if h == prefix or h.startswith(prefix):
            return h
    raise AssertionError("no header starting with %r in catalog output" % prefix)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pse_db_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def db(self, version, **kw):
        path = os.path.join(self.tmp, "db_ios%s.sqlite" % version)
        synth.build(path, version, **kw)
        return path


class TestAllVersions(Base):
    def test_each_version_exports(self):
        for v in synth.VERSIONS:
            with self.subTest(version=v):
                db = self.db(v)
                proc, out = run_tool(db)
                self.assertEqual(proc.returncode, 0,
                                 "iOS %s: %s" % (v, proc.stderr))
                csv_path = os.path.join(out, "db_ios%s_basic.csv" % v)
                self.assertTrue(os.path.exists(csv_path))
                header, rows = read_csv(csv_path)
                self.assertGreater(len(header), 50)
                self.assertEqual(len(header), len(set(header)), "dup headers")
                self.assertGreaterEqual(len(rows), synth.N_ASSETS)
                pks = {r for r in col(rows, header, "zAsset-zPK")}
                self.assertEqual(len(pks), synth.N_ASSETS)
                # database opened read-only: no sidecar files
                self.assertFalse(os.path.exists(db + "-wal"))
                self.assertFalse(os.path.exists(db + "-shm"))

    def test_report_matches_csv(self):
        db = self.db("17")
        proc, out = run_tool(db)
        report = io.open(os.path.join(out, "export_report.txt"),
                         encoding="utf-8").read()
        header, rows = read_csv(os.path.join(out, "db_ios17_basic.csv"))
        self.assertIn("columns: %d kept" % len(header), report)
        self.assertIn("asset-album join: Z_28ASSETS", report)
        self.assertIn("wrote db_ios17_basic.csv: %d columns x %d rows"
                      % (len(header), len(rows)), report)

    def test_very_basic_profile_one_row_per_asset(self):
        db = self.db("16")
        proc, out = run_tool(db, "--profile", "very-basic")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header, rows = read_csv(os.path.join(out, "db_ios16_very-basic.csv"))
        self.assertEqual(len(rows), synth.N_ASSETS)
        with self.assertRaises(AssertionError):
            find_header(header, "zGenAlbum-Title")


class TestDifferential(unittest.TestCase):
    """Compare exported values against the original query texts.

    Only plain-column and DateTime columns are compared value-for-value;
    CASE columns may carry the label wording of a newer iOS mapping, so their
    values are allowed to differ (the underlying integers are unchanged).
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pse_diff_")
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import build_catalog as bc  # noqa: E402
        cls.bc = bc

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run_original(self, db, sql):
        conn = sqlite3.connect(db)
        cur = conn.execute(sql)
        header = [d[0] for d in cur.description]
        rows = [[("" if px.blob_to_text(v) is None else str(px.blob_to_text(v)))
                 for v in r] for r in cur.fetchall()]
        conn.close()
        return header, rows

    def _compare(self, version, sql, db, csv_path, min_compared):
        """Columns are matched by what they compute (expression shape plus
        referenced columns), not by header text: the merged catalog renames
        some columns and reuses a few old names for different expressions.

        When both outputs have the same row count the value multisets must be
        equal.  When they differ (the original joins fewer row-multiplying
        tables than the basic profile) the (asset PK, value) pairs must be.
        """
        with io.open(os.path.join(ROOT, "catalog.json"), encoding="utf-8") as fh:
            cat = json.load(fh)
        name_of = {(c["shape"], tuple(sorted(tuple(r) for r in c["refs"]))):
                   c["name"] for c in cat["columns"]}

        items, _base, joins, _ = self.bc.parse_query(sql)
        amap = self.bc.alias_map_for_query(joins)
        oheader, orows = self._run_original(db, sql)
        header, rows = read_csv(csv_path)

        keys = []
        for expr, _hdr in items:
            canon = self.bc.rewrite_with_map(
                self.bc.canonicalize_sql(expr), amap)
            keys.append((self.bc.shape_of(canon),
                         tuple(sorted(self.bc.refs_of(canon)))))
        pk_key = ("col", (("zAsset", "Z_PK"),))
        self.assertIn(pk_key, keys, "original query has no zAsset.Z_PK column")
        o_pk = keys.index(pk_key)
        pk_name = name_of[pk_key]
        same_rows = len(orows) == len(rows)

        compared = 0
        for i, key in enumerate(keys):
            if key[0] not in ("col", "datetime"):
                continue          # CASE labels may follow a newer mapping
            name = name_of.get(key)
            if name is None or name not in header:
                continue
            ours = col(rows, header, name)
            if same_rows:
                want, got = sorted(r[i] for r in orows), sorted(ours)
            else:
                want = sorted({(r[o_pk], r[i]) for r in orows})
                got = sorted(set(zip(col(rows, header, pk_name), ours)))
            self.assertEqual(want, got, "%s: column %r (original %r) differs"
                             % (version, name, oheader[i]))
            compared += 1
        self.assertGreater(compared, min_compared,
                           "differential comparison covered too few columns")

    @unittest.skipUnless(os.path.isdir(REPO), "repo not available")
    def test_repo_basic_13_to_17(self):
        for v in ("13", "14", "15", "16", "17"):
            with self.subTest(version=v):
                db = os.path.join(self.tmp, "d%s.sqlite" % v)
                synth.build(db, v)
                proc, out = run_tool(db)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                q = os.path.join(REPO, "iOS%s" % int(float(v)),
                                 "Previous_Queries",
                                 "iOS%s_LPL_Phsql_Basic.txt" % int(float(v)))
                sql = self.bc.read_text(q)
                self._compare(v, sql, db,
                              os.path.join(out, "d%s_basic.csv" % v), 20)

    @unittest.skipUnless(os.path.isdir(REPO), "repo not available")
    def test_repo_very_basic_11_12(self):
        # the 11/12 Very-Basic texts join the album link table, so compare
        # against the default basic profile, which has the same multiplicity
        for v in ("11", "12"):
            with self.subTest(version=v):
                db = os.path.join(self.tmp, "d%s.sqlite" % v)
                synth.build(db, v)
                proc, out = run_tool(db)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                q = os.path.join(REPO, "iOS%s" % v, "Previous_Queries",
                                 "iOS%s_LPL_Phsql_Very-Basic.txt" % v)
                sql = self.bc.read_text(q)
                self._compare(v, sql, db,
                              os.path.join(out, "d%s_basic.csv" % v), 15)

    @unittest.skipUnless(os.path.isdir(ILEAPP), "iLEAPP not available")
    def test_ileapp_ph002_ios26(self):
        import re
        src = io.open(os.path.join(
            ILEAPP, "scripts", "artifacts",
            "Ph002BasicAssetandAlbumData.py"), encoding="utf-8").read()
        body = re.search(r"\ndef Ph002_1AssetBasicGenAlbumDataPhDaPsql"
                         r"\(context\):.*?(?=\ndef |\Z)", src, re.S).group(0)
        sql = None
        parts = self.bc.BRANCH_SPLIT.split(body)
        for i in range(1, len(parts), 3):
            if parts[i] == "26":
                m = re.search(r"query = '''(.*?)'''", parts[i + 2], re.S)
                if m:
                    sql = m.group(1)
        self.assertIsNotNone(sql, "iOS 26 branch not found in Ph002")
        db = os.path.join(self.tmp, "d26.sqlite")
        synth.build(db, "26")
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._compare("26", sql, db, os.path.join(out, "d26_basic.csv"), 15)


class TestFilters(Base):
    def test_filters_select_expected_assets(self):
        db = self.db("26")
        proc, out = run_tool(db, "--all-filters")
        # hidden/trashed/favorite/locations/adjusted/syndication all apply
        self.assertEqual(proc.returncode, 0, proc.stderr)
        f = synth.FACTS
        expect = dict(hidden=f["hidden"], trashed=f["trashed"],
                      favorite=f["favorite"], locations=f["located"],
                      adjusted=f["adjusted"], syndication=f["syndicated"])
        for name, assets in expect.items():
            path = os.path.join(out, "db_ios26_basic_%s.csv" % name)
            header, rows = read_csv(path)
            pks = {int(x) for x in col(rows, header, "zAsset-zPK")}
            self.assertEqual(pks, assets, "filter %s" % name)

    def test_locations_includes_southern_hemisphere(self):
        # asset 3 sits at a negative latitude; the old repo condition
        # (ZLATITUDE > 0) would have missed it
        db = self.db("17")
        proc, out = run_tool(db, "--filter", "locations")
        header, rows = read_csv(os.path.join(out, "db_ios17_basic_locations.csv"))
        pks = {int(x) for x in col(rows, header, "zAsset-zPK")}
        self.assertEqual(pks, synth.FACTS["located"])

    def test_adjusted_uses_ios18_column(self):
        db = self.db("18")
        proc, out = run_tool(db, "--filter", "adjusted")
        header, rows = read_csv(os.path.join(out, "db_ios18_basic_adjusted.csv"))
        pks = {int(x) for x in col(rows, header, "zAsset-zPK")}
        self.assertEqual(pks, synth.FACTS["adjusted"])
        report = io.open(os.path.join(out, "export_report.txt"),
                         encoding="utf-8").read()
        self.assertIn("filter adjusted: using zAsset.ZADJUSTMENTSSTATE > 0",
                      report)

    def test_inapplicable_filter_skipped_with_report(self):
        db = self.db("11")            # no ZSYNDICATIONIDENTIFIER before iOS 15
        proc, out = run_tool(db, "--filter", "syndication")
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(os.path.exists(os.path.join(out, "db_ios11_basic.csv")))
        report = io.open(os.path.join(out, "export_report.txt"),
                         encoding="utf-8").read()
        self.assertIn("SKIPPED", report)

    def test_custom_where(self):
        db = self.db("17")
        proc, out = run_tool(db, "--where", "zAsset.ZFAVORITE = 1")
        header, rows = read_csv(os.path.join(out, "db_ios17_basic_custom.csv"))
        pks = {int(x) for x in col(rows, header, "zAsset-zPK")}
        self.assertEqual(pks, {1})


class TestDegradation(Base):
    def test_missing_column_dropped_and_reported(self):
        db = self.db("17", drop_columns=[("ZASSET", "ZFILENAME")])
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header, rows = read_csv(os.path.join(out, "db_ios17_basic.csv"))
        self.assertNotIn("zAsset-Filename", header)
        report = io.open(os.path.join(out, "export_report.txt"),
                         encoding="utf-8").read()
        self.assertIn("ZASSET.ZFILENAME missing", report)

    def test_missing_table_dropped(self):
        db = self.db("17", drop_tables=("ZCLOUDMASTER",))
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header, rows = read_csv(os.path.join(out, "db_ios17_basic.csv"))
        self.assertFalse(any(h.startswith("zCldMast-") for h in header))
        self.assertGreater(len(header), 100)

    def test_missing_link_table_loses_albums_only(self):
        spec = synth.SPECS["17"]
        db = self.db("17", drop_tables=(spec["aa"][0],))
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header, rows = read_csv(os.path.join(out, "db_ios17_basic.csv"))
        self.assertFalse(any(h.startswith("zGenAlbum-") for h in header))
        self.assertIn("zAsset-Filename", header)
        # the album join no longer multiplies rows; the internal-resource
        # join still does (asset 1 has two resources)
        expected = sum(synth.FACTS["intres"].get(i, 1)
                       for i in range(1, synth.N_ASSETS + 1))
        self.assertEqual(len(rows), expected)

    def test_without_primarykey_pattern_fallback(self):
        db = self.db("16", with_primarykey=False)
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header, rows = read_csv(os.path.join(out, "db_ios16_basic.csv"))
        titles = col(rows, header, find_header(header, "zGenAlbum-Title"))
        self.assertIn("Album 1", titles)

    def test_future_link_renumbering(self):
        # simulate an unknown future iOS renumbering the link table
        db = self.db("26", rename_link=("Z_40ASSETS", 40, 3))
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header, rows = read_csv(os.path.join(out, "db_ios26_basic.csv"))
        titles = col(rows, header, find_header(header, "zGenAlbum-Title"))
        self.assertIn("Album 2", titles)
        report = io.open(os.path.join(out, "export_report.txt"),
                         encoding="utf-8").read()
        self.assertIn("Z_40ASSETS", report)
        self.assertIn("unknown version", report)

    def test_keep_missing_emits_null_columns(self):
        with io.open(os.path.join(ROOT, "catalog.json"), encoding="utf-8") as fh:
            cat = json.load(fh)
        db = self.db("26")
        proc, out = run_tool(db, "--keep-missing")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header, rows = read_csv(os.path.join(out, "db_ios26_basic.csv"))
        self.assertEqual(len(header), len(cat["columns"]))
        self.assertIn("zAddAssetAttr-Master Fingerprint", header)
        idx = header.index("zAddAssetAttr-Master Fingerprint")
        self.assertTrue(all(r[idx] == "" for r in rows))


class TestBadInputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pse_bad_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, path):
        return run_tool(path)

    def test_not_found(self):
        proc, _ = run_tool(os.path.join(self.tmp, "nope.sqlite"))
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_text_file(self):
        p = os.path.join(self.tmp, "text.sqlite")
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write("this is not a database\n" * 100)
        proc, _ = self._run(p)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_empty_file(self):
        p = os.path.join(self.tmp, "empty.sqlite")
        io.open(p, "w").close()
        proc, _ = self._run(p)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_unrelated_sqlite(self):
        p = os.path.join(self.tmp, "other.sqlite")
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE t (x)")
        conn.commit()
        conn.close()
        proc, _ = self._run(p)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)


class TestCsvContent(Base):
    def test_encoding_blobs_and_newlines(self):
        db = self.db("17")
        proc, out = run_tool(db)
        path = os.path.join(out, "db_ios17_basic.csv")
        raw = io.open(path, "rb").read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "missing BOM")
        header, rows = read_csv(path)
        names = col(rows, header, "zAsset-Filename")
        self.assertIn(synth.UNICODE_NAME, names)
        # the blob column comes back as hex
        with io.open(path, encoding="utf-8-sig", newline="") as fh:
            r = list(csv.DictReader(fh))
        blobs = [row for row in r
                 if any(v and v.startswith("0x") for v in row.values())]
        self.assertTrue(blobs, "no blob rendered as hex")

    def test_rows_ordered_by_added_date(self):
        db = self.db("18")
        proc, out = run_tool(db)
        header, rows = read_csv(os.path.join(out, "db_ios18_basic.csv"))
        date_col = "zAsset-Add Date" if "zAsset-Add Date" in header else \
            "zAsset-Added Date"
        dates = col(rows, header, date_col)
        self.assertEqual(dates, sorted(dates))

    def test_database_untouched(self):
        db = self.db("15")
        before = hashlib.sha256(io.open(db, "rb").read()).hexdigest()
        proc, out = run_tool(db, "--all-filters")
        after = hashlib.sha256(io.open(db, "rb").read()).hexdigest()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
