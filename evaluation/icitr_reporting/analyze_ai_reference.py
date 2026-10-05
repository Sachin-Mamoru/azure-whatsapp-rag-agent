"""
Compare a run's model outputs with the AI-reviewed reference labels.

  python evaluation/icitr_reporting/analyze_ai_reference.py --run-dir <dir>

Reference = ai_review/ai_review_labels.csv: ONE AI annotator (Claude Sonnet 5.5),
single pass, made before any live model output existed. It is NOT human
annotation, there is no inter-annotator agreement, and the annotator was not
blind to how the dataset was built. Results are labelled accordingly and sit
beside, never in place of, the human-reference metrics in analyze_image_eval.py.

Writes <dir>/analysis/ai_reference_metrics.json and ai_reference_tables.md.
"""
import argparse
import csv
import json
import os
import statistics
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import analyze_image_eval as A  # noqa: E402
from stats_utils import macro_f1, proportion, write_json  # noqa: E402

LABELS = os.path.join(HERE, "ai_review", "ai_review_labels.csv")
COARSE = {"flooding": "flood", "slope_failure_or_cracking": "landslide", "no_hazard": "none", "unusable": "none",
          "drainage_problem": "other", "road_obstruction": "other", "other_hazard": "other"}
CONTRADICTION = "contradiction"


def load_labels(path=LABELS):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    return {r["item_id"]: r for r in rows}


def metrics(rows, labels):
    """rows: output of analyze_image_eval.score_items; labels: item_id -> AI label row."""
    ok = [r for r in rows if "runner_error" not in r and r["item_id"] in labels]
    for r in ok:
        h = labels[r["item_id"]]
        r["_a_coarse"] = COARSE[h["image_category"]]
        r["_a_supports"] = h["hazard_visible"] == "yes" and h["caption_consistency"] in ("high", "moderate")
        r["_a_unusable"] = h["image_category"] == "unusable"
    real = [r for r in ok if r["source_kind"] == "real_commons"]
    vok = [r for r in real if r["vision"]["status"] == "ok"]
    out = {"reference": "AI-reviewed (single annotator, not human; see ai_review/README.md)",
           "n_items": len(ok), "n_real": len(real), "n_real_vision_ok": len(vok)}

    out["provisional_vs_ai_label_quality"] = {
        "confusion_commons_class_to_ai_class": Counter(f"{r['provisional_image_class']}->{r['_a_coarse']}" for r in real),
        "agreement": proportion(sum(r["provisional_image_class"] == r["_a_coarse"] for r in real), len(real)),
        "note": "Commons category membership over-claims hazards; it is not used as ground truth here"}

    out["visual_category_vs_ai"] = {
        "coarse_accuracy": A.rate_with_cluster_ci(vok, lambda r: r["vision_coarse"] == r["_a_coarse"]),
        "macro_f1": macro_f1([r["_a_coarse"] for r in vok], [r["vision_coarse"] for r in vok],
                             ["flood", "landslide", "other", "none"]) if vok else None,
        "confusion": Counter(f"{r['_a_coarse']}->{r['vision_coarse']}" for r in vok),
        "hazard_detected_agreement": A.rate_with_cluster_ci(
            vok, lambda r: bool(r["vision"].get("hazard_detected")) == (labels[r["item_id"]]["hazard_visible"] == "yes"))}

    contra = [r for r in vok if labels[r["item_id"]]["caption_consistency"] == CONTRADICTION]
    flagged = [r for r in vok if r["vision"].get("report_image_consistency") == CONTRADICTION]
    out["contradiction_detection_vs_ai"] = {
        "recall": proportion(sum(r in flagged for r in contra), len(contra)),
        "precision": proportion(sum(labels[r["item_id"]]["caption_consistency"] == CONTRADICTION for r in flagged), len(flagged))}

    tier = [round(abs(float(r["vision"]["evidence_score"]) - float(labels[r["item_id"]]["evidence_tier"])) / 0.05) for r in vok]
    out["evidence_tier_vs_ai"] = {
        "mean_abs_error_in_tiers": statistics.mean(tier) if tier else None,
        "exact": proportion(sum(t == 0 for t in tier), len(tier)),
        "within_one_tier": proportion(sum(t <= 1 for t in tier), len(tier)),
        "note": "AI convention: tier 0 only for unusable images; usable but non-supporting = 0.05"}

    fs = {}
    for name, subset in (("all_non_supporting", [r for r in real if not r["_a_supports"]]),
                         ("non_supporting_vision_ok", [r for r in vok if not r["_a_supports"]]),
                         ("contradiction", [r for r in real if labels[r["item_id"]]["caption_consistency"] == CONTRADICTION]),
                         ("no_hazard_visible", [r for r in real if labels[r["item_id"]]["hazard_visible"] == "no"])):
        b = sum(r["conditions"]["L"]["visual_contribution"] > 0 and not r["conditions"]["C"]["visual_contribution"] > 0 for r in subset)
        c = sum(r["conditions"]["C"]["visual_contribution"] > 0 and not r["conditions"]["L"]["visual_contribution"] > 0 for r in subset)
        fs[name] = {"visual_v2_C": A.rate_with_cluster_ci(subset, lambda r: r["conditions"]["C"]["visual_contribution"] > 0),
                    "legacy_L": A.rate_with_cluster_ci(subset, lambda r: r["conditions"]["L"]["visual_contribution"] > 0),
                    "discordant_L_only": b, "discordant_C_only": c, "mcnemar_exact_p": A.exact_mcnemar(b, c)}
    out["false_support_vs_ai"] = fs
    sup = [r for r in real if r["_a_supports"]]
    out["missed_support_vs_ai"] = {
        "n_supporting": len(sup),
        "visual_v2_C": A.rate_with_cluster_ci(sup, lambda r: r["conditions"]["C"]["visual_contribution"] == 0),
        "legacy_L": A.rate_with_cluster_ci(sup, lambda r: r["conditions"]["L"]["visual_contribution"] == 0)}

    bf = {}
    for code in ("C", "L"):
        acc = [r for r in real if r["conditions"][code]["hazard_type"] != r["extraction"].get("hazard_type")]
        bf[code] = {"n_backfilled": len(acc),
                    "correct_vs_ai": proportion(sum(r["conditions"][code]["hazard_type"] == r["_a_coarse"] for r in acc), len(acc)),
                    "backfilled_where_ai_sees_no_hazard": proportion(sum(r["_a_coarse"] == "none" for r in acc), len(acc))}
    out["backfill_vs_ai"] = bf

    deg = [r for r in ok if r["source_kind"] == "derived_degraded_from_real"]
    out["degraded_images"] = {
        "n": len(deg), "ai_unusable": sum(r["_a_unusable"] for r in deg),
        "model_vision_outcomes": Counter(r["vision_outcome"] for r in deg),
        "degraded_adding_support_C": sum(r["conditions"]["C"]["visual_contribution"] > 0 for r in deg),
        "degraded_adding_support_L": sum(r["conditions"]["L"]["visual_contribution"] > 0 for r in deg)}

    for r in ok:
        for k in ("_a_coarse", "_a_supports", "_a_unusable"):
            r.pop(k, None)
    return out


def tables(m, run_meta):
    pct = lambda d: (f"{d['p']:.1%} ({d['k']}/{d['n']}; 95% CI {d['ci95_wilson'][0]:.1%}–{d['ci95_wilson'][1]:.1%})"
                     if d["n"] else "n/a")
    fs = m["false_support_vs_ai"]
    lines = ["# Results against the AI-reviewed reference", "",
             f"Run commit `{(run_meta.get('source_commit') or '')[:8]}`, split `{run_meta.get('split')}`. Reference: one AI "
             "annotator (Claude Sonnet 5.5), single pass; **not human annotation**; no inter-annotator agreement.", "",
             "## Table A. Visual support on images that do not support the report (AI reference)", "",
             "| Subset | visual-v2 | legacy | discordant legacy-only / v2-only | exact McNemar p |", "|---|---|---|---|---|"]
    for name, d in fs.items():
        lines.append(f"| {name} | {pct(d['visual_v2_C'])} | {pct(d['legacy_L'])} | "
                     f"{d['discordant_L_only']} / {d['discordant_C_only']} | {d['mcnemar_exact_p']:.3g} |")
    ms = m["missed_support_vs_ai"]
    f1 = lambda d: f"{d['macro_f1']:.3f}" if d else "n/a"
    lines += ["", f"Images the reference says support their report ({ms['n_supporting']}) that added nothing: visual-v2 "
                  f"{pct(ms['visual_v2_C'])}; legacy {pct(ms['legacy_L'])}.", "",
              "## Table B. Model vision output vs AI reference", "", "| Measure | Value |", "|---|---|",
              f"| Coarse category accuracy | {pct(m['visual_category_vs_ai']['coarse_accuracy'])} |",
              f"| Macro-F1 (flood/landslide/other/none) | {f1(m['visual_category_vs_ai']['macro_f1'])} |",
              f"| hazard_detected agreement | {pct(m['visual_category_vs_ai']['hazard_detected_agreement'])} |",
              f"| Contradiction recall | {pct(m['contradiction_detection_vs_ai']['recall'])} |",
              f"| Contradiction precision | {pct(m['contradiction_detection_vs_ai']['precision'])} |",
              f"| Evidence tier exact / within one tier | {pct(m['evidence_tier_vs_ai']['exact'])} / {pct(m['evidence_tier_vs_ai']['within_one_tier'])} |",
              f"| Mean absolute tier error | {m['evidence_tier_vs_ai']['mean_abs_error_in_tiers']:.2f} tiers |" if m["evidence_tier_vs_ai"]["mean_abs_error_in_tiers"] is not None else "| Mean absolute tier error | n/a |",
              "", "## Table C. Hazard-type backfill vs AI reference", "",
              "| Policy | Backfilled | Correct | Backfilled where AI sees no hazard |", "|---|---|---|---|"]
    for code, name in (("C", "visual-v2"), ("L", "legacy")):
        d = m["backfill_vs_ai"][code]
        lines.append(f"| {name} | {d['n_backfilled']} | {pct(d['correct_vs_ai'])} | {pct(d['backfilled_where_ai_sees_no_hazard'])} |")
    q = m["provisional_vs_ai_label_quality"]
    lines += ["", "## Label quality: Commons category vs AI reference", "",
              f"Agreement on flood/landslide/none: {pct(q['agreement'])}. Confusion: {dict(q['confusion_commons_class_to_ai_class'])}."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    manifest = {i["item_id"]: i for i in map(json.loads, open(A.MANIFEST, encoding="utf-8"))}
    items_dir = os.path.join(args.run_dir, "items")
    records = [json.load(open(os.path.join(items_dir, n), encoding="utf-8")) for n in sorted(os.listdir(items_dir))]
    run_meta = json.load(open(os.path.join(args.run_dir, "run_meta.json"), encoding="utf-8"))
    m = metrics(A.score_items(records, manifest), load_labels())
    out = os.path.join(args.run_dir, "analysis")
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "ai_reference_metrics.json"), m)
    open(os.path.join(out, "ai_reference_tables.md"), "w", encoding="utf-8").write(tables(m, run_meta))
    print(tables(m, run_meta))


if __name__ == "__main__":
    main()
