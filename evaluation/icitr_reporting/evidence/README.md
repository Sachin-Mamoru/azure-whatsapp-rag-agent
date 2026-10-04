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
| 10 | Shareable archive | `python make_archive.py` → `dist/` (not committed) |

## Kinds of evidence, kept separate

| Kind | What it is | Where |
|---|---|---|
| Historical model run | The archived 29-message extraction run (model snapshot and prompt not recorded), re-scored offline | `evaluation/results/04_reporting_pipeline.json` (unchanged), `../annotation/rescore_*.json` |
| New live inference | **None completed.** The dev smoke run failed on every call (`insufficient_quota`); it is kept, not hidden | `../runs/20261004T084723Z_dev/` |
| Deterministic tests | 55 unit/regression tests; probes of the audited code; aggregation and policy analysis; bench 05 re-run | `tests/`, `../runs/20261004T085607Z_offline/` |
| Simulation | None. Ablation D (contributor weights) was not run, and no simulation was substituted | — |
| Proposed experiments | Frozen image evaluation; blinded text and image annotation | `../FREEZE_test_split.json`, `REPRODUCE.md` |

## Actions needed from the repository owner

1. **Add OpenAI credit.** The API returns `429 insufficient_quota` (credit
   balance exhausted). This blocks the live image run, and the production bot,
   which uses the same key and cannot answer messages either. Estimated cost for dev plus test: under
   $1 at the recorded gpt-4o-mini prices; the runner enforces a $5 cap. Then run
   the two "Live evaluation" commands in `REPRODUCE.md`.
2. **Recruit two annotators for each blinded task** (they may be the same two
   people).
   - Text: send `annotation/blinded_review/reviewer_A.csv` and
     `reviewer_B.csv` with `annotation/ANNOTATION_POLICY.md`.
   - Images: send `image_annotation/annotator_1.csv` and `annotator_2.csv`,
     with `image_annotation/IMAGE_ANNOTATION_GUIDE.md` and the
     `image_data/images/` folder.
   - Do not send manifests, key files or run outputs.
   - When they return, run `annotation_tools.py agreement` /
     `image-agreement`, adjudicate into `adjudicated_labels.csv` /
     `adjudicated_image_labels.csv`, and rerun `analyze_image_eval.py`.
3. **Ask a Sinhala and a Tamil speaker** to check the caption templates in
   `build_image_dataset.py` (`TEMPLATES`) before the test run if possible. Any
   change to them requires a new manifest and a new freeze record.
4. **Decide on the 6-photo pilot** in draft §5.5.1: supply its images and
   reference scores, or remove it (recommended in `PAPER_UPDATE.md`).
