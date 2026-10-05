# Reproduction

All commands run from the repository root with Python 3.11.16 and the packages in
`environment/pip_freeze.txt` (key versions: langchain 0.2.14, langchain-openai
0.1.20, openai 1.109.1, fastapi 0.115.0, Pillow 12.3.0, matplotlib 3.11.2).
`pytest` is not required; tests use the standard library.

## Deterministic (no API key, no network)

```bash
python -m unittest discover -s tests -v                                  # 55 regression tests
python evaluation/icitr_reporting/annotation_tools.py rescore --labels original
python evaluation/icitr_reporting/annotation_tools.py rescore --labels proposed
python evaluation/icitr_reporting/annotation_tools.py discrepancy
OUT=evaluation/icitr_reporting/runs/$(date -u +%Y%m%dT%H%M%SZ)_offline
python evaluation/icitr_reporting/offline_evidence.py --out $OUT
EVAL_RESULTS_DIR=$OUT python evaluation/bench_05_triangulation_bayesian.py
python evaluation/icitr_reporting/evidence_figures.py --run-dir $OUT
```

`EVAL_RESULTS_DIR` keeps the archived `evaluation/results/` files unchanged.

## Image dataset

```bash
python evaluation/icitr_reporting/build_image_dataset.py --verify   # fetches images, checks SHA-256 against manifest
```

Rebuilding from Commons (`build_image_dataset.py --refresh`) re-queries live
categories and will not reproduce the committed manifest exactly; use `--verify`.

## Live evaluation (needs OpenAI credit; cap enforced by the runner)

```bash
RUN=evaluation/icitr_reporting/runs/$(date -u +%Y%m%dT%H%M%SZ)_dev
python evaluation/icitr_reporting/run_image_eval.py --split dev --run-dir $RUN --max-cost-usd 2 \
    --concurrency 1 --min-interval-s 10          # 10 s keeps a 200k tokens/minute account under its limit
python evaluation/icitr_reporting/analyze_image_eval.py --run-dir $RUN
python evaluation/icitr_reporting/analyze_ai_reference.py --run-dir $RUN

RUN=evaluation/icitr_reporting/runs/$(date -u +%Y%m%dT%H%M%SZ)_test
python evaluation/icitr_reporting/run_image_eval.py --split test --run-dir $RUN --max-cost-usd 2 \
    --concurrency 1 --min-interval-s 10 --frozen evaluation/icitr_reporting/FREEZE_test_split.json
python evaluation/icitr_reporting/analyze_image_eval.py --run-dir $RUN
python evaluation/icitr_reporting/analyze_ai_reference.py --run-dir $RUN
# repeatability of two runs with identical frozen code:
python evaluation/icitr_reporting/compare_runs.py --run-a <run A> --run-b <run B> --out compare.json
```

The test-split command refuses to run if any frozen file differs from commit
`d7f7fd6` (the freeze record names its own commit). `--redo-failed` moves items
that ended in an API error aside to `failed_attempts/` and runs them again. Re-running the same `--run-dir` resumes. Each run directory records
the source commit, working-tree status and diff digest, `pip freeze`, model
alias, per-call model snapshot, prompts and their digests, timeouts, pricing
assumption, manifest hash and the exact command.

## Human annotation

```bash
python evaluation/icitr_reporting/annotation_tools.py agreement         # after reviewer_A/B.csv are filled
python evaluation/icitr_reporting/annotation_tools.py rescore --labels adjudicated
python evaluation/icitr_reporting/annotation_tools.py image-agreement   # after annotator_1/2.csv are filled
python evaluation/icitr_reporting/analyze_image_eval.py --run-dir <test run>   # adds human_reference metrics
```

## Archive

```bash
python evaluation/icitr_reporting/evidence/make_archive.py
```
