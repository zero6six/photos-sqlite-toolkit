# NOTICE

This project (**photos-sqlite-toolkit**) is licensed under the MIT License
(see [LICENSE](LICENSE)) for all code and documentation written by this
project's authors.

One data file is a **derived work** and incorporates third-party material:

## photos_sqlite_export/catalog.json

`catalog.json` is a merged, machine-readable catalog of SQL query columns and
JOIN definitions. It was built by `tools/build_catalog.py` from the following
two sources (both read as data only; no code was imported):

### 1. iOS_Local_PL_Photos.sqlite_Queries — by Scott Koenig

- Source: https://github.com/ScottKjr3347/iOS_Local_PL_Photos.sqlite_Queries
  (archived repository; commit `860ea4c` was used)
- Author site: https://theforensicscooter.com
- License: **no license file was present** in that repository at the time of
  use. The material is used here as reference material with full attribution,
  in the spirit of the forensic community it was shared in. The iOS 11–17
  Basic / Very-Basic query column sets originate from this work.

### 2. iLEAPP — iOS Logs, Events, And Plists Parser

- Source: https://github.com/abrignoni/iLEAPP (commit `e1aea33` was used when
  building the catalog)
- License: MIT — Copyright (c) 2020 Alexis Brignoni
- Specifically the artifact scripts `scripts/artifacts/Ph001BasicAssetData.py`
  and `scripts/artifacts/Ph002BasicAssetandAlbumData.py`, which carry the same
  photo-library queries as the repository above, maintained by the same author
  (Scott Koenig) up to iOS 26.

### Background article

- https://theforensicscooter.com/2024/05/18/ileapp-parsers-photos-sqlite-queries/

### Provenance transparency

`catalog.json` records per-column provenance: every column entry carries
`sources`, `first_source`, `newest_source` and version fields, so the origin
of each expression can be audited. The merge rule prefers the newest source's
expression and label (iLEAPP) whenever a logical column appears in both.

## photos_viewer

The Vue-based viewer contains no third-party code; its npm dependencies
(Vue, Vite, vitest, etc.) are MIT / ISC / Apache-2.0 licensed.

## WAL replay implementation note

The WAL replay in `photos_export.py` is an original implementation against
the public SQLite file format (https://www.sqlite.org/fileformat2.html#walformat).
No code was copied; the frame-layout handling was cross-checked against the
open-source **sqlite-forensic / sqlite4n6** project by SecurityRonin
(https://github.com/SecurityRonin/sqlite-forensic, Apache-2.0) while this
feature was developed. For residue beyond committed WAL history (rollback
journal, free blocks, uncommitted frames) that tool remains the specialist.

## Credits

- **Scott Koenig** (theforensicscooter.com) — the photo library SQL queries
  this toolkit is built upon, and their continued maintenance inside iLEAPP.
- **Alexis Brignoni** — iLEAPP (MIT), which preserved and extended those
  queries.
- **SecurityRonin** — sqlite4n6 / sqlite-forensic (Apache-2.0), whose WAL
  timeline model informed the replay design.

If you are the author of any material referenced here and have concerns about
how it is used, please open an issue in this repository.
