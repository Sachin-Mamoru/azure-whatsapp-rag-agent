# ICITR evidence package: community reporting

Everything needed to update the community-reporting sections of the ICITR
manuscript, with each claim traceable to code, a test, a run or a source.

| # | Item | Location |
|---|---|---|
| 1 | Implementation change log, baseline and evaluated revisions | `CHANGELOG.md` |
| 2 | Reproduction commands and environment | `REPRODUCE.md`, `environment/pip_freeze.txt` |
| 3 | Regression-test results | `../runs/20261004T085607Z_offline/regression_tests.txt` |
| 4 | Dataset and annotation documentation, outstanding review items | `DATASETS.md`, `../annotation/`, `../image_annotation/` |
| 5 | Per-item predictions and run metadata | `../runs/*/items/`, `../runs/*/run_meta.json`, `../runs/*/analysis/per_item_predictions.jsonl` |
| 6 | Machine-readable metrics, tables, figures | `../annotation/rescore_*.json`, `../runs/20261004T085607Z_offline/{offline_evidence.json, 05_triangulation_bayesian.json, fig_*.png}`, tables in `PAPER_UPDATE.md` |
| 7 | Claim-to-evidence matrix | `CLAIMS_MATRIX.md` |
| 8 | Manuscript text | `PAPER_UPDATE.md` |
| 9 | Limitations | `LIMITATIONS.md` |
| 10 | Shareable archive | `python make_archive.py` → `dist/` (not committed). It contains the blinding keys, so never send it to annotators. |

## Kinds of evidence, kept separate

| Kind | What it is | Where |
|---|---|---|
| Historical model run | The archived 29-message extraction run (model snapshot and prompt not recorded), re-scored offline | `evaluation/results/04_reporting_pipeline.json` (unchanged), `../annotation/rescore_*.json` |
| New live inference | Frozen test split, 159 items, one model snapshot, $0.75 per run (primary run plus a labelled replication, $1.49 together); a dev smoke run (22 items); an earlier dev attempt that failed on every call (`insufficient_quota`) is kept, not hidden | `../runs/20261005T033433Z_test_live/` (primary), `../runs/20261005T040118Z_test_live_replicate/` (replication), `../runs/20261005T033020Z_dev_live/`, `../runs/20261004T084723Z_dev/` |
| Deterministic tests | 55 unit/regression tests; probes of the audited code; aggregation and policy analysis; bench 05 re-run | `tests/`, `../runs/20261004T085607Z_offline/` |
| Simulation | None. Ablation D (contributor weights) was not run, and no simulation was substituted | — |
| Proposed experiments | Frozen image evaluation; blinded text and image annotation | `../FREEZE_test_split.json`, `REPRODUCE.md` |

## Remaining owner actions

Everything else in this package is finished. What only the repository owner can do:

1. **Keep the new admin secret.** It was generated on 2026-10-05, is in the local
   `.env` as `ADMIN_SECRET` and in Azure as the `admin-secret` secret. Copy it into
   a password manager (`grep ^ADMIN_SECRET= .env`). `admin.html` asks for it and for
   a GitHub token once per device: tick "Remember on this device" and it keeps both
   for up to 30 days, so no typing after that. Only tick it on a device you trust.
2. **Confirm the old GitHub token is revoked.** The classic token that was embedded
   in the public admin page must be deleted under GitHub Settings, Developer
   settings, Personal access tokens. The page no longer embeds anything.
3. **Optional: delete the `ADMIN_PAT` repository secret.** Nothing reads it any
   more; the token is now pasted into the admin page when needed.

Not planned (owner decisions, 2026-10-05): human annotation of the text and image
sets, and a Redis replacement. The six-photo pilot was removed from the draft.
