"""
Offline analysis of a run_image_eval.py run directory.

  python evaluation/icitr_reporting/analyze_image_eval.py --run-dir <dir>

Writes <dir>/analysis/{per_item_predictions.jsonl, metrics.json, tables.md, *.png}.

Reference labels used here are of two kinds and are reported as such:
- constructed: the claim encoded in the templated caption (by construction);
- provisional: the Commons source category of the image (not human-annotated).
No metric in this file uses human annotations; none are available yet.
Ablation conditions are applied to the same stored model outputs (paired):
  A text_only, B score_only, C score_backfill (production, visual-v2),
  L legacy_v1 (pre-change visual handling, for comparison only).
"""
import argparse
import json
import math
import os
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
from stats_utils import cluster_bootstrap, macro_f1, proportion, write_json  # noqa: E402

MANIFEST = os.path.join(HERE, "image_data", "manifest.jsonl")
CONDITIONS = {"A": "text_only", "B": "score_only", "C": "score_backfill", "L": "legacy_v1"}
COARSE = {"localised_flooding": "flood", "slope_instability": "landslide", "ground_cracking": "landslide",
          "none": "none", "drainage_issue": "other", "access_obstruction": "other", "other": "other"}


def exact_mcnemar(b, c):
    """Two-sided exact McNemar p-value for discordant counts b, c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def summarize(values):
    if not values:
        return {"n": 0}
    v = sorted(values)
    q = lambda p: v[min(len(v) - 1, int(round(p * (len(v) - 1))))]
    return {"n": len(v), "mean": statistics.mean(v), "p50": q(0.5), "p90": q(0.9), "p95": q(0.95), "max": v[-1]}


def rate_with_cluster_ci(rows, predicate, cluster_key="event_group"):
    k = sum(1 for r in rows if predicate(r))
    out = proportion(k, len(rows))
    groups = defaultdict(list)
    for r in rows:
        groups[r[cluster_key]].append(1.0 if predicate(r) else 0.0)
    out["ci95_cluster_bootstrap"] = list(cluster_bootstrap(groups, statistics.mean)) if rows else None
    out["n_clusters"] = len(groups)
    return out


def score_items(records, manifest):
    from config import Config
    tmp = tempfile.mkdtemp(prefix="icitr_analysis_")
    Config.COMMUNITY_REPORTS_DB = os.path.join(tmp, "empty.db")
    from agent import reporter as rep
    scorer = rep.CommunityReporter()  # empty DB: no corroboration; empty cache: no rainfall bonus
    rows = []
    for rec in records:
        item = manifest[rec["item_id"]]
        row = {k: item[k] for k in ("item_id", "split", "source_kind", "event_group", "contributor_group",
                                    "provisional_image_class", "caption_condition", "caption_language",
                                    "text_claim_class", "expected_image_supports_report", "duplicate_of",
                                    "transformation", "image_sha256")}
        if "runner_error" in rec:
            row["runner_error"] = rec["runner_error"]
            rows.append(row)
            continue
        extracted = rec["extraction"]
        vision = rec["vision"]
        public = {k: v for k, v in extracted.items() if not k.startswith("_")}
        row["extraction_status"] = extracted.get("_extraction_meta", {}).get("status")
        row["extraction"] = public
        row["vision"] = vision
        row["vision_outcome"] = rep.classify_visual_outcome(vision)
        row["vision_coarse"] = COARSE.get(vision.get("hazard_category")) if vision.get("status") == "ok" else None
        row["would_ask_clarification"] = not public.get("location_text") or not public.get("location_specific")
        row["conditions"] = {}
        for code, mode in CONDITIONS.items():
            t0 = time.perf_counter()
            fields, contribution, decisions = rep.apply_visual_policy(public, vision, mode)
            scored = scorer.score_report(fields, "eval-contributor", contribution)
            row["conditions"][code] = {
                "visual_contribution": contribution,
                "hazard_type": fields.get("hazard_type"), "report_domain": fields.get("report_domain"),
                "hazard_scale": fields.get("hazard_scale"),
                "confidence": scored["confidence"], "severity": scored["severity"],
                "baseline_action": rep.decide_action_baseline(scored["confidence"], scored["severity"]),
                "candidate_action": rep.decide_action_candidate(scored["confidence"], scored["severity"]),
                "backfill": decisions, "scoring_s": time.perf_counter() - t0,
            }
        stages = {a["stage"]: a for a in rec["attempts"]}
        row["latency_s"] = {
            "extraction": (stages.get("extraction", {}).get("meta") or {}).get("latency_s"),
            "vision": (stages.get("vision", {}).get("meta") or {}).get("latency_s"),
        }
        row["tokens"] = {s: ((stages.get(s, {}).get("meta") or {}).get("token_usage") or {}) for s in ("extraction", "vision")}
        row["model_snapshots"] = sorted({(a.get("meta") or {}).get("model_snapshot") for a in rec["attempts"]} - {None})
        row["retries"] = len(rec.get("failures", []))
        rows.append(row)
    return rows


def analyze(rows, run_meta):
    ok = [r for r in rows if "runner_error" not in r]
    real = [r for r in ok if r["source_kind"] == "real_commons"]
    m = {"n_items": len(rows), "n_runner_errors": len(rows) - len(ok), "n_real": len(real),
         "label_provenance": {
             "text_reference": "constructed (claim encoded in templated caption)",
             "image_reference": "provisional (Commons source category; not human-annotated)",
             "human_annotations": "none available for this run"}}

    # Failures and model identifiers
    m["extraction_status"] = Counter(r["extraction_status"] for r in ok)
    m["vision_status"] = Counter(r["vision"]["status"] for r in ok)
    m["vision_errors"] = Counter(r["vision"].get("error") for r in ok if r["vision"]["status"] != "ok")
    m["model_snapshots"] = sorted({s for r in ok for s in r["model_snapshots"]})
    m["retries_total"] = sum(r["retries"] for r in ok)

    # 1. Text extraction against the constructed caption claim
    def expected_text_hazard(r):
        return r["text_claim_class"] if r["text_claim_class"] != "none" else "unknown"
    gold = [expected_text_hazard(r) for r in real]
    pred = [r["extraction"].get("hazard_type") for r in real]
    m["text_extraction"] = {
        "hazard_type_agreement": rate_with_cluster_ci(real, lambda r: r["extraction"].get("hazard_type") == expected_text_hazard(r)),
        "hazard_type_macro_f1": macro_f1(gold, pred, ["flood", "landslide", "unknown"]),
        "location_presence": proportion(sum(bool(r["extraction"].get("location_text")) for r in real), len(real)),
        "would_ask_clarification": proportion(sum(r["would_ask_clarification"] for r in real), len(real)),
        "by_language": {lang: proportion(sum(r["extraction"].get("hazard_type") == expected_text_hazard(r) for r in sub), len(sub))
                        for lang in ("en", "si", "ta") for sub in [[r for r in real if r["caption_language"] == lang]]},
        "note": "location_presence is presence of location text, not geolocation accuracy",
    }

    # 2. Visual category against the provisional source-category class
    vok = [r for r in real if r["vision"]["status"] == "ok"]
    m["visual_category"] = {
        "n_scored": len(vok),
        "coarse_accuracy": rate_with_cluster_ci(vok, lambda r: r["vision_coarse"] == r["provisional_image_class"]),
        "macro_f1": macro_f1([r["provisional_image_class"] for r in vok], [r["vision_coarse"] for r in vok],
                             ["flood", "landslide", "none"]),
        "confusion": Counter(f"{r['provisional_image_class']}->{r['vision_coarse']}" for r in vok),
        "hazard_detected_agreement": rate_with_cluster_ci(
            vok, lambda r: bool(r["vision"].get("hazard_detected")) == (r["provisional_image_class"] != "none")),
        "by_language_of_caption": {lang: proportion(sum(r["vision_coarse"] == r["provisional_image_class"] for r in sub), len(sub))
                                   for lang in ("en", "si", "ta") for sub in [[r for r in vok if r["caption_language"] == lang]]},
    }
    m["evidence_tier"] = {
        "ordinal_error": "not computed: no reference evidence tiers (requires human annotation)",
        "distribution_by_class_and_condition": {
            f"{c}/{cond}": Counter(str(r["vision"].get("evidence_score")) for r in vok
                                   if r["provisional_image_class"] == c and r["caption_condition"] == cond)
            for c, cond in sorted({(r["provisional_image_class"], r["caption_condition"]) for r in vok})},
        "consistency_by_condition": {
            cond: Counter(r["vision"].get("report_image_consistency") for r in vok if r["caption_condition"] == cond)
            for cond in sorted({r["caption_condition"] for r in vok})},
    }

    # 3. False support and missed support: visual-v2 (C) vs legacy (L), paired
    def supports(r, code):
        return r["conditions"][code]["visual_contribution"] > 0
    neg = [r for r in real if not r["expected_image_supports_report"]]
    pos = [r for r in real if r["expected_image_supports_report"]]
    fs = {}
    for name, subset in (("all_non_supporting", neg),
                         ("contradiction_hazard_image", [r for r in neg if r["caption_condition"] == "contradiction"]),
                         ("no_hazard_image", [r for r in neg if r["provisional_image_class"] == "none"])):
        b = sum(supports(r, "L") and not supports(r, "C") for r in subset)
        c = sum(supports(r, "C") and not supports(r, "L") for r in subset)
        fs[name] = {"visual_v2_C": rate_with_cluster_ci(subset, lambda r: supports(r, "C")),
                    "legacy_L": rate_with_cluster_ci(subset, lambda r: supports(r, "L")),
                    "discordant_L_only": b, "discordant_C_only": c, "mcnemar_exact_p": exact_mcnemar(b, c)}
    m["false_support"] = fs
    b = sum(supports(r, "L") and not supports(r, "C") for r in pos)
    m["missed_support_on_expected_support"] = {
        "visual_v2_C": rate_with_cluster_ci(pos, lambda r: not supports(r, "C")),
        "legacy_L": rate_with_cluster_ci(pos, lambda r: not supports(r, "L")),
        "discordant_L_supports_only": b, "mcnemar_exact_p": exact_mcnemar(b, sum(supports(r, "C") and not supports(r, "L") for r in pos))}

    # 4. Backfill coverage and correctness (hazard_type), C vs L
    def backfilled(r, code):
        return r["conditions"][code]["hazard_type"] != r["extraction"].get("hazard_type")
    eligible = [r for r in real if r["extraction"].get("hazard_type") in (None, "unknown")]
    bf = {}
    for code in ("C", "L"):
        acc = [r for r in eligible if backfilled(r, code)]
        bf[code] = {
            "eligible_text_unknown": len(eligible),
            "coverage": proportion(len(acc), len(eligible)),
            "correct_vs_provisional": proportion(sum(r["conditions"][code]["hazard_type"] == r["provisional_image_class"]
                                                     for r in acc), len(acc)),
            "backfilled_on_no_hazard_image": proportion(sum(r["provisional_image_class"] == "none" for r in acc), len(acc)),
            "eligible_by_class": Counter(r["provisional_image_class"] for r in eligible),
        }
    m["backfill_hazard_type"] = bf
    m["backfill_reasons_C"] = Counter(d["reason"] for r in real for d in r["conditions"]["C"]["backfill"])

    # 5. Paired A/B/C ablation (descriptive; no outcome labels for actions)
    ab = {}
    for code in CONDITIONS:
        conf = [r["conditions"][code]["confidence"] for r in real]
        ab[code] = {"mean_confidence": statistics.mean(conf) if conf else None,
                    "baseline_actions": Counter(r["conditions"][code]["baseline_action"] for r in real),
                    "candidate_actions": Counter(r["conditions"][code]["candidate_action"] for r in real)}
    for x, y in (("B", "A"), ("C", "B"), ("C", "A"), ("C", "L")):
        groups = defaultdict(list)
        for r in real:
            groups[r["event_group"]].append(r["conditions"][x]["confidence"] - r["conditions"][y]["confidence"])
        diffs = [d for g in groups.values() for d in g]
        ab[f"{x}-{y}_confidence_diff"] = {"mean": statistics.mean(diffs) if diffs else None,
                                          "ci95_cluster_bootstrap": list(cluster_bootstrap(groups, statistics.mean)),
                                          "baseline_action_changed": sum(r["conditions"][x]["baseline_action"] != r["conditions"][y]["baseline_action"] for r in real)}
    sparse_hazard = [r for r in real if r["caption_condition"] == "sparse" and r["provisional_image_class"] != "none"]
    a_ok = [r["conditions"]["A"]["hazard_type"] == r["provisional_image_class"] for r in sparse_hazard]
    c_ok = [r["conditions"]["C"]["hazard_type"] == r["provisional_image_class"] for r in sparse_hazard]
    ab["sparse_caption_hazard_type_vs_provisional"] = {
        "A_text_only": proportion(sum(a_ok), len(a_ok)), "C_with_backfill": proportion(sum(c_ok), len(c_ok)),
        "mcnemar_exact_p": exact_mcnemar(sum(c and not a for a, c in zip(a_ok, c_ok)), sum(a and not c for a, c in zip(a_ok, c_ok)))}
    m["ablation"] = ab
    m["ablation_D_contributor_weights"] = "not run: no valid contributor histories exist for these items (no simulation substituted)"
    m["severe_report_review_recall"] = "not computed: no independently labelled reference priorities"

    # 6. Latency, tokens, cost (paths exercised: extraction + vision + offline scoring)
    ext = [r["latency_s"]["extraction"] for r in ok if r["latency_s"]["extraction"] is not None]
    vis = [r["latency_s"]["vision"] for r in ok if r["latency_s"]["vision"] is not None]
    e2e = [r["latency_s"]["extraction"] + r["latency_s"]["vision"] + r["conditions"]["C"]["scoring_s"]
           for r in ok if r["latency_s"]["extraction"] and r["latency_s"]["vision"]]
    m["latency_s"] = {"extraction": summarize(ext), "vision": summarize(vis),
                      "sequential_model_path_plus_scoring": summarize(e2e),
                      "scoring_offline": summarize([r["conditions"]["C"]["scoring_s"] for r in ok]),
                      "scope": "model calls measured from this client; excludes WhatsApp transport, media download and DB write"}
    tok = defaultdict(int)
    for r in ok:
        for stage, usage in r["tokens"].items():
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                tok[f"{stage}_{k}"] += usage.get(k, 0) or 0
    m["tokens"] = dict(tok)

    # 7. Duplicate and degradation controls
    by_id = {r["item_id"]: r for r in ok}
    pairs = defaultdict(list)
    for r in ok:
        if r["duplicate_of"] and r["duplicate_of"] in by_id:
            pairs[r["source_kind"]].append((by_id[r["duplicate_of"]], r))
    ctrl = {}
    for kind, ps in pairs.items():
        ctrl[kind] = {
            "n_pairs": len(ps),
            "identical_hash": sum(a["image_sha256"] == b["image_sha256"] for a, b in ps),
            "same_vision_category": sum(a["vision"].get("hazard_category") == b["vision"].get("hazard_category") for a, b in ps),
            "same_evidence_tier": sum(a["vision"].get("evidence_score") == b["vision"].get("evidence_score") for a, b in ps),
            "same_visual_outcome": sum(a["vision_outcome"] == b["vision_outcome"] for a, b in ps),
            "mean_evidence_change": statistics.mean([(b["vision"].get("evidence_score") or 0) - (a["vision"].get("evidence_score") or 0)
                                                     for a, b in ps]) if ps else None,
            "derived_outcomes": Counter(b["vision_outcome"] for _, b in ps),
            "by_transformation": Counter(b["transformation"] for _, b in ps),
        }
    m["duplicate_and_degradation_controls"] = ctrl
    m["run"] = {k: run_meta.get(k) for k in ("source_commit", "split", "model_alias", "manifest_sha256", "started_at",
                                             "prompt_digests")}
    return m


def tables(m):
    fs = m["false_support"]
    pct = lambda d: f"{d['p']:.1%} ({d['k']}/{d['n']}; 95% CI {d['ci95_wilson'][0]:.1%}–{d['ci95_wilson'][1]:.1%})" if d["n"] else "n/a"
    lines = ["# Image evaluation tables", "",
             f"Run commit `{(m['run']['source_commit'] or '')[:8]}`, split `{m['run']['split']}`, "
             f"model alias `{m['run']['model_alias']}`, snapshots {', '.join(m['model_snapshots'])}.", "",
             "Reference labels: text = constructed caption claim; image = provisional Commons source category. "
             "No human annotations were used.", "",
             "## Table A. Visual support on items whose image should not support the report", "",
             "| Subset | visual-v2 (C) | legacy (L) | discordant L-only / C-only | exact McNemar p |", "|---|---|---|---|---|"]
    for name, d in fs.items():
        lines.append(f"| {name} | {pct(d['visual_v2_C'])} | {pct(d['legacy_L'])} | "
                     f"{d['discordant_L_only']} / {d['discordant_C_only']} | {d['mcnemar_exact_p']:.3g} |")
    ms = m["missed_support_on_expected_support"]
    lines += ["", f"Items whose image should support the report but contributed nothing: visual-v2 {pct(ms['visual_v2_C'])}; "
                  f"legacy {pct(ms['legacy_L'])}.", "",
              "## Table B. Extraction and visual classification", "", "| Measure | Value |", "|---|---|",
              f"| Text hazard type vs constructed claim | {pct(m['text_extraction']['hazard_type_agreement'])} |",
              f"| Text hazard type macro-F1 (flood/landslide/unknown) | {m['text_extraction']['hazard_type_macro_f1']['macro_f1']:.3f} |",
              f"| Visual coarse class vs provisional class | {pct(m['visual_category']['coarse_accuracy'])} |",
              f"| Visual macro-F1 (flood/landslide/none) | {m['visual_category']['macro_f1']['macro_f1']:.3f} |",
              f"| hazard_detected vs provisional hazard presence | {pct(m['visual_category']['hazard_detected_agreement'])} |", "",
              "## Table C. Hazard-type backfill (text left hazard type unknown)", "",
              "| Policy | Coverage | Correct vs provisional | Backfilled on no-hazard image |", "|---|---|---|---|"]
    for code, name in (("C", "visual-v2"), ("L", "legacy")):
        d = m["backfill_hazard_type"][code]
        lines.append(f"| {name} | {pct(d['coverage'])} | {pct(d['correct_vs_provisional'])} | {pct(d['backfilled_on_no_hazard_image'])} |")
    lat = m["latency_s"]
    lines += ["", "## Table D. Latency (seconds)", "", "| Stage | n | mean | p50 | p95 |", "|---|---|---|---|---|"]
    for stage in ("extraction", "vision", "sequential_model_path_plus_scoring"):
        d = lat[stage]
        if d.get("n"):
            lines.append(f"| {stage} | {d['n']} | {d['mean']:.2f} | {d['p50']:.2f} | {d['p95']:.2f} |")
    return "\n".join(lines) + "\n"


def figures(m, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fs = m["false_support"]
    names = list(fs)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    for k, (code, label, color) in enumerate((("visual_v2_C", "visual-v2", "#2a6f97"), ("legacy_L", "legacy", "#bc6c25"))):
        vals = [fs[n][code]["p"] for n in names]
        errs = [[v - fs[n][code]["ci95_wilson"][0] for v, n in zip(vals, names)],
                [fs[n][code]["ci95_wilson"][1] - v for v, n in zip(vals, names)]]
        ax.bar([i + k * 0.38 for i in range(len(names))], vals, 0.38, yerr=errs, capsize=3, label=label, color=color)
    ax.set_xticks([i + 0.19 for i in range(len(names))])
    ax.set_xticklabels([n.replace("_", " ") for n in names], fontsize=8)
    ax.set_ylabel("share with visual support > 0")
    ax.set_ylim(0, 1)
    ax.legend(frameon=False)
    ax.set_title("Visual support on non-supporting images (provisional labels)", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_false_support.png"), dpi=200)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    manifest = {i["item_id"]: i for i in map(json.loads, open(MANIFEST, encoding="utf-8"))}
    items_dir = os.path.join(args.run_dir, "items")
    records = [json.load(open(os.path.join(items_dir, n), encoding="utf-8")) for n in sorted(os.listdir(items_dir))]
    run_meta = json.load(open(os.path.join(args.run_dir, "run_meta.json"), encoding="utf-8"))
    rows = score_items(records, manifest)
    out = os.path.join(args.run_dir, "analysis")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "per_item_predictions.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    m = analyze(rows, run_meta)
    write_json(os.path.join(out, "metrics.json"), m)
    open(os.path.join(out, "tables.md"), "w", encoding="utf-8").write(tables(m))
    figures(m, out)
    print(tables(m))


if __name__ == "__main__":
    main()
