#!/usr/bin/env python3
"""Tests for the WAL differential export (photos_export.py >= 0.2.0).

A non-empty <db>-wal sidecar switches the exporter into a two-pass
differential run: pass 1 reads the pre-checkpoint snapshot of the main file
(immutable), pass 2 reads a checkpointed COPY of db+wal.  The fixture below
reproduces a device pulled mid-life: a child process commits an UPDATE, a
DELETE and an INSERT into the WAL with autocheckpointing disabled, then
hard-exits so the WAL survives.  The originals must come out untouched (the
diff has to be repeatable); the expected classification on the synthetic
iOS 26 database is

    asset 1, 4, 5  unchanged
    asset 2        modified   (ZFILENAME -> WALMOD_2)
    asset 3        removed    (deleted in the WAL, snapshot rows survive)
    asset 999      added      (inserted in the WAL)
"""

import hashlib
import io
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import make_synthetic_db as synth          # noqa: E402
import photos_export as px                 # noqa: E402
from test_export import Base, run_tool, read_csv, col  # noqa: E402

CRASH_CHILD = r"""
import os, sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db, isolation_level=None)
conn.execute("PRAGMA journal_mode=wal")
conn.execute("PRAGMA wal_autocheckpoint=0")
conn.execute("BEGIN IMMEDIATE")
conn.execute("UPDATE ZASSET SET ZFILENAME='WALMOD_'||Z_PK WHERE Z_PK=2")
conn.execute("DELETE FROM ZASSET WHERE Z_PK=3")
conn.execute("INSERT INTO ZASSET (Z_PK, Z_ENT, Z_OPT, ZUUID, ZFILENAME, "
             "ZFAVORITE, ZADDEDDATE) VALUES (999, 1, 1, 'uuid-999', "
             "'ADDED_999.HEIC', 1, 700999000.0)")
conn.execute("COMMIT")
os._exit(1)
"""

# the competition scenario: create, mark-as-trashed and delete an asset in
# three SEPARATE transactions, all left in the WAL - the asset exists in no
# state a two-pass diff would ever see (absent from both the snapshot and
# the final state); only WAL replay surfaces it
CRASH_CHILD_3TX = r"""
import os, sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db, isolation_level=None)
conn.execute("PRAGMA journal_mode=wal")
conn.execute("PRAGMA wal_autocheckpoint=0")
conn.execute("BEGIN IMMEDIATE")
conn.execute("INSERT INTO ZASSET (Z_PK, Z_ENT, Z_OPT, ZUUID, ZFILENAME, "
             "ZADDEDDATE, ZDATECREATED, ZTRASHEDSTATE, ZTRASHEDDATE) "
             "VALUES (999, 1, 1, 'uuid-999', 'IMG_0001.PNG', 806820793.6, "
             "806820793.6, 0, NULL)")
conn.execute("COMMIT")
conn.execute("BEGIN IMMEDIATE")
conn.execute("UPDATE ZASSET SET ZTRASHEDSTATE=1, ZTRASHEDDATE=806820806.599 "
             "WHERE Z_PK=999")
conn.execute("COMMIT")
conn.execute("BEGIN IMMEDIATE")
conn.execute("DELETE FROM ZASSET WHERE Z_PK=999")
conn.execute("COMMIT")
os._exit(1)
"""


def crash_write_wal(db):
    """Commit update/delete/insert into a fresh -wal, then hard-exit."""
    proc = subprocess.run([sys.executable, "-c", CRASH_CHILD, db])
    assert proc.returncode == 1, "crash writer should hard-exit(1)"
    assert os.path.getsize(db + "-wal") > 0, "no WAL survived the crash"


def sha(path):
    with io.open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class TestWalDiff(Base):
    def wal_db(self, version="26"):
        db = os.path.join(self.tmp, "wal%s.sqlite" % version)
        synth.build(db, version)
        crash_write_wal(db)
        return db

    def asset_statuses(self, header, rows):
        by_pk = {}
        for r in rows:
            by_pk.setdefault(r[header.index("zAsset-zPK")],
                             set()).add(r[header.index("wal-diff-status")])
        return {k: next(iter(v)) for k, v in by_pk.items()}

    def test_classification(self):
        db = self.wal_db()
        db_before, wal_before = sha(db), sha(db + "-wal")
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header, rows = read_csv(os.path.join(out, "wal26_basic.csv"))
        self.assertIn("wal-diff-status", header)
        got = self.asset_statuses(header, rows)
        self.assertEqual(got, {"1": "unchanged", "2": "modified",
                               "3": "removed", "4": "unchanged",
                               "5": "unchanged", "999": "added"})
        # values come from the right state
        names = {(r[header.index("zAsset-zPK")], r[header.index("zAsset-Filename")],
                  r[header.index("wal-diff-status")]) for r in rows}
        self.assertIn(("2", "WALMOD_2", "modified"), names)      # post state
        self.assertIn(("3", "IMG_0003.HEIC", "removed"), names)  # snapshot
        self.assertIn(("999", "ADDED_999.HEIC", "added"), names)
        # provenance: snapshot asset first/last = 0; WAL-inserted = 1/1
        prov = {r[header.index("zAsset-zPK")]:
                (r[header.index("wal-first-commit")],
                 r[header.index("wal-last-commit")]) for r in rows}
        self.assertEqual(prov["3"], ("0", "0"))
        self.assertEqual(prov["999"], ("1", "1"))
        self.assertEqual(prov["2"], ("0", "1"))
        # originals untouched: the diff stays repeatable
        self.assertEqual((sha(db), sha(db + "-wal")), (db_before, wal_before))
        # disposable work dir cleaned up
        self.assertFalse(os.path.exists(os.path.join(out, "_wal_work")))

    def test_replay_surfaces_created_and_deleted_inside_wal(self):
        # the 009 scenario: an asset created, trashed and deleted in three
        # separate WAL commits is invisible to both the snapshot and the
        # final state - the replay must still surface it as removed, with
        # the values (trash markers included) of the last state that saw it
        db = os.path.join(self.tmp, "wal3tx.sqlite")
        synth.build(db, "26")
        proc = subprocess.run([sys.executable, "-c", CRASH_CHILD_3TX, db])
        self.assertEqual(proc.returncode, 1)
        self.assertGreater(os.path.getsize(db + "-wal"), 0)
        wal_before = sha(db + "-wal")
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header, rows = read_csv(os.path.join(out, "wal3tx_basic.csv"))
        got = self.asset_statuses(header, rows)
        self.assertEqual(got["999"], "removed")
        row = next(r for r in rows if r[header.index("zAsset-zPK")] == "999")
        ts_col = next(i for i, h in enumerate(header)
                      if h.lower().startswith("zasset-trashed state"))
        td_col = next(i for i, h in enumerate(header)
                      if h.lower().startswith("zasset-trashed date"))
        self.assertEqual(row[header.index("zAsset-Filename")], "IMG_0001.PNG")
        self.assertIn("In Trash", row[ts_col])       # the trash marker
        self.assertNotEqual(row[td_col].strip(), "")  # and the trash date
        # first seen at the INSERT commit, last seen at the TRASH commit
        self.assertEqual(row[header.index("wal-first-commit")], "1")
        self.assertEqual(row[header.index("wal-last-commit")], "2")
        # snapshot assets are untouched and span the full replay
        prov = {r[header.index("zAsset-zPK")]:
                (r[header.index("wal-first-commit")],
                 r[header.index("wal-last-commit")]) for r in rows}
        self.assertEqual(prov["1"], ("0", "3"))
        # the original WAL survived the replay
        self.assertEqual(sha(db + "-wal"), wal_before)

    def test_report_records_wal(self):
        db = self.wal_db()
        size = os.path.getsize(db + "-wal")
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with io.open(os.path.join(out, "export_report.txt"),
                     encoding="utf-8") as fh:
            report = fh.read()
        self.assertIn("wal: %d-byte sidecar" % size, report)
        self.assertIn("commits, 0 dead frames", report)
        self.assertIn("replayed states 0 (snapshot) .. 1 (final)", report)
        self.assertIn("wal diff: 3 unchanged, 1 added, 1 removed, 1 modified",
                      report)
        self.assertIn("wal: work copy removed", report)

    def test_keep_wal_work(self):
        db = self.wal_db()
        proc, out = run_tool(db, "--keep-wal-work")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        work = os.path.join(out, "_wal_work")
        # the final state's replay copy is kept for inspection
        final = os.path.join(work, "state_final", "wal26.sqlite")
        self.assertTrue(os.path.exists(final))
        with io.open(os.path.join(out, "export_report.txt"),
                     encoding="utf-8") as fh:
            report = fh.read()
        self.assertIn("wal: work copy kept", report)

    def test_no_wal_diff_flag(self):
        db = self.wal_db()
        proc, out = run_tool(db, "--no-wal-diff")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("differential export", proc.stdout)
        header, rows = read_csv(os.path.join(out, "wal26_basic.csv"))
        self.assertNotIn("wal-diff-status", header)
        # single pass reads the full state (through the WAL)
        pks = {int(x) for x in col(rows, header, "zAsset-zPK")}
        self.assertEqual(pks, {1, 2, 4, 5, 999})

    def test_empty_wal_single_pass(self):
        db = os.path.join(self.tmp, "wal_empty.sqlite")
        synth.build(db, "26")
        io.open(db + "-wal", "wb").close()          # 0-byte sidecar
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("differential export", proc.stdout)
        header, rows = read_csv(os.path.join(out, "wal_empty_basic.csv"))
        self.assertNotIn("wal-diff-status", header)
        pks = {int(x) for x in col(rows, header, "zAsset-zPK")}
        self.assertEqual(pks, set(range(1, synth.N_ASSETS + 1)))

    def test_filters_share_the_diff(self):
        db = self.wal_db()
        proc, out = run_tool(db, "--filter", "favorite")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        path = os.path.join(out, "wal26_basic_favorite.csv")
        header, rows = read_csv(path)
        self.assertIn("wal-diff-status", header)
        got = self.asset_statuses(header, rows)
        # asset 1 was favorite all along; the WAL-inserted 999 arrives as
        # favorite too
        self.assertEqual(got, {"1": "unchanged", "999": "added"})


# partial checkpoint: history folded into the main file mid-generation,
# exactly like a live phone (SQLite checkpoints passively while the WAL
# keeps its frames).  The main file is then a mid-history state, not the
# pre-WAL state.
CRASH_CHILD_PC = r"""
import os, sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db, isolation_level=None)
conn.execute("PRAGMA journal_mode=wal")
conn.execute("PRAGMA wal_autocheckpoint=0")
conn.execute("BEGIN IMMEDIATE")
conn.execute("INSERT INTO ZASSET (Z_PK, Z_ENT, Z_OPT, ZUUID, ZFILENAME, "
             "ZADDEDDATE, ZDATECREATED, ZTRASHEDSTATE, ZTRASHEDDATE) "
             "VALUES (800, 1, 1, 'uuid-800', 'IMG_0800.PNG', 806820793.6, "
             "806820793.6, 0, NULL)")
conn.execute("COMMIT")
conn.execute("BEGIN IMMEDIATE")
conn.execute("UPDATE ZASSET SET ZTRASHEDSTATE=1, ZTRASHEDDATE=806820806.599 "
             "WHERE Z_PK=800")
conn.execute("COMMIT")
# fold what exists so far into the main file; the WAL keeps its frames
conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
conn.execute("BEGIN IMMEDIATE")
conn.execute("DELETE FROM ZASSET WHERE Z_PK=800")
conn.execute("COMMIT")
os._exit(1)
"""


class TestWalPartialCheckpoint(Base):
    def test_asset_deleted_after_partial_checkpoint(self):
        db = os.path.join(self.tmp, "walpc.sqlite")
        synth.build(db, "26")
        proc = subprocess.run([sys.executable, "-c", CRASH_CHILD_PC, db])
        self.assertEqual(proc.returncode, 1)
        self.assertGreater(os.path.getsize(db + "-wal"), 0)
        wal_before = sha(db + "-wal")
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header, rows = read_csv(os.path.join(out, "walpc_basic.csv"))
        got = {}
        for r in rows:
            got.setdefault(r[header.index("zAsset-zPK")],
                           set()).add(r[header.index("wal-diff-status")])
        self.assertEqual(got.get("800"), {"removed"})
        row = next(r for r in rows if r[header.index("zAsset-zPK")] == "800")
        self.assertEqual(row[header.index("zAsset-Filename")], "IMG_0800.PNG")
        # the recovered row carries the trash markers from the checkpointed
        # era (state 0 = the partially checkpointed main file)
        td_idx = next(i for i, h in enumerate(header)
                      if h.lower().startswith("zasset-trashed date"))
        self.assertIn("04:53:26", row[td_idx])
        self.assertEqual(sha(db + "-wal"), wal_before)

    def test_probe_sql_skips_missing_columns(self):
        # unit level: the ZASSET-only probe used on mixed-era middle states
        import json
        with io.open(os.path.join(ROOT, "catalog.json"),
                     encoding="utf-8") as fh:
            cat = json.load(fh)
        db = self.db("26")
        conn = px.open_readonly(db)
        b = px.QueryBuilder(cat, conn, px.Schema(conn), "basic")
        b.resolve_joins()
        sql = px.wal_probe_sql(b)
        self.assertIn("'zAsset-zPK'", sql)
        self.assertIn("'zAsset-Trashed Date'", sql)
        cur = conn.execute(sql)
        self.assertEqual(len(cur.fetchall()), synth.N_ASSETS)
        conn.close()
        # a schema without ZTRASHEDDATE drops that column from the probe
        db2 = os.path.join(self.tmp, "walprobe.sqlite")
        synth.build(db2, "26", drop_columns=[("ZASSET", "ZTRASHEDDATE")])
        conn2 = px.open_readonly(db2)
        b2 = px.QueryBuilder(cat, conn2, px.Schema(conn2), "basic")
        b2.resolve_joins()
        self.assertNotIn("'zAsset-Trashed Date'", px.wal_probe_sql(b2))
        conn2.close()


if __name__ == "__main__":
    unittest.main()
