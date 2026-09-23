"""
Component Benchmark 9 — RAG vs. Closed-Book Baseline Ablation (+ LLM-as-judge)

Addresses the missing-baseline gap in the technical evaluation: compares the
production RAGSystem.query() (grounded in the FAISS knowledge base) against a
closed-book baseline that answers the SAME questions with the SAME LLM
(gpt-4o-mini) but with NO retrieved context — i.e. the ablation isolates the
marginal value of retrieval itself, holding the generator constant.

Both conditions' answers are scored by an independent LLM judge (gpt-4o,
falling back to gpt-4o-mini — see llm_judge.py) for faithfulness, relevance,
and a hallucination flag, in addition to the existing keyword-coverage proxy.

Uses a fixed, seeded 30-item subsample of qa_testset.json (60 items) to bound
API cost while still tripling the sample size used in the original ablation-free
report (n=20 -> effectively n=30 paired comparisons here).
"""
import asyncio
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.common import load_dataset, save_json, summarize, wilson_ci
from evaluation.llm_judge import LLMJudge
from agent.rag import RAGSystem
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from config import Config

N_SAMPLE = 30
SEED = 123


def keyword_coverage(answer: str, keywords) -> float:
    if not keywords:
        return 1.0
    answer_lower = answer.lower()
    hits = sum(1 for kw in keywords if kw.lower() in answer_lower)
    return hits / len(keywords)


_LANG_NAMES = {"si": "Sinhala", "ta": "Tamil", "en": "English"}


async def closed_book_answer(llm: ChatOpenAI, question: str, language: str) -> str:
    """Same generator model as production, but with NO retrieved KB context —
    isolates what the LLM 'knows' on its own vs. what RAG grounds it in."""
    lang_name = _LANG_NAMES.get(language, "English")
    system_prompt = (
        f"You are a helpful safety and hazard awareness assistant for Sri Lanka.\n"
        f"Answer the user's question from your own general knowledge — you have "
        f"NO access to any external document or knowledge base right now.\n"
        f"ALWAYS respond in {lang_name}.\n"
        f"Keep answers clear and actionable."
    )
    result = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=question),
    ])
    return result.content


async def main():
    full_dataset = load_dataset("qa_testset.json")
    rng = random.Random(SEED)
    sample = rng.sample(full_dataset, min(N_SAMPLE, len(full_dataset)))

    rag = RAGSystem()
    closed_book_llm = ChatOpenAI(
        model=Config.MODEL_NAME, openai_api_key=Config.OPENAI_API_KEY, temperature=0.1,
        request_timeout=20, max_retries=1,
    )
    judge = LLMJudge(preferred_model="gpt-4o")

    results = []
    for item in sample:
        q, lang, keywords = item["question"], item["language"], item["keywords"]

        # RAG condition
        t0 = time.perf_counter()
        rag_out = await rag.query(q, language=lang)
        rag_latency = time.perf_counter() - t0
        rag_answer = rag_out["answer"] if rag_out else ""

        # Closed-book condition (same generator model, no retrieval)
        t0 = time.perf_counter()
        cb_answer = await closed_book_answer(closed_book_llm, q, lang)
        cb_latency = time.perf_counter() - t0

        # Retrieve the same context RAG used, purely so the judge can check
        # faithfulness against it for the RAG condition (closed-book gets no context).
        docs = rag.vectorstore.similarity_search(q, k=4) if rag.vectorstore else []
        context = "\n\n".join(d.page_content for d in docs)

        rag_judge = await judge.score(q, rag_answer, context=context)
        cb_judge = await judge.score(q, cb_answer, context="")

        row = {
            "id": item["id"], "language": lang, "question": q,
            "rag": {
                "answer": rag_answer, "latency_s": rag_latency,
                "keyword_coverage": keyword_coverage(rag_answer, keywords),
                "faithfulness": rag_judge.get("faithfulness"),
                "relevance": rag_judge.get("relevance"),
                "hallucination_flag": rag_judge.get("hallucination_flag"),
            },
            "closed_book": {
                "answer": cb_answer, "latency_s": cb_latency,
                "keyword_coverage": keyword_coverage(cb_answer, keywords),
                "faithfulness": cb_judge.get("faithfulness"),
                "relevance": cb_judge.get("relevance"),
                "hallucination_flag": cb_judge.get("hallucination_flag"),
            },
            "judge_model": rag_judge.get("judge_model"),
        }
        results.append(row)
        print(f"{item['id']}: RAG faith={row['rag']['faithfulness']} hallu={row['rag']['hallucination_flag']} "
              f"| CB faith={row['closed_book']['faithfulness']} hallu={row['closed_book']['hallucination_flag']}")

    def col(cond, field):
        return [r[cond][field] for r in results if r[cond][field] is not None]

    rag_hallu = [1 if r["rag"]["hallucination_flag"] else 0 for r in results if r["rag"]["hallucination_flag"] is not None]
    cb_hallu = [1 if r["closed_book"]["hallucination_flag"] else 0 for r in results if r["closed_book"]["hallucination_flag"] is not None]

    summary = {
        "n": len(results),
        "judge_model": results[0]["judge_model"] if results else None,
        "rag": {
            "latency": summarize(col("rag", "latency_s")),
            "keyword_coverage": summarize(col("rag", "keyword_coverage")),
            "faithfulness": summarize(col("rag", "faithfulness")),
            "relevance": summarize(col("rag", "relevance")),
            "hallucination_rate": sum(rag_hallu) / len(rag_hallu) if rag_hallu else None,
            "hallucination_rate_ci95": wilson_ci(sum(rag_hallu), len(rag_hallu)) if rag_hallu else None,
        },
        "closed_book": {
            "latency": summarize(col("closed_book", "latency_s")),
            "keyword_coverage": summarize(col("closed_book", "keyword_coverage")),
            "faithfulness": summarize(col("closed_book", "faithfulness")),
            "relevance": summarize(col("closed_book", "relevance")),
            "hallucination_rate": sum(cb_hallu) / len(cb_hallu) if cb_hallu else None,
            "hallucination_rate_ci95": wilson_ci(sum(cb_hallu), len(cb_hallu)) if cb_hallu else None,
        },
        "per_item": results,
    }

    print(f"\nRAG hallucination rate: {summary['rag']['hallucination_rate']}")
    print(f"Closed-book hallucination rate: {summary['closed_book']['hallucination_rate']}")
    save_json("09_rag_vs_closedbook_baseline.json", summary)


if __name__ == "__main__":
    asyncio.run(main())
