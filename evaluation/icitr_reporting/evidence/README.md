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

## Actions needed from the repository owner

1. **Rotate the admin secret.** The live `ADMIN_SECRET` is the public default
   `admin_secret_change_me` (hardcoded in `early-warning-site/admin.html`).
   Put a new random `ADMIN_SECRET=` in the local `.env` and run `./deploy.sh`.
   The admin page then needs to ask for the secret instead of hardcoding it.
2. **Rotate the GitHub token.** The Pages build injects the `ADMIN_PAT`
   repository secret into the public admin page. Create a new fine-grained
   token limited to this repo (Contents read/write), replace the secret under
   Settings, Secrets and variables, Actions, and revoke the old token.
3. **Recruit two annotators for each blinded task** (they may be the same two
   people).
   - Text: `annotation/blinded_review/reviewer_A.csv` and `reviewer_B.csv` with
     `annotation/ANNOTATION_POLICY.md`.
   - Images: `image_annotation/annotator_1.csv` and `annotator_2.csv`, with
     `image_annotation/IMAGE_ANNOTATION_GUIDE.md` and the `image_data/images/`
     folder (fetch with `build_image_dataset.py --verify`).
   - Do not send manifests, key files, `ai_review/` or run outputs.
   - When they return, run `annotation_tools.py agreement` / `image-agreement`,
     adjudicate into `adjudicated_labels.csv` / `adjudicated_image_labels.csv`,
     and rerun `analyze_image_eval.py` on the test run to add human-referenced
     metrics.
4. **Ask a Sinhala and a Tamil speaker** to check the caption templates in
   `build_image_dataset.py` (`TEMPLATES`). Any change needs a new manifest, a new
   freeze record and a new live run.
5. **Decide on the six-photo pilot** in draft §5.5.1: supply its images and
   reference scores, or remove it (recommended in `PAPER_UPDATE.md`).
6. **Decide on Redis.** The configured Azure Redis no longer exists, so
   sessions and pending reports live in process memory.
