# Datasets, annotation and outstanding review items

## 1. Archived text set (29 reports)

- **Source:** `evaluation/datasets/report_extraction_testset.json` (unchanged). 29 messages written for the earlier benchmark: 21 English, 4 Sinhala, 4 Tamil.
- **Labels:** five fields, hand-written by the original author with no written policy.
- **Predictions:** `evaluation/results/04_reporting_pipeline.json` (unchanged). That file does not record the model snapshot or the prompt.
- **Prompt:** the prompt at the time (commit `07461cf`) lacked the `location_specific` and `clarification_question` fields that were added later.

**Independent re-score** (`annotation_tools.py rescore`, from the stored per-item predictions and labels; Wilson 95% CIs):

| Field | Original labels | Proposed labels (sensitivity only) |
|---|---|---|
| report_domain | 23/29 (0.62–0.90) | 23/29 |
| hazard_type | 23/29 (0.62–0.90) | 23/29 |
| location presence | 29/29 (0.88–1.00) | 29/29 |
| people_at_risk | 20/29 (0.51–0.83) | 20/29 |
| ongoing | 27/29 (0.78–0.98) | 27/29 |
| all five | 14/29 (0.31–0.66) | 13/29 (0.28–0.62) |
| exposure TP/TN/FP/FN | 10/10/9/0 | 11/9/8/1 |

This reproduces the audit's figures exactly. Location presence means "some location text was extracted", not geolocation accuracy. The proposed column is a sensitivity analysis on the same 29 items: the labels are not human-reviewed and the items are not a held-out set.

**Annotation policy:** `annotation/ANNOTATION_POLICY.md` (v1) separates human exposure (E1–E3), infrastructure impact, and ongoing process versus persisting damage (O1–O2). It also names a prompt–label conflict: the extraction prompt counts "roads" as exposure, while the policy does not.

**Discrepancy report:** `annotation/discrepancy_report.{csv,md}` has 25 rows, one for every field where the archived prediction differs from the original label plus every proposal.
- 6 rows propose a change: e06 and e22 `people_at_risk` false→true; e04 and e10 `ongoing` true→false; e04 and e15 `hazard_type` erosion→unknown.
- 19 rows retain the original label, each with a cited rule.
- 5 exposure disagreements (e08, e18, e25, e26, e28) trace to the prompt's "roads" definition.
- Several proposals move *away* from the model's predictions (e22, e10, and e04/e15 to `unknown`), and the all-five score falls. The proposals were not chosen to match the model.

**Blinded review workflow:** `annotation/blinded_review/`.
- Two reviewer sheets carry message text only, under random codes and in different orders. They show no original labels, predictions or discrepancy flags.
- `KEY_DO_NOT_SHARE.csv` maps codes to items.
- After review, `annotation_tools.py agreement` reports raw agreement and Cohen's kappa. `adjudicated_labels.csv` takes the adjudicated labels, and `rescore --labels adjudicated` scores them separately from the original-label result.
- **Status: not started.** No human review has been done.

## 2. Image-report set (181 items)

**Source and licences**
- `image_data/manifest.jsonl` holds 155 real photographs from fixed Wikimedia Commons categories (listed in `build_image_dataset.py`).
- Licences were filtered to CC BY / CC BY-SA / CC0 / public domain: 66 CC BY-SA 4.0, 36 CC BY 2.0, 17 CC BY-SA 3.0, 15 PD, 10 CC BY 3.0 and others.
- Each item records the Commons title, page URL, author, licence and URL, uploader, categories, and the SHA-256 of the 1024-px rendition used.

**Construction**
- **Captions** are constructed from fixed templates in English (59), Sinhala (62) and Tamil (60). They are not real community messages, and the Sinhala/Tamil text has not been reviewed by native speakers.
- **Caption conditions:**
  - hazard images: matching, sparse ("please look at this photo. <place>."), or contradiction (the other hazard claimed);
  - no-hazard images: hazard claim or sparse.
- **Provisional image labels** come from the Commons source category: flood, landslide (incl. mudslides, rockfalls) or none (roads, rivers, tea, paddy and storm drains in Sri Lanka; storm drains generic). They are not human annotations, and some category members will not show the category's hazard.
- **Derived controls** (26, synthetic transformations of real test images):
  - 15 degraded copies: Gaussian blur r=12, brightness ×0.08, or 40-px downscale;
  - 8 byte-identical duplicates;
  - 3 JPEG-q25 re-encodings.

**Splits**
- 22 dev and 159 test items, split by whole event group (17 groups).
- Dev is used only for runner smoke tests; prompts and policies were frozen before any test call.
- Two uploaders appear in both splits; with no tuning on dev this is not leakage.
- Duplicates and degraded copies stay in their source's split.
- Real test items: 133, of which 80 are Sri Lankan events. Flood test images come from only two event groups.

**Sample size.** The set is bounded by openly licensed Sri Lankan hazard photos on Commons (about 20 usable Sri Lankan flood photos), not chosen for adequacy. Expected 95% Wilson half-widths on the test split:

| Stratum | n | event groups | ±, p = 0.1 | ±, p = 0.5 |
|---|---|---|---|---|
| Non-supporting (false-support denominator) | 80 | 11 | 0.07 | 0.11 |
| … contradiction (hazard image, other hazard claimed) | 20 | 6 | 0.14 | 0.20 |
| … no-hazard image | 60 | 5 | 0.08 | 0.12 |
| Expected-support (missed-support denominator) | 53 | 6 | 0.08 | 0.13 |
| Sparse caption with hazard image (backfill) | 27 | 6 | 0.12 | 0.18 |
| Flood images | 23 | 2 | 0.12 | 0.19 |
| Landslide images | 50 | 4 | 0.09 | 0.13 |
| Per caption language | 43–45 | 11 | 0.09 | 0.14 |

The primary outcome (false support on non-supporting images, 80 items) can separate rates about 0.15 apart. Per-language and flood-specific estimates are too wide for strong claims, and cluster-bootstrap intervals with two to six event groups are unstable.

**Image annotation:** `image_annotation/IMAGE_ANNOTATION_GUIDE.md`.
- Two blinded sheets (`annotator_1.csv`, `annotator_2.csv`) cover 181 items in different random orders: image file and caption only, with no provisional labels or model output.
- `annotation_tools.py image-agreement` reports kappa.
- `adjudicated_image_labels.csv` takes the final labels. `analyze_image_eval.py` uses them automatically (pre-registered in the frozen analysis).
- **Status: not started.**

## 3. Outstanding review items

| Item | Owner | Blocks |
|---|---|---|
| Blinded review of the 29 text items (two reviewers + adjudication) | human annotators | adjudicated re-score; any revised-label claim |
| Blinded annotation of the 181 image items (two annotators + adjudication) | human annotators | all human-reference image metrics, evidence-tier error, severe-report review recall |
| Native-speaker check of the Sinhala/Tamil caption templates | Sinhala and Tamil speakers | language-specific claims |
| OpenAI credit for the live run (estimated < $1 at the recorded prices; cap $5) | repository owner | all live image results |
