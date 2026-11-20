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
        # values come from the right pass
        names = {(r[header.index("zAsset-zPK")], r[header.index("zAsset-Filename")],
                  r[header.index("wal-diff-status")]) for r in rows}
        self.assertIn(("2", "WALMOD_2", "modified"), names)      # post state
        self.assertIn(("3", "IMG_0003.HEIC", "removed"), names)  # snapshot
        self.assertIn(("999", "ADDED_999.HEIC", "added"), names)
        # originals untouched: the diff stays repeatable
        self.assertEqual((sha(db), sha(db + "-wal")), (db_before, wal_before))
        # disposable work dir cleaned up
        self.assertFalse(os.path.exists(os.path.join(out, "_wal_work")))

    def test_report_records_wal(self):
        db = self.wal_db()
        size = os.path.getsize(db + "-wal")
        proc, out = run_tool(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with io.open(os.path.join(out, "export_report.txt"),
                     encoding="utf-8") as fh:
            report = fh.read()
        self.assertIn("wal: %d-byte sidecar" % size, report)
        self.assertIn("wal: checkpoint on copy", report)
        self.assertIn("wal diff: 3 unchanged, 1 added, 1 removed, 1 modified",
                      report)
        self.assertIn("wal: work copy removed", report)

    def test_keep_wal_work(self):
        db = self.wal_db()
        proc, out = run_tool(db, "--keep-wal-work")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        work = os.path.join(out, "_wal_work")
        self.assertTrue(os.path.exists(os.path.join(work, "wal26.sqlite")))
        # the copy was checkpointed: its wal is truncated to zero
        self.assertEqual(os.path.getsize(
            os.path.join(work, "wal26.sqlite-wal")), 0)
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


if __name__ == "__main__":
    unittest.main()
