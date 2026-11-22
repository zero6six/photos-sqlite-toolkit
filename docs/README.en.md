# photos-sqlite-toolkit (English)

Forensic toolkit for the iOS photo library (`Photos.sqlite`): **export any iOS
version's photo database to CSV, then analyze it visually in an offline web
page**. Everything runs locally — no network requests, evidence files are
never modified. Suitable for on-site forensic use.

[中文文档（主文档）](../README.md)

## Why it exists

The community-standard way to analyze the iOS photo library is a set of
ready-made SQL queries (Scott Koenig's `iOS_Local_PL_Photos.sqlite_Queries`).
That collection ships one query per iOS version with hard-coded table and
column names — and Core Data join-table numbers drift across versions
(`Z_28ASSETS` → `Z_29` → `Z_30` → `Z_33`), so every query fails on iOS 26.

This toolkit rebuilds the idea as a **version-agnostic** pipeline: the schema
is probed at runtime, join tables are resolved by entity meaning from
`Z_PRIMARYKEY`, and missing tables/columns are pruned automatically — it
always produces the best CSV the database allows.

## Components

| Part | What it does |
|---|---|
| [`photos_sqlite_export/`](../photos_sqlite_export/README.md) | Export CLI. Pure Python stdlib; copy `photos_export.py` + `catalog.json` anywhere and run. Emits UTF-8-BOM CSV (opens directly in Excel) plus a schema-detection report |
| [`photos_viewer/`](../photos_viewer/README.md) | Viewer. A **single-file offline HTML** app (open via `file://`) built with Vue 3 — drag a CSV in for per-asset aggregation, semantic badges, filtering/sorting and dynamic custom columns |

```
Photos.sqlite ──► photos_export.py + catalog.json ──► CSV (UTF-8 BOM) ──► photos_viewer.html
                 (schema probe / pruning / filters)                       (local visual analysis)
```

## Quick start

### 1. Export (Python ≥ 3.8)

```bash
cd photos_sqlite_export

# No evidence handy? Walk the pipeline with the synthetic sample:
python photos_export.py samples/Photos_ios26_synthetic.sqlite -o samples_demo

# Real evidence (opened strictly read-only):
python photos_export.py Photos.sqlite -o out                # main CSV + report
python photos_export.py Photos.sqlite -o out --all-filters  # hidden/trashed/favorite/locations/adjusted/syndication

# A non-empty Photos.sqlite-wal next to the database switches the export into
# differential mode: every WAL commit is replayed, and assets that were
# added/modified/deleted - including ones created and deleted entirely inside
# the WAL - are flagged in a wal-diff-status column (--no-wal-diff disables it)
```

See the [sub-project README](../photos_sqlite_export/README.md) (Chinese) for
all options (`--profile very-basic`, `--where`, `--dump-sql`, …) and exit
codes.

### 2. View (no install needed)

```bash
# Option A: download photos_viewer.html from a Release (single offline file), open in a browser
# Option B: build it yourself
cd photos_viewer && npm install && npm run build   # produces dist/photos_viewer.html
```

Drag the CSV onto the page. Note: with the default `basic` profile one asset
may span multiple rows (album/internal-resource fan-out); the viewer folds
them back per asset by `zAsset-zPK`.

## Tests

```bash
cd photos_sqlite_export && python -m unittest discover -s tests   # 31 tests (10 synthetic iOS schemas + WAL replay)
cd photos_viewer && npm test                                      # 44 tests
```

## Known limits (honesty section)

- Schema support validated for iOS 11–26 (synthetic databases + one real
  iOS 26-structure library); **value-level differential testing was done on
  synthetic databases only**.
- The synthetic sample data under `photos_sqlite_export/samples/` is fully
  reproducible and contains no real device data.
- More details in the [sub-project README](../photos_sqlite_export/README.md).

## Credits & third-party sources

The query knowledge in this toolkit builds on the work of two forensic
community authors:

- **Scott Koenig** ([theforensicscooter.com](https://theforensicscooter.com))
  — original author of the photo-library SQL query collections
- **Alexis Brignoni** — [iLEAPP](https://github.com/abrignoni/iLEAPP) (MIT),
  where those queries are maintained up to current iOS versions

`catalog.json` is a derived data file with per-column provenance; full source
attribution, commit hashes and license status are documented in
[NOTICE.md](../NOTICE.md).

## License

Code and documentation in this project: [MIT](../LICENSE). `catalog.json`
contains third-party derived material — see [NOTICE.md](../NOTICE.md).

## Contributing

How to run tests, how to regenerate the catalog, and the semantic red lines
refactors must not break: see [CONTRIBUTING.md](../CONTRIBUTING.md).
