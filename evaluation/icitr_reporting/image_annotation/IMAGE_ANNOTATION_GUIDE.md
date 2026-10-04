# Image annotation guide (image-report evaluation)

You will label 181 items. Each row shows one photo (`image_file`, relative to
`evaluation/icitr_reporting/image_data/`) and the text a person sent with it
(`caption_text`, in English, Sinhala or Tamil). Work alone; do not look at
`manifest.jsonl`, `KEY_DO_NOT_SHARE.csv`, any run output or the other
annotator's sheet. Some photos repeat or are blurred or dark on purpose; label
each row on what you see. Use only the values listed. Put doubts in `notes`.

| Column | Values | Question |
|---|---|---|
| `hazard_visible` | yes / no / unclear | Is a flood, landslide, slope failure, ground crack, drainage failure or road obstruction visible? |
| `image_category` | flooding / slope_failure_or_cracking / drainage_problem / road_obstruction / other_hazard / no_hazard / unusable | The main thing the photo shows. `unusable` = too dark, blurred or small to tell. |
| `evidence_tier` | 0 / 0.05 / 0.10 / 0.15 / 0.20 | How strongly the photo supports what the caption reports. 0 = unusable or no support; 0.05 = visible but does not clearly support; 0.10 = partly consistent; 0.15 = clearly consistent; 0.20 = strong, direct support. For a caption that only says "look at this photo", judge support for the hazard the photo shows. |
| `caption_consistency` | high / moderate / low / contradiction | Does the photo agree with the caption? `contradiction` = the caption describes a different hazard, or a hazard where the photo shows none. |
| `severity` | none / low / moderate / high | How serious the visible situation looks. |
| `reference_priority` | urgent_review / routine_review / monitor_only / no_action | How a disaster-management officer receiving this report should treat it, judged from photo and caption together. `urgent_review` = people or homes appear in danger now. |

Adjudication: an adjudicator resolves every disagreement listed by
`annotation_tools.py image-agreement` and writes one row per `item_id` in
`adjudicated_image_labels.csv` (map codes to item ids with the key file), with
their name in `adjudicator`.
