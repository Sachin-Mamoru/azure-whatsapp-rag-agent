# AI-reviewed reference labels (not human annotation)

`ai_review_labels.csv` holds one review pass over all 181 image items by
Claude Sonnet 5.5 (an AI model), made on 2026-10-05, **before any live model
output existed** for this dataset.

## What this is and is not

- **Is:** a documented, reproducible reference that corrects the provisional
  Commons-category labels, which over-claim hazards (of 39 "flood" and 56
  "landslide" real images, 26 and 34 show that hazard).
- **Is not:** human annotation. There is one annotator, so there is no
  inter-annotator agreement. Two AI passes would not be independent either.
- **Not blind to construction.** The reviewer also wrote the dataset builder
  and knew the caption templates, so it could infer which captions were
  contradictions. It was blind to every model output, to the provisional
  labels, and to the manifest's caption-condition and class fields while
  labelling (it used only the blinded sheet: image plus caption).
- It never writes to `image_annotation/adjudicated_image_labels.csv`. The
  human pipeline stays pending, and `analyze_image_eval.py` does not read this
  file.
- Reference priorities and severity were not labelled, so review recall and
  workload are still not computed.

## Conventions used (single annotator, so applied consistently)

| Field | Rule |
|---|---|
| `hazard_visible` | yes = a hazard is clearly shown; unclear = ambiguous (e.g. standing water that may be irrigated paddy); no = none. |
| `image_category` | `unusable` for images too dark or too blurred to interpret. Satellite and rainfall maps, paintings and relief-camp interiors are `no_hazard` (satellite cyclone images: `other_hazard`, `hazard_visible=unclear`). |
| `evidence_tier` | 0 only for unusable images. A usable photo that does not support the caption, including a contradiction, is 0.05. Clear hazard with a matching or sparse caption 0.15; unmistakable, extensive 0.20; partial or ambiguous 0.10. |
| `caption_consistency` | high = photo shows what the caption says; moderate = sparse caption with a hazard photo, or partial match; low = sparse caption with no hazard, or an unrelated image; contradiction = caption names a different hazard, or a hazard where the photo shows none. |
| `faces_visible` | yes only for clearly recognisable people in close or medium shots. Used to exclude those photos from the shareable archive. |

Items that share one source photo (exact copies and re-encodings) received the
same labels; blurred and darkened derived copies were judged on what remains
visible (13 are `unusable`).

## Limits

Judgements are subjective, especially evidence tiers and `unclear` hazards.
Some images are ambiguous (e.g. P7606, P6147, P5034). Treat results against
this reference as an AI-referenced sensitivity analysis. Human adjudicated
labels replace it as soon as they exist.
