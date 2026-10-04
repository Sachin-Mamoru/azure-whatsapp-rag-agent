# Claim-to-evidence matrix (community reporting, ICITR)

**Status key**
- **S**: supported by completed work.
- **S\***: supported, with the stated caveat.
- **P**: pending (protocol ready; needs data, labels or credit).
- **X**: not supported; remove or rephrase.

**Evidence paths**
- `T` = `tests/test_reporting.py`
- `R` = `evaluation/icitr_reporting/runs/20261004T085607Z_offline/`
- `A` = `evaluation/icitr_reporting/annotation/`

## Claims proposed for the manuscript

| # | Claim | St. | Evidence |
|---|---|---|---|
| 1 | Reports are extracted by an LLM into a fixed schema; every field is validated (enums, booleans, numeric bounds, missing fields) and invalid output falls back to a keyword extractor with the reason recorded. | S | `agent/reporter.py` `TEXT_SCHEMA`, `validate_against_schema`, `_extract_report`; `T` `TestModelOutputValidation`, `test_malformed_text_reply_uses_keyword_fallback` |
| 2 | A failed, unsupported, unusable, no-hazard or contradictory photo adds no confidence and supplies no hazard fields. | S | `apply_visual_policy`, `classify_visual_outcome`; `T` `TestVisualPolicy`, `TestImageAnalysis`, `test_vision_failure_contributes_nothing`; truth table in `R/offline_evidence.json` |
| 3 | In the audited implementation, a vision-model failure added 0.05 evidence. | S | `R/audited_behaviour_probe.txt` (b) |
| 4 | Photo-derived backfill of hazard type/scale happens only when the text left them unknown and the photo is supporting with high/moderate consistency; each decision is recorded. | S | `apply_visual_policy`; `T` `test_supporting_image_backfills_only_unknown_text_fields`, `test_low_consistency_scores_but_does_not_backfill`; `scoring_provenance.visual.backfill` |
| 5 | A report missing a location is held and completed by the user's next message, on both the direct and agent-tool paths, without re-running extraction or vision; cancel, expiry (60 min) and per-user isolation are enforced. | S | `agent/orchestrator.py`, `agent/agent_tools.py`; `T` `TestClarificationFlow` (7 tests) |
| 6 | In the audited implementation, the agent-tool path discarded the pending report. | S\* | Code reading of `29f926f` `agent_tools.py`/`orchestrator.py` (tool returned only text); not executed against the audited code |
| 7 | A report is acknowledged as stored only after a committed transaction; WhatsApp redeliveries, including concurrent ones, are stored once. | S | `_store_report`, unique index `uq_reports_source_message`; `T` `test_storage_failure_is_not_acknowledged_and_writes_nothing`, `test_duplicate_message_id_*`, `test_concurrent_redelivery_*`, `test_webhook_redelivery_is_ignored` |
| 8 | In the audited implementation, a failed write was still acknowledged as stored. | S | `R/audited_behaviour_probe.txt` (c) |
| 9 | Contributor reputation is a bounded exponential moving average r ← round₄(clip(0.7r + 0.3y, 0.05, 0.95)) of human review outcomes. | S | `reliability_update`; `T` `test_reliability_update_is_bounded_ema` |
| 10 | Review state, review event and reputation update are atomic and idempotent; corrections and retractions are applied by replaying effective decisions, so a corrected review leaves no trace in the score. | S | `review_report`, `_replay_reliability`; `T` `TestReview` (6 tests) |
| 11 | In the audited implementation, repeating a verification raised reputation each time (0.65 → 0.755 → 0.8285). | S | `R/audited_behaviour_probe.txt` (a) |
| 12 | Unreviewed expiry does not change reputation and is distinguishable from a report reviewed as false. | S | `apply_retention`; `T` `test_unreviewed_expiry_archives_without_touching_reliability` |
| 13 | In the audited implementation, the retention job's reputation update failed with "database is locked" (~5.4 s per report), so the documented decay never applied. | S | `R/audited_retention_probe.txt` |
| 14 | Corroboration combines other contributors' reputations by product-of-odds aggregation, computed in log-odds form; equal to the direct product on ordinary inputs (max diff 1.1×10⁻¹⁶) and stable for large sets (1,100 neutral contributors: 0.5, where the direct product gives 0). | S | `aggregate_reliabilities`; `R/offline_evidence.json`; `R/fig_aggregation_stability.png`; `T` `TestAggregation` |
| 15 | Corroboration excludes the submitter, counts each other contributor once and excludes reports carrying a byte-identical photo. | S | `_corroboration_details`; `T` `TestCorroboration` |
| 16 | Corroboration indicates independent observation. | X | Distinct pseudonyms are not independent observers (LIMITATIONS C) |
| 17 | Confidence, corroboration or reputation are probabilities / Bayesian posteriors / TruthFinder. | X | No calibration study; formulas are heuristic (LIMITATIONS C) |
| 18 | Weather context is a same-day district-centroid precipitation *forecast*, used only if fetched within 180 min. | S | `_rainfall_context`, `_get_rainfall_bonus_sync`; `T` `TestRainfallContext` |
| 19 | The baseline decision policy is non-monotone (44 adjacent-step violations on the evaluation grid) and stores high-severity, low-confidence reports without review; the candidate policy is monotone (0 violations) and routes such reports to expedited review. | S | `decide_action_*`; `R/offline_evidence.json`; `R/fig_policy_action_maps.png`; `T` `TestDecisionPolicies` |
| 20 | The candidate policy improves safety or triage quality. | X | Not measured; shadow mode only; on the archived 29 predictions it moved 10 reports to expedited review (`R/offline_evidence.json`) |
| 21 | Every stored report carries enough provenance to recompute its scores and action. | S | `scoring_provenance`; `T` `test_stored_report_carries_replayable_provenance` |
| 22 | Contributor identifiers are keyed HMAC pseudonyms; existing histories migrate on first contact. | S\* | `_hash_phone`, `_resolve_user_hash`; `T` `TestPrivacy`. Requires `REPORTER_ID_KEY` in deployment |
| 23 | On the archived 29-message set, field agreement with the original labels was domain 23/29, hazard type 23/29, exposure 20/29, ongoing 27/29, all five 14/29; location text was present for 29/29. | S | `A/rescore_original.json`, `annotation_tools.py rescore`; archived `evaluation/results/04_reporting_pipeline.json` |
| 24 | Exposure disagreements are mostly false positives (9 FP, 0 FN), and 5 of the 9 involve road-only mentions that the extraction prompt defines as exposure. | S | `A/discrepancy_report.csv` |
| 25 | Agreement against adjudicated labels. | P | Blinded packet in `A/blinded_review/`; not reviewed |
| 26 | The 29-message set measures location *accuracy*. | X | It measures presence only |
| 27 | Image evaluation: false support, missed support, backfill correctness, visual category accuracy, latency and cost of visual-v2 vs legacy on 133 real test images. | P | Frozen protocol `FREEZE_test_split.json`; runner and analysis ready; blocked by OpenAI quota (`runs/20261004T084723Z_dev`) |
| 28 | Image metrics against human labels; evidence-tier error; severe-report review recall/workload. | P | `image_annotation/`; pre-registered in `analyze_image_eval.human_reference` |
| 29 | The 6-image photographic-evidence pilot (draft §5.5.1, Table 6a). | X | No images, reference scores or outputs exist in the repository; cannot be reproduced |
| 30 | Triangulation matches its closed-form reference with max error 1.6×10⁻⁴ (draft §5.6). | S\* | Re-run `R/05_triangulation_bayesian.json`: max error 0.0 after the change. The earlier 1.6×10⁻⁴ came from rounding the score to four decimals |
| 31 | The system "decays reporter reliability" for stale reports (draft §1). | X | Never executed in the audited code (claim 13); removed by design (claim 12) |
| 32 | Same-user exclusion gives Sybil resistance (draft §3.5, §5.6). | X | Only self-exclusion; multiple accounts are not detected |
| 33 | Regression suite: 55 tests pass on the evaluated revision. | S | `R/regression_tests.txt` |
