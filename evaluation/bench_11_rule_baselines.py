"""
Component Benchmark 11 — Paired rule-based baselines for report detection and extraction

Scores the deterministic keyword components on the SAME items as the stored
LLM benchmark runs, so each LLM component has a paired before/after comparison:
  - detection: detect_report_intent() vs the agent's first tool (results/03_agent_routing.json)
  - extraction: _fallback_extraction() vs _extract_report() (results/04_reporting_pipeline.json)

No API calls: the keyword side runs locally, the LLM side is read from the
stored results. Significance is the exact two-sided McNemar test on discordant pairs.
"""
import os
import sys
from math import comb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.common import load_dataset, load_json_result, save_json, wilson_ci
from agent.reporter import CommunityReporter, detect_report_intent

FIELDS = ["report_domain", "hazard_type", "has_location", "people_at_risk", "ongoing"]


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n)


def paired(base: dict, llm: dict, ok) -> dict:
    ids = list(base)
    k_base = sum(ok(base[i]) for i in ids)
    k_llm = sum(ok(llm[i]) for i in ids)
    b = sum(ok(llm[i]) and not ok(base[i]) for i in ids)
    c = sum(ok(base[i]) and not ok(llm[i]) for i in ids)
    return {"n": len(ids),
            "keyword": {"k": k_base, "p": k_base / len(ids), "ci95_wilson": wilson_ci(k_base, len(ids))},
            "llm": {"k": k_llm, "p": k_llm / len(ids), "ci95_wilson": wilson_ci(k_llm, len(ids))},
            "llm_only_correct": b, "keyword_only_correct": c, "mcnemar_exact_p": mcnemar_exact(b, c)}


def eval_detection() -> dict:
    agent = {q["id"]: q for q in load_json_result("03_agent_routing.json")["per_query"]}
    items = load_dataset("routing_testset.json")
    reports = [i for i in items if i["expected_tool"] == "submit_community_report"]
    others = [i for i in items if i["expected_tool"] != "submit_community_report"]
    kw = {i["id"]: detect_report_intent(i["message"]) for i in reports}
    ag = {i["id"]: agent[i["id"]]["first_tool"] == "submit_community_report" for i in reports}
    return {
        "recall_on_reports": paired(kw, ag, bool),
        "false_alarms_on_non_reports": {
            "n": len(others),
            "keyword": sum(bool(detect_report_intent(i["message"])) for i in others),
            "llm": sum(agent[i["id"]]["first_tool"] == "submit_community_report" for i in others)},
    }


def score(ex: dict, gt: dict) -> dict:
    # Same checks as bench_04_reporting_pipeline.eval_extraction
    return {"report_domain": ex.get("report_domain") == gt["report_domain"],
            "hazard_type": ex.get("hazard_type") == gt["hazard_type"],
            "has_location": bool(ex.get("location_text")) == gt["has_location"],
            "people_at_risk": bool(ex.get("people_at_risk")) == gt["people_at_risk"],
            "ongoing": bool(ex.get("ongoing")) == gt["ongoing"]}


def eval_extraction() -> dict:
    llm_out = {p["id"]: p["extracted"] for p in load_json_result("04_reporting_pipeline.json")["extraction"]["per_item"]}
    items = load_dataset("report_extraction_testset.json")
    kw = {i["id"]: score(CommunityReporter._fallback_extraction(None, i["message"]), i["gt"]) for i in items}
    ll = {i["id"]: score(llm_out[i["id"]], i["gt"]) for i in items}
    out = {f: paired(kw, ll, lambda s, f=f: s[f]) for f in FIELDS}
    out["exact_match"] = paired(kw, ll, lambda s: all(s.values()))
    # The keyword extractor never returns a location, so also report exact match without that field
    out["exact_match_excluding_location"] = paired(
        kw, ll, lambda s: all(v for f, v in s.items() if f != "has_location"))
    return out


if __name__ == "__main__":
    result = {"detection": eval_detection(), "extraction": eval_extraction()}
    d = result["detection"]["recall_on_reports"]
    e = result["extraction"]["exact_match"]
    print(f"Detection recall: keyword {d['keyword']['k']}/{d['n']} vs agent {d['llm']['k']}/{d['n']} "
          f"(McNemar p={d['mcnemar_exact_p']:.4f})")
    print(f"Extraction exact match: keyword {e['keyword']['k']}/{e['n']} vs LLM {e['llm']['k']}/{e['n']} "
          f"(McNemar p={e['mcnemar_exact_p']:.4f})")
    save_json("11_rule_baselines.json", result)
