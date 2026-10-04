# Annotation policy: community report text fields

Version: annotation-policy-v1 (2026-10-04). Status: **proposed; not yet applied by
human annotators.** Applies to `evaluation/datasets/report_extraction_testset.json`
and to any new report-text test set.

The archived labels were written before this policy existed. Where they conflict
with it, the conflict is listed in `discrepancy_report.csv`; the original labels
are never edited.

## Rule set

Each rule has an identifier that the discrepancy report cites.

### Domain (`report_domain`)

- **D1 hazard.** A natural hazard process is occurring or showing precursor signs:
  flooding, rising or overflowing water, slope movement, falling rock, ground or
  wall cracking, leaning poles or trees on a slope. Precursor signs count as
  `hazard/landslide` even when the visible object is a wall or pole (the same
  signs are in `LANDSLIDE_INDICATORS` in `agent/reporter.py`).
- **D2 infrastructure.** Damage to, failure of, or blockage of built
  infrastructure (drain, culvert, retaining wall, road, bridge) without a named
  hazard process in progress.
- **D3 regulatory.** Human activity that may breach land-use or building rules
  or create a hazard: excavation, slope cutting, construction on slopes or
  riverbanks, filling drains or wetlands.
- **D4 safety.** A danger to people not covered by D1–D3 (for example a fallen
  live wire). Not used for D3 activities.
- **D5 unknown.** The message names no specific observation, even if it uses the
  word "hazard".

### Hazard type (`hazard_type`)

- **H1** Label the natural process the message states or unambiguously implies:
  `landslide`, `flood`, `erosion`, `drainage` (drain or culvert blockage or
  failure), `mixed` (two processes named).
- **H2** Infrastructure damage whose cause is not stated is `unknown`. Do not
  infer erosion, flooding or scour from "after the rain" alone.
- **H3** D3 regulatory reports are `unknown` unless a hazard process is already
  occurring.

### Human exposure (`people_at_risk`)

- **E1 true** when people, or occupied buildings or facilities (homes, schools,
  hospitals, vehicles with occupants), are described as in, at, or directly
  threatened by the hazard area. "Our wall", "next to our house" and "near the
  school" count.
- **E2 false** when only roads, land or unoccupied infrastructure are affected.
  A blocked or flooded road is infrastructure impact (`infrastructure_damage`),
  not human exposure, unless people or traffic are said to be endangered.
- **E3 false** when the reporter explicitly states there is no danger to people
  ("no immediate danger", "no one hurt").

Known conflict: the production extraction prompt defines `people_at_risk` as
"mentions people, houses, schools, **roads**". Under E2, road mentions alone are
not exposure. This is a construct-validity mismatch between prompt and label;
agreement on this field partly measures the prompt definition, not model error.

### Status (`ongoing`)

- **O1 true** when the hazard process or the reported activity is active or
  evolving at the time of the report (water rising or overflowing, ground moving,
  rocks falling, a crack widening, digging in progress), stated or implied in
  the present tense.
- **O2 false** for completed events whose damage persists ("has collapsed",
  "washed away", "collapsed yesterday") and for static conditions with no active
  process ("blocked for days, no immediate danger").

### Location presence (`has_location`)

- **L1** true when the message names a navigable place (village, town, road,
  landmark). "Near my area" or "near our street" alone is false. This field
  records presence only. It is **not** geolocation accuracy, and no score on it
  may be reported as such.

## Blinded review procedure

1. Two annotators independently label all 29 items with this policy, using
   `blinded_review/reviewer_A.csv` and `reviewer_B.csv`. These files contain
   the message text only, in different random orders under random item codes.
   They contain no original labels, model predictions, or discrepancy flags.
2. Annotators do not confer and do not see `blinded_review/KEY_DO_NOT_SHARE.csv`.
3. Run `python evaluation/icitr_reporting/annotation_tools.py agreement` to
   compute per-field agreement and Cohen's kappa and to list disagreements.
4. An adjudicator (who may be one of the annotators, recorded as such) resolves
   each disagreement in `adjudicated_labels.csv` with a rule identifier.
5. Run `annotation_tools.py rescore --labels adjudicated` to score the archived
   predictions against adjudicated labels. Report this **separately** from the
   score against original labels. Re-labelled examples are the same 29 items, so
   they are not a new held-out benchmark.
