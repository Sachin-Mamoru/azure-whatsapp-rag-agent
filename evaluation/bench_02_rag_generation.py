"""
Component Benchmark 2 — RAG Generation Layer (FAISS retrieval + GPT-4o-mini synthesis)

Measures, using the real production RAGSystem.query() coroutine:
  - End-to-end latency (retrieval + LLM synthesis) per query
  - Answer keyword coverage (automatic groundedness proxy)
  - Confidence-score distribution produced by RAGSystem.calculate_confidence()
  - Per-language latency breakdown (en / si / ta)

This benchmark makes real OpenAI chat-completion calls (gpt-4o-mini) against
the 20-item grounded QA test set, so it has a small, bounded API cost.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.common import load_dataset, save_json, summarize
from agent.rag import RAGSystem


def keyword_coverage(answer: str, keywords) -> float:
    if not keywords:
        return 1.0
    answer_lower = answer.lower()
    hits = sum(1 for kw in keywords if kw.lower() in answer_lower)
    return hits / len(keywords)


async def main():
    dataset = load_dataset("qa_testset.json")
    rag = RAGSystem()

    results = []
    for item in dataset:
        t0 = time.perf_counter()
        out = await rag.query(item["question"], language=item["language"])
        elapsed = time.perf_counter() - t0
        answer = out["answer"] if out else ""
        conf = out["confidence"] if out else 0.0
        coverage = keyword_coverage(answer, item["keywords"])
        results.append({
            "id": item["id"], "language": item["language"],
            "latency_s": elapsed, "confidence": conf,
            "keyword_coverage": coverage, "answer_len_chars": len(answer),
        })
        print(f"{item['id']} ({item['language']}): {elapsed:.2f}s conf={conf:.2f} "
              f"coverage={coverage:.2f}")

    latencies = [r["latency_s"] for r in results]
    coverages = [r["keyword_coverage"] for r in results]
    confidences = [r["confidence"] for r in results]

    by_lang = {}
    for lang in set(r["language"] for r in results):
        lang_lat = [r["latency_s"] for r in results if r["language"] == lang]
        by_lang[lang] = summarize(lang_lat)

    save_json("02_rag_generation.json", {
        "n_queries": len(results),
        "latency": summarize(latencies),
        "keyword_coverage": summarize(coverages),
        "confidence": summarize(confidences),
        "latency_by_language": by_lang,
        "per_query": results,
    })


if __name__ == "__main__":
    asyncio.run(main())
