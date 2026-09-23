"""
Component Benchmark 7 — Language Detection Layer (deterministic pre-check, Layer 1)

Measures the Unicode-script-range detector used in
WhatsAppOrchestrator._detect_script_language() — the very first, LLM-free
gate every inbound message passes through. Since it never calls an LLM,
this benchmark validates it is both fast (sub-millisecond) and accurate
on a hand-labelled trilingual test set (English / Sinhala / Tamil,
including short commands, digits, and language-switch phrases).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.common import load_dataset, save_json, summarize
from agent.orchestrator import WhatsAppOrchestrator


def main():
    dataset = load_dataset("language_testset.json")

    latencies = []
    correct = 0
    confusion = {}
    per_item = []

    for item in dataset:
        expected = item["language"]
        t0 = time.perf_counter()
        detected = WhatsAppOrchestrator._detect_script_language(item["text"])
        latencies.append(time.perf_counter() - t0)
        # detector returns None for ASCII/English text (no script signal)
        detected_norm = detected or "en"
        is_correct = detected_norm == expected
        correct += int(is_correct)
        confusion.setdefault(expected, {}).setdefault(detected_norm, 0)
        confusion[expected][detected_norm] += 1
        per_item.append({
            "id": item["id"], "expected": expected, "detected": detected_norm,
            "correct": is_correct, "latency_s": latencies[-1],
        })

    accuracy = correct / len(dataset)
    print(f"Language-detection accuracy: {accuracy:.3f} over n={len(dataset)}")
    print(f"Mean latency: {summarize(latencies)['mean']*1e6:.2f} microseconds")

    save_json("07_language_detection.json", {
        "n_items": len(dataset),
        "accuracy": accuracy,
        "confusion_matrix": confusion,
        "latency_seconds": summarize(latencies),
        "per_item": per_item,
    })


if __name__ == "__main__":
    main()
