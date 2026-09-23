"""
Component Benchmark 3 — LangChain Tool-Calling Agent (routing layer)

Measures, using the real DisasterAgent (GPT-4o-mini function calling):
  - Tool-selection accuracy against a hand-labelled routing test set
  - Confusion matrix between the 4 tools
  - End-to-end agent latency (LLM reasoning + tool execution) per call
  - Latency broken down by expected tool type

A dedicated, disposable SQLite DB is used for agent_tool_calls logging so the
benchmark never touches production data.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["COMMUNITY_REPORTS_DB"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "results", "_bench_community_reports.db"
)

from evaluation.common import load_dataset, save_json, summarize
from agent.rag import RAGSystem
from agent.reporter import CommunityReporter
from agent.tools import WebSearchTool
from agent.disaster_agent import DisasterAgent
import hashlib
import sqlite3
from config import Config

TOOLS = ["query_knowledge_base", "search_web", "submit_community_report", "get_community_observations"]


def hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode("utf-8")).hexdigest()[:16]


def get_called_tools(db_path: str, user_hash: str, after_iso: str):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT tool_name FROM agent_tool_calls WHERE user_hash=? AND called_at>=? ORDER BY id",
            (user_hash, after_iso),
        ).fetchall()
    return [r[0] for r in rows]


async def main():
    dataset = load_dataset("routing_testset.json")

    rag = RAGSystem()
    reporter = CommunityReporter()
    web_search = WebSearchTool()
    agent = DisasterAgent(rag, reporter, web_search)

    results = []
    confusion = {t: {t2: 0 for t2 in TOOLS} for t in TOOLS}

    for i, item in enumerate(dataset):
        phone = f"+94_bench_test_{item['id']}"
        uh = hash_phone(phone)
        from datetime import datetime, timezone
        t_start_iso = datetime.now(timezone.utc).isoformat()

        t0 = time.perf_counter()
        response = await agent.ainvoke(item["message"], item["language"], phone, conversation_history=[])
        elapsed = time.perf_counter() - t0

        called = get_called_tools(reporter.db_path, uh, t_start_iso)
        first_tool = called[0] if called else "none"
        expected = item["expected_tool"]
        correct = first_tool == expected
        if expected in confusion and first_tool in confusion[expected]:
            confusion[expected][first_tool] += 1

        results.append({
            "id": item["id"], "language": item["language"], "expected_tool": expected,
            "called_tools": called, "first_tool": first_tool, "correct": correct,
            "latency_s": elapsed, "response_len": len(response or ""),
        })
        print(f"{item['id']}: expected={expected} got={first_tool} "
              f"{'OK' if correct else 'MISS'} ({elapsed:.2f}s)")

    accuracy = sum(r["correct"] for r in results) / len(results)
    latencies = [r["latency_s"] for r in results]

    by_tool_latency = {}
    for t in TOOLS:
        lat = [r["latency_s"] for r in results if r["expected_tool"] == t]
        if lat:
            by_tool_latency[t] = summarize(lat)

    save_json("03_agent_routing.json", {
        "n_queries": len(results),
        "accuracy": accuracy,
        "confusion_matrix": confusion,
        "latency": summarize(latencies),
        "latency_by_expected_tool": by_tool_latency,
        "per_query": results,
    })
    print(f"\nRouting accuracy: {accuracy:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
