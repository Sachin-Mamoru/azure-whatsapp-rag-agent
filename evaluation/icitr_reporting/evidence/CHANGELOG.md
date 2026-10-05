# Implementation change log: community reporting

## Revisions

| Role | Commit | Notes |
|---|---|---|
| Audited snapshot | `29f926fcd2eaa60d4979866f9504e19ecf228075` | Code identical to `0208dac`; the only difference is `early-warning-site/data.json`. |
| Pre-existing uncommitted work | `19c2eb4` | Greeting menu, reply-from-receiving-number, LLM-judged `location_specific`. Committed unchanged as the baseline for this work. Adds two fields to the extraction prompt, so the archived 29-item run (made before it) used a different prompt. |
| Reporting fixes | `d863ca7`, `8379d1e` | Described below. |
| Evaluation tooling | `cddd3cd`, `befea64`, `5d6f7b8`, `ed79bdb` | Annotation, image dataset, runner, analysis; AI-reviewed reference, throttled runner. |
| Frozen for the test split | `ed79bdb` (record in `d7f7fd6`) | `FREEZE_test_split.json`, superseding the `befea64` and `5d6f7b8` freezes; no test output existed at any of them. The live test runs used code at `d7f7fd6`. |
| Merged to `main` | `166771d` | Merge of the feature branch as of `d7f7fd6`; production runs the same runtime code (deployed from `cca45f5`). |

Archived datasets and results under `evaluation/datasets/` and `evaluation/results/` are unchanged (verified by hash before and after the offline re-runs).

## Audited behaviour confirmed by execution

These were reproduced by running the audited code (`runs/20261004T085607Z_offline/audited_*_probe.txt`):

1. Verifying the same report three times raised reliability 0.65 → 0.755 → 0.8285.
2. A vision-model failure produced an evidence score of 0.05 (positive support).
3. A failed database write still returned `stored: True` and a "Report received" acknowledgement, with zero rows stored.
4. The retention job archived an expired report but its reliability update failed with `database is locked` after about 5.4 s per report, because it opened a second writer while its own write transaction was open. The documented decay therefore never applied. The docstring also described a half-weight decay that the code did not implement.
5. With 1,100 contributors of reliability 0.5, the direct-product corroboration formula underflowed to 0 (`runs/.../offline_evidence.json`).

Found by code reading and covered by regression tests:

6. A report submitted through the agent tool that needed a location follow-up lost its pending state, because the tool returned only the reply text.
7. Contradictory, no-hazard and unusable images could add their evidence score and backfill hazard type and scale.
8. Baseline decision policy: a confidence of 0.39 with severity 1.0 is store-only, and raising confidence from just below 0.70 to 0.70 at severity 0.50 moves a report from review to monitoring (44 adjacent-step monotonicity violations on the evaluation grid).
9. Sums of decimal weights can land just below a threshold in binary floating point (0.15 + 0.20 + 0.05 = 0.39999999999999997, so store-only instead of review).
10. The corroboration location token was the first word longer than two characters, so "near Kandy" grouped with "near Galle".
11. The unkeyed 16-hex SHA-256 pseudonym of a phone number can be reversed by enumerating the number space; webhook logs printed full recipient numbers.

## Changes and their behavioural effects

Each item lists what changed for a report, not only for the code.

**Model output (`agent/reporter.py`)**
- Text and vision replies are parsed and validated against explicit schemas (`TEXT_SCHEMA`, `IMAGE_SCHEMA`): enums, booleans, numeric bounds and missing fields. Invalid fields take defaults and are listed in provenance. *Effect:* a non-boolean `people_at_risk` (e.g. `1`) no longer counts as exposure.
- Extraction failures (timeout 30 s, API error, malformed or non-object JSON) fall back to the keyword extractor, as before, but the reason is recorded.
- Vision returns an explicit `status`: `ok`, `unsupported` (empty, over 10 MB, or not JPEG/PNG/WebP/GIF by magic bytes; no model call) or `error` (timeout 45 s, API error, malformed JSON, invalid core field). *Effect:* failure contributes 0, not 0.05.

**Visual evidence policy `visual-v2`**
- Outcomes are `unavailable`, `unusable` (score 0), `no_hazard`, `contradiction` or `supporting`. Only `supporting` adds its evidence tier to confidence. *Effect:* contradiction and no-hazard images add nothing.
- Hazard type and scale are backfilled only when the text left them unknown and the image is supporting with high or moderate consistency. Text-derived values are never overwritten, and every accept/reject decision is recorded with a reason.
- A supporting image with low consistency still adds its tier score (0.05 under the rubric) but cannot backfill.

**Clarification (`agent/agent_tools.py`, `agent/disaster_agent.py`, `agent/orchestrator.py`)**
- The agent tool passes the full reporter result to the orchestrator, which stores a pending report in the session.
- A pending report expires after 60 min (`PENDING_REPORT_TTL_MINUTES`), and `cancel` / `අවලංගු` / `ரத்து` discards it.
- An empty answer keeps it pending.
- A second photo during clarification is not sent to the vision model.
- A WhatsApp redelivery of a stored message is ignored.

**Persistence**
- Report insert, status log and contributor report count are one transaction, and the user is acknowledged only after commit. *Effect:* on failure the user is asked to resend.
- A unique index on the WhatsApp message id prevents duplicate storage, including concurrent redeliveries.

**Human review**
- Review decision, review event, status change and reliability recomputation are one transaction (`review_report`). Repeating the current decision is a no-op.
- `reject` means "verified false report". A new `/retract` endpoint withdraws a decision.
- Reliability is replayed from the effective review decisions (latest per report, retractions excluded) in order of their recording, starting from `replay_base`, which preserves any pre-existing score. *Effect:* correcting a wrong review gives the same reliability as if it had never happened.

**Retention (`apply_retention`, called by the scheduler)**
- One write transaction, with no nested writers.
- Unreviewed expiry archives (or, for unknown-domain reports with confidence < 0.40, deletes) without changing reliability, and keeps `review_outcome` NULL. Reports reviewed false keep `closed`/`false`.
- Photos older than 30 days (`IMAGE_RETENTION_DAYS`) are deleted for all reports. Unreferenced photos older than twice the pending TTL are deleted.

**Aggregation and context**
- Corroboration is `sigmoid(sum(logit(clip(r))))`, equal to the product-of-odds formula on ordinary inputs (max difference 1.1e-16 on the tested cases) and stable for large sets.
- Self-exclusion and per-contributor deduplication are kept. Reports with a byte-identical photo are excluded.
- The location token prefers a known district/locality name and skips positional words.
- The rainfall bonus uses a cached Open-Meteo **forecast** for the district centroid. It applies only if fetched within 180 min and dated today in Asia/Colombo, and is recorded as forecast, not site measurement.

**Decision policy**
- Scores are quantised to 1e-6 before thresholds.
- `baseline-v1` is unchanged and is the active policy. `candidate-v2` (priority: escalate > expedited_review > flag_review > monitor > store_only) is computed for every report and stored as `shadow_action`.
- `ACTIVE_DECISION_POLICY=candidate-v2` would make it drive actions; this is not enabled.

**Provenance and privacy**
- Each report stores `scoring_provenance` (JSON): full-precision components, policy versions and both actions, prompt digests, model alias and per-call snapshot, extraction status and issues, validated visual fields and outcome, backfill decisions, rainfall context with timestamps, and corroborating contributor pseudonyms, reliabilities and report ids.
- With `REPORTER_ID_KEY` set, pseudonyms are `k1_` + HMAC-SHA-256. Legacy rows are re-keyed the first time each contributor is seen.
- Webhook logs mask recipient numbers.

## Operations changes after the audit (2026-10-05)

- Deployed the reporting fixes to production (revision `whatsapp-agent--0000032`, built from `cca45f5`).
- Rotated the bot admin secret and stored it as an Azure secret (revision `--0000033`); `deploy.sh` now refuses a missing or placeholder `ADMIN_SECRET`.
- `admin.html`: secrets typed in and kept in session storage, Content-Security-Policy, HTML escaping of report text, 401 shown as failure; `pages.yml` no longer injects `ADMIN_PAT`. Verified in a browser test with mocked network (no secret in the source, no requests before sign-in, injected markup rendered as text, other origins blocked) and on the live page.

## Not changed

- The extraction and vision prompts, as of `19c2eb4`.
- The confidence and severity weights, the baseline policy, the reliability update rule and the retention ages.
