"""
Component Benchmark 8 — End-to-End Orchestrator Throughput / Concurrency

Drives the REAL WhatsAppOrchestrator.process_message() coroutine (full
pipeline: pre-checks -> LangChain agent -> tool execution -> LLM synthesis)
at increasing concurrency levels to characterise how the single FastAPI
container process behaves under concurrent WhatsApp webhook deliveries.

Redis is intentionally pointed at an unreachable local port so every run
uses the documented in-memory session fallback — this isolates agent/LLM
reasoning latency from external Redis network latency, which is reported
separately in the persistence-layer benchmark.

NOTE: this benchmark calls the real OpenAI API once per simulated message
(no outbound WhatsApp Cloud API calls are made — send_whatsapp_message()
lives in app.py and is never invoked here), so cost is bounded by
sum(concurrency_levels) * n_per_level chat-completion calls.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"  # force fast, deterministic fallback
os.environ["COMMUNITY_REPORTS_DB"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "results", "_bench_load_reports.db"
)

from evaluation.common import save_json, summarize
from agent.orchestrator import WhatsAppOrchestrator

TEST_MESSAGES = [
    "What should I do to prepare for a landslide?",
    "How can I make my house safer from flooding?",
    "What's today's weather forecast for Ratnapura?",
    "I can see a crack on the slope behind my house, it's happening now.",
    "Has anyone else reported problems near my area recently?",
    "What are the warning signs of a slope failure?",
    "Is there any active flood alert right now in Kalutara?",
    "Water is rising fast near the main road in Kelaniya.",
]


async def run_one(orchestrator, idx: int):
    phone = f"+94_load_test_{idx}_{time.time_ns()}"
    msg = TEST_MESSAGES[idx % len(TEST_MESSAGES)]
    t0 = time.perf_counter()
    try:
        response = await orchestrator.process_message(phone, msg, message_id=f"m{idx}")
        ok = bool(response)
    except Exception as exc:
        ok = False
        print(f"[load] request {idx} failed: {exc}")
    elapsed = time.perf_counter() - t0
    return {"idx": idx, "ok": ok, "latency_s": elapsed}


async def run_level(orchestrator, concurrency: int, n_requests: int):
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(i):
        async with semaphore:
            return await run_one(orchestrator, i)

    t0 = time.perf_counter()
    results = await asyncio.gather(*[bounded(i) for i in range(n_requests)])
    wall_s = time.perf_counter() - t0

    latencies = [r["latency_s"] for r in results]
    n_ok = sum(r["ok"] for r in results)
    return {
        "concurrency": concurrency, "n_requests": n_requests, "n_ok": n_ok,
        "wall_s": wall_s, "throughput_req_per_s": n_ok / wall_s if wall_s > 0 else 0,
        "latency": summarize(latencies),
    }


async def main():
    orchestrator = WhatsAppOrchestrator()

    # Warm-up call (excludes one-off Python import / first-call JIT-ish overhead from timings)
    await run_one(orchestrator, 9999)

    level_results = []
    for concurrency in [1, 2, 4, 8]:
        res = await run_level(orchestrator, concurrency, n_requests=8)
        level_results.append(res)
        print(f"concurrency={concurrency}: throughput={res['throughput_req_per_s']:.3f} req/s "
              f"p50={res['latency']['p50']:.2f}s p95={res['latency']['p95']:.2f}s "
              f"ok={res['n_ok']}/{res['n_requests']}")

    save_json("08_concurrency_load.json", {"levels": level_results})


if __name__ == "__main__":
    asyncio.run(main())
