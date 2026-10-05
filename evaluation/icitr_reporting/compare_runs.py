"""
Run-to-run repeatability of the live model outputs.

  python evaluation/icitr_reporting/compare_runs.py --run-a <dir> --run-b <dir> --out <file.json>

Both runs use identical frozen code, prompts and inputs. This quantifies how much
of any single run's result is sampling noise from the model at temperature 0.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import analyze_image_eval as A  # noqa: E402
from stats_utils import cohen_kappa, proportion, write_json  # noqa: E402


def load(run_dir):
    manifest = {i["item_id"]: i for i in map(json.loads, open(A.MANIFEST, encoding="utf-8"))}
    items = os.path.join(run_dir, "items")
    records = [json.load(open(os.path.join(items, n), encoding="utf-8")) for n in sorted(os.listdir(items))]
    return {r["item_id"]: r for r in A.score_items(records, manifest)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-a", required=True)
    parser.add_argument("--run-b", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    a, b = load(args.run_a), load(args.run_b)
    ids = sorted(set(a) & set(b))
    both = [i for i in ids if "runner_error" not in a[i] and "runner_error" not in b[i]]
    ok = [i for i in both if a[i]["vision"]["status"] == "ok" and b[i]["vision"]["status"] == "ok"]

    def same(field_fn, subset):
        k = sum(field_fn(a[i]) == field_fn(b[i]) for i in subset)
        return proportion(k, len(subset))

    result = {
        "n_items_both": len(both), "n_both_vision_ok": len(ok),
        "vision_status_same": same(lambda r: r["vision"]["status"], both),
        "extraction_hazard_type_same": same(lambda r: r["extraction"].get("hazard_type"), both),
        "visual_outcome_same": same(lambda r: r["vision_outcome"], both),
        "vision_coarse_category_same": same(lambda r: r["vision_coarse"], ok),
        "vision_coarse_category_kappa": cohen_kappa([a[i]["vision_coarse"] for i in ok], [b[i]["vision_coarse"] for i in ok]),
        "evidence_tier_same": same(lambda r: r["vision"].get("evidence_score"), ok),
        "consistency_label_same": same(lambda r: r["vision"].get("report_image_consistency"), ok),
        "visual_v2_support_decision_same": same(lambda r: r["conditions"]["C"]["visual_contribution"] > 0, both),
        "baseline_action_same": same(lambda r: r["conditions"]["C"]["baseline_action"], both),
        "note": "run A and B use identical frozen code, prompts, inputs and temperature 0",
    }
    write_json(args.out, result)
    print(json.dumps({k: (f"{v['p']:.3f} ({v['k']}/{v['n']})" if isinstance(v, dict) and "p" in v else v)
                      for k, v in result.items()}, indent=1))


if __name__ == "__main__":
    main()
