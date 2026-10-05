# Limitations

## A. Resolved (implemented and covered by regression tests)

Each item is a software-correctness fix, verified by a test that fails on the audited behaviour. None of them is evidence of better accuracy or safety in the field.

- Pending clarification state is kept for reports submitted through the agent tool; there are tests for cancellation, expiry, isolation between users, and no duplicate inference or storage on continuation.
- Storage is acknowledged only after commit; message-id deduplication holds under concurrent redelivery.
- Review is atomic and idempotent; wrong reviews are corrected by replay, not by an approximate inverse.
- The retention job no longer nests writers and no longer touches reliability.
- Corroboration aggregation is numerically stable up to (at least) 5,000 contributors.
- Vision failure, unusable, no-hazard and contradiction images contribute 0 and never backfill.
- Floating-point residue at decision thresholds is removed.
- Logged phone numbers in the webhook are masked.

## B. Changed but not validated

- **Visual policy `visual-v2`.** Measured once on 133 real photos against an AI-reviewed reference (not human): support given to non-supporting photos fell from 50.0% to 25.0%, with no loss on supporting photos. It is not validated against human labels, and it has limits found in the same run: the model never reported a contradiction, so that rule never fired; 24 of 96 non-supporting photos still add support; 13 of 15 blurred or darkened copies still add support; and the stricter backfill gate changed no decision (8 of 29 backfills are made where the reviewer sees no hazard).
- **Candidate decision policy `candidate-v2`.** It is monotone and never stores a high-severity report without review. Whether it is better is unknown. On the archived 29 predictions it moved 10 reports into expedited review (workload up), including e20, whose high severity comes from an exposure false positive. It runs in shadow mode only.
- **Low-consistency images** still add their 0.05 tier score. This follows the rubric but is a judgement call.
- **Location token selection** is an improvement over "first word" but has not been evaluated against real location strings.
- **Rainfall freshness (180 min, same local date)** is an engineering choice, not a calibrated value.
- **Keyed pseudonyms** are implemented and tested. The migration of legacy histories is tested on synthetic rows only.

## C. Remaining limitations

**Scores and models**
- Confidence and severity are additive heuristics with hand-set weights. They are not probabilities, and no calibration study has been done.
- Reliability is a bounded EMA of review outcomes and corroboration is product-of-odds aggregation. Neither is a Beta posterior or the TruthFinder algorithm.
- A single neutral corroborator adds 0.15 confidence just by existing.
- The extraction prompt counts "roads" as human exposure; the annotation policy does not. Exposure agreement partly measures this definitional mismatch.
- On the agent path, extraction runs on the agent's paraphrase of the user's message, not the raw text.
- The extraction model's location text is not geocoded. "Location presence" says nothing about whether the place is correct or locatable.
- After clarification, any reply is taken as the location, including a question or an unrelated message.
- Model snapshots for the archived 29-item run were not recorded.

**Independence and identity**
- Distinct accounts are not independent observers. One person with several numbers, or several people forwarding the same rumour or photo, are counted as separate corroborators.
- Only byte-identical photos are excluded; re-encoded, cropped or screenshotted copies are not detected.
- Location matching is substring matching on one token. Unrelated places that share a token can corroborate each other, and the same place spelled differently (e.g. "Kelaniya" vs "Kelani", English vs Sinhala script) does not.
- Keyed pseudonyms protect stored identifiers only if `REPORTER_ID_KEY` stays secret. If the key is lost, continuity of contributor histories is lost.

**Data and evaluation**
- Results against the AI-reviewed reference come from one AI annotator that was not blind to how the dataset was built and has no inter-annotator agreement. They are an interim sensitivity analysis, not a substitute for human labels.
- The vision model is not deterministic at temperature 0: the same image and prompt gave an invalid consistency value in one call and a valid one in another. Each reported number comes from the recorded run(s) only.
- A small share of vision replies violate the schema (2 of 22 on the dev split); they count as vision errors that add no support, and the images drop out of the category and tier metrics.
- No human annotation exists yet for the text policy review or the image set. Image reference labels are provisional (Commons category), constructed (template caption) or from the single AI review.
- Live results come from one frozen run (plus one labelled replication); the dev split was a smoke test and was not used to change any prompt or policy.
- Captions are templated; Sinhala and Tamil templates are machine-written and not native-speaker reviewed.
- Image coverage is limited by open licensing: flood test images come from two event groups, and Sri Lankan landslide images mostly from one event (Koslanda 2014).
- No contributor histories exist, so ablation D (uniform vs historical weights) was not run; no simulation was substituted.
- No independently labelled reference priorities exist, so severe-report review recall, false escalation and workload are not reported.
- Latency covers model calls from the evaluation client only. It excludes WhatsApp transport, media download and database writes.

**Operations**
- The production deployment stores `community_reports.db` in container `/tmp`, so reports, review events and reliability are lost on every restart or redeploy. Reliability histories and retention therefore have no practical continuity in the current deployment.
- The deployed `ADMIN_SECRET` equals the default placeholder `admin_secret_change_me`, which is hardcoded in `early-warning-site/admin.html` and therefore public in the repository and on the Pages site. Anyone can call the admin endpoints, including review, reject, alert sending and registration sync. Separately, the Pages workflow injects the `ADMIN_PAT` GitHub token into the same public page. Neither is fixed here; both need rotation (see the repository owner actions in README.md).
- The configured Azure Redis (`redis-whatsapp-15437`) no longer exists in the resource group, so conversation and pending-report state is held in process memory only. A restart or redeploy drops pending clarifications, and more than one replica would not share them.
- Outbound alert logging (`agent/alert_sender.py`) still prints full phone numbers; this is outside the community-reporting scope.
- A `ResourceWarning` (unclosed CSV handle) in `analyze_image_eval.py` was left in place to keep the frozen analysis file unchanged.
