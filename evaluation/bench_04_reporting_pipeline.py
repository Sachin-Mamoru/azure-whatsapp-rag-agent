"""
Component Benchmark 4 — Community Reporting Pipeline (VGI intake)

Two sub-benchmarks:
  A) detect_report_intent() — deterministic keyword classifier.
     Precision/recall measured using:
       positives = report_extraction_testset.json (hazard/infra reports)
       negatives = qa_testset.json (advisory questions, should NOT trigger)
  B) LLM-based structured extraction (_extract_report) — real GPT-4o-mini
     zero-shot JSON extraction, evaluated field-by-field against
     hand-labelled ground truth, plus per-stage latency (extraction call,
     rainfall lookup via Open-Meteo, deterministic confidence/severity scoring).
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["COMMUNITY_REPORTS_DB"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "results", "_bench_reporter_pipeline.db"
)

from evaluation.common import load_dataset, save_json, summarize
from agent.reporter import CommunityReporter, detect_report_intent


def eval_intent_detection():
    reports = load_dataset("report_extraction_testset.json")
    questions = load_dataset("qa_testset.json")

    tp = fn = tn = fp = 0
    latencies = []
    for item in reports:
        t0 = time.perf_counter()
        pred = detect_report_intent(item["message"])
        latencies.append(time.perf_counter() - t0)
        if pred:
            tp += 1
        else:
            fn += 1
    for item in questions:
        t0 = time.perf_counter()
        pred = detect_report_intent(item["question"])
        latencies.append(time.perf_counter() - t0)
        if pred:
            fp += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "tp": tp, "fn": fn, "tn": tn, "fp": fp,
        "precision": precision, "recall": recall, "f1": f1,
        "latency": summarize(latencies),
    }


async def eval_extraction():
    dataset = load_dataset("report_extraction_testset.json")
    reporter = CommunityReporter()

    field_correct = {"report_domain": 0, "hazard_type": 0, "has_location": 0,
                      "people_at_risk": 0, "ongoing": 0}
    latencies = []
    per_item = []

    for item in dataset:
        t0 = time.perf_counter()
        extracted = await reporter._extract_report(item["message"], item["language"])
        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)

        gt = item["gt"]
        pred_has_location = bool(extracted.get("location_text"))
        checks = {
            "report_domain": extracted.get("report_domain") == gt["report_domain"],
            "hazard_type": extracted.get("hazard_type") == gt["hazard_type"],
            "has_location": pred_has_location == gt["has_location"],
            "people_at_risk": bool(extracted.get("people_at_risk")) == gt["people_at_risk"],
            "ongoing": bool(extracted.get("ongoing")) == gt["ongoing"],
        }
        for k, v in checks.items():
            field_correct[k] += int(v)

        per_item.append({
            "id": item["id"], "language": item["language"], "latency_s": elapsed,
            "extracted": extracted, "checks": checks,
            "exact_match": all(checks.values()),
        })
        print(f"{item['id']}: {elapsed:.2f}s fields_ok={sum(checks.values())}/5")

    n = len(dataset)
    field_accuracy = {k: v / n for k, v in field_correct.items()}
    exact_match_rate = sum(p["exact_match"] for p in per_item) / n

    # ── Stage-level latency breakdown on a subset (extraction vs rainfall vs scoring) ──
    stage_timings = []
    for item in dataset[:6]:
        t0 = time.perf_counter()
        extracted = await reporter._extract_report(item["message"], item["language"])
        t_extract = time.perf_counter() - t0

        t0 = time.perf_counter()
        loc = extracted.get("location_text") or ""
        if loc:
            await reporter._fetch_rainfall_for_location(loc)
        t_rainfall = time.perf_counter() - t0

        t0 = time.perf_counter()
        conf = reporter._score_confidence(extracted, f"+94_bench_{item['id']}")
        sev = reporter._score_severity(extracted)
        _ = reporter._decide_action(conf, sev)
        t_score = time.perf_counter() - t0

        stage_timings.append({
            "id": item["id"], "extract_s": t_extract, "rainfall_s": t_rainfall, "score_s": t_score,
        })

    return {
        "n_items": n,
        "field_accuracy": field_accuracy,
        "exact_match_rate": exact_match_rate,
        "latency": summarize(latencies),
        "stage_timings": stage_timings,
        "per_item": per_item,
    }


async def main():
    intent_results = eval_intent_detection()
    print(f"Intent detection: P={intent_results['precision']:.3f} "
          f"R={intent_results['recall']:.3f} F1={intent_results['f1']:.3f}")

    extraction_results = await eval_extraction()
    print(f"Extraction exact-match rate: {extraction_results['exact_match_rate']:.3f}")

    save_json("04_reporting_pipeline.json", {
        "intent_detection": intent_results,
        "extraction": extraction_results,
    })


if __name__ == "__main__":
    asyncio.run(main())
