"""
Deterministic offline evidence (no API calls, no network).

  python evaluation/icitr_reporting/offline_evidence.py --out <run-dir>

1. Aggregation: direct-product formula vs log-odds implementation.
2. Decision policies: action counts over a fine (confidence, severity) grid,
   the two documented baseline issues, and monotonicity violations.
3. Shadow policy comparison on the archived 29 extraction predictions
   (scores computed without corroboration or rainfall context).
4. Visual policy truth table: legacy vs visual-v2 for each visual outcome.
"""
import argparse
import itertools
import json
import math
import os
import sys
import tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.setdefault("OPENAI_API_KEY", "sk-not-used")
from stats_utils import write_json  # noqa: E402


def product_formula(rs):
    rs = [min(0.95, max(0.05, r)) for r in rs]
    pr, pq = math.prod(rs), math.prod(1 - r for r in rs)
    return pr / (pr + pq) if pr + pq else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    from config import Config
    Config.COMMUNITY_REPORTS_DB = os.path.join(tempfile.mkdtemp(), "empty.db")
    from agent import reporter as rep

    # 1. Aggregation
    cases = {f"n={n}, r={r}": [r] * n for n in (1, 2, 5, 10, 50, 200, 1074, 1100, 5000) for r in (0.3, 0.5, 0.7, 0.9)}
    cases.update({"mixed [0.9, 0.2, 0.6]": [0.9, 0.2, 0.6], "mixed 1100x0.95 + 1100x0.05": [0.95] * 1100 + [0.05] * 1100,
                  "clipped [0.999, 0.001]": [0.999, 0.001]})
    aggregation = {}
    for name, rs in cases.items():
        old, new = product_formula(rs), rep.aggregate_reliabilities(rs)
        aggregation[name] = {"direct_product": old, "log_odds": new, "abs_diff": abs(old - new),
                             "corroboration_points_old": 0.30 * old, "corroboration_points_new": 0.30 * new}
    ordinary = [v["abs_diff"] for k, v in aggregation.items() if not any(x in k for x in ("1074", "1100", "5000"))]

    # 2. Decision policies over a grid (step 0.01 plus boundary neighbours)
    grid = sorted({round(i / 100, 2) for i in range(101)} |
                  {v for b in (0.30, 0.40, 0.70) for v in (math.nextafter(b, 0), math.nextafter(b, 1))})
    cells = list(itertools.product(grid, grid))
    by_policy = {name: Counter(fn(c, s) for c, s in cells) for name, fn in rep.DECISION_POLICIES.items()}
    changed = Counter((rep.decide_action_baseline(c, s), rep.decide_action_candidate(c, s))
                      for c, s in cells if rep.decide_action_baseline(c, s) != rep.decide_action_candidate(c, s))
    rank = {a: i for i, a in enumerate(reversed(rep.ACTION_PRIORITY))}

    def violations(fn):
        n = 0
        for i in range(len(grid) - 1):
            for o in grid:
                n += rank[fn(grid[i + 1], o)] < rank[fn(grid[i], o)]
                n += rank[fn(o, grid[i + 1])] < rank[fn(o, grid[i])]
        return n
    policies = {
        "grid_points": len(cells),
        "action_counts": {k: dict(v) for k, v in by_policy.items()},
        "baseline_to_candidate_changes": {f"{a} -> {b}": n for (a, b), n in changed.items()},
        "monotonicity_violations_adjacent_grid_steps": {k: violations(fn) for k, fn in rep.DECISION_POLICIES.items()},
        "documented_baseline_issues": {
            "low_confidence_high_severity (0.39, 1.0)": {k: fn(0.39, 1.0) for k, fn in rep.DECISION_POLICIES.items()},
            "confidence just below 0.70 at severity 0.50": {k: fn(math.nextafter(0.70, 0), 0.50) for k, fn in rep.DECISION_POLICIES.items()},
            "confidence 0.70 at severity 0.50": {k: fn(0.70, 0.50) for k, fn in rep.DECISION_POLICIES.items()},
        },
        "note": "Grid counts describe the policy rules, not the distribution of real reports.",
    }

    # 3. Shadow comparison on archived predictions
    archived = json.load(open(os.path.join(ROOT, "evaluation", "results", "04_reporting_pipeline.json"), encoding="utf-8"))
    scorer = rep.CommunityReporter()
    shadow = []
    for item in archived["extraction"]["per_item"]:
        fields = item["extracted"]
        scored = scorer.score_report(fields, "archived-eval", 0.0)
        shadow.append({"id": item["id"], "confidence": scored["confidence"], "severity": scored["severity"],
                       "baseline": rep.decide_action_baseline(scored["confidence"], scored["severity"]),
                       "candidate": rep.decide_action_candidate(scored["confidence"], scored["severity"])})
    shadow_summary = {
        "n": len(shadow), "scoring_context": "no corroboration, no rainfall bonus, no image; archived predictions as extracted",
        "baseline_actions": Counter(r["baseline"] for r in shadow), "candidate_actions": Counter(r["candidate"] for r in shadow),
        "changed": [r for r in shadow if r["baseline"] != r["candidate"]],
        "items": shadow,
        "caveat": "Action changes are not validated against any reference priority; they show what the candidate policy would do differently.",
    }

    # 4. Visual policy truth table
    base_text = {"report_domain": "unknown", "hazard_type": "unknown", "category": None, "hazard_scale": "unknown"}
    ok = {"status": "ok", "hazard_detected": True, "hazard_category": "localised_flooding", "possible_condition": "",
          "severity_from_image": "high", "report_image_consistency": "high", "evidence_score": 0.15}
    scenarios = {
        "inference error": {"status": "error"},
        "unsupported image": {"status": "unsupported"},
        "unusable (score 0)": {**ok, "evidence_score": 0.0},
        "no hazard detected": {**ok, "hazard_detected": False, "hazard_category": "none"},
        "contradiction": {**ok, "report_image_consistency": "contradiction"},
        "supporting, low consistency": {**ok, "report_image_consistency": "low", "evidence_score": 0.05},
        "supporting, high consistency": ok,
    }
    truth = {}
    for name, analysis in scenarios.items():
        row = {}
        for mode in (rep.VISUAL_LEGACY, rep.VISUAL_FULL):
            fields, contribution, _ = rep.apply_visual_policy(base_text, analysis, mode)
            row[mode] = {"contribution": contribution, "hazard_type": fields["hazard_type"], "hazard_scale": fields["hazard_scale"]}
        truth[name] = row

    result = {"aggregation": aggregation, "aggregation_max_abs_diff_ordinary_cases": max(ordinary),
              "decision_policies": policies, "shadow_on_archived_predictions": shadow_summary,
              "visual_policy_truth_table": truth}
    write_json(os.path.join(args.out, "offline_evidence.json"), result)
    print(json.dumps({"aggregation_max_abs_diff_ordinary_cases": max(ordinary),
                      "n=1100,r=0.5": aggregation["n=1100, r=0.5"],
                      "monotonicity": policies["monotonicity_violations_adjacent_grid_steps"],
                      "baseline_issues": policies["documented_baseline_issues"],
                      "shadow_changed": [(r["id"], r["baseline"], r["candidate"]) for r in shadow_summary["changed"]],
                      "shadow_baseline": shadow_summary["baseline_actions"], "shadow_candidate": shadow_summary["candidate_actions"],
                      "truth": {k: {m: (v["contribution"], v["hazard_type"]) for m, v in r.items()} for k, r in truth.items()}},
                     indent=1, default=str))


if __name__ == "__main__":
    main()
