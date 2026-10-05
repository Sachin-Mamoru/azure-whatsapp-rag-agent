"""
Live, resumable image-report evaluation runner.

  python evaluation/icitr_reporting/run_image_eval.py --split dev  --run-dir <dir> [--max-cost-usd 5]
  python evaluation/icitr_reporting/run_image_eval.py --split test --run-dir <dir> --frozen <freeze.json>

For every manifest item it calls the production extraction
(CommunityReporter._extract_report) and vision assessment
(CommunityReporter._analyze_image_evidence) exactly once and stores raw
outputs, failures, per-stage latency and token usage in <run-dir>/items/.
Ablations and metrics are computed offline from these files
(analyze_image_eval.py), so conditions A/B/C are paired on identical outputs.

Re-running with the same --run-dir skips completed items. Transient API
errors and timeouts are retried; schema failures are outcomes and are not
retried. The run stops before a call would exceed --max-cost-usd.
"""
import argparse
import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

# Assumed list prices (USD per 1M tokens) for cost accounting only; checked
# against the provider's price page on the run date and recorded in run_meta.
PRICING = {"gpt-4o-mini": {"input": 0.15, "output": 0.60}}
WORST_CASE_CALL_USD = 0.02
MANIFEST = os.path.join(HERE, "image_data", "manifest.jsonl")
# Files that must not change between the freeze record and a test-split run.
FROZEN_PATHS = ["agent/reporter.py", "config.py", "evaluation/icitr_reporting/run_image_eval.py",
                "evaluation/icitr_reporting/analyze_image_eval.py", "evaluation/icitr_reporting/analyze_ai_reference.py",
                "evaluation/icitr_reporting/ai_review/ai_review_labels.csv",
                "evaluation/icitr_reporting/image_data/manifest.jsonl"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def backoff_s(reason, attempt):
    """Rate-limit windows are per minute, so wait long; other transient errors back off briefly."""
    return 20 * (attempt + 1) if "RateLimit" in (reason or "") else 2 ** attempt


def call_cost(meta, model_alias):
    usage = (meta or {}).get("token_usage") or {}
    price = PRICING.get(model_alias)
    if not price or not usage:
        return 0.0
    return (usage.get("prompt_tokens", 0) * price["input"] + usage.get("completion_tokens", 0) * price["output"]) / 1e6


def spent(items_dir, model_alias):
    total = 0.0
    for name in os.listdir(items_dir):
        rec = json.load(open(os.path.join(items_dir, name), encoding="utf-8"))
        for attempt in rec.get("attempts", []):
            total += call_cost(attempt.get("meta"), model_alias)
    return total


def run_meta(args, reporter, manifest_items):
    from config import Config
    pip = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join([os.path.basename(sys.executable), *sys.argv]),
        "source_commit": git("rev-parse", "HEAD"),
        "source_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "working_tree_status": git("status", "--porcelain"),
        "working_tree_diff_sha256": sha256_text(git("diff", "HEAD")),
        "python": sys.version, "platform": platform.platform(),
        "pip_freeze_sha256": sha256_text(pip), "pip_freeze": pip.splitlines(),
        "model_alias": Config.MODEL_NAME,
        "model_snapshot_note": "per-call snapshot is recorded from the API response (meta.model_snapshot)",
        "temperature": 0.0,
        "timeouts_s": {"extraction": Config.EXTRACTION_TIMEOUT_S, "vision": Config.VISION_TIMEOUT_S},
        "pricing_assumption_usd_per_1m": PRICING, "max_cost_usd": args.max_cost_usd,
        "prompts": {"extraction": reporter.EXTRACTION_PROMPT, "vision_template": reporter.VISION_PROMPT_TEMPLATE},
        "prompt_digests": {"extraction": reporter.prompt_digest(reporter.EXTRACTION_PROMPT),
                           "vision": reporter.prompt_digest(reporter.VISION_PROMPT_TEMPLATE)},
        "manifest_sha256": hashlib.sha256(open(MANIFEST, "rb").read()).hexdigest(),
        "split": args.split, "n_items": len(manifest_items),
        "frozen_record": args.frozen,
    }


async def run_item(reporter, item, retries):
    image_path = os.path.join(HERE, "image_data", item["image_file"])
    data = open(image_path, "rb").read()
    if hashlib.sha256(data).hexdigest() != item["image_sha256"]:
        raise RuntimeError(f"{item['item_id']}: image hash mismatch")
    record = {"item_id": item["item_id"], "attempts": [], "failures": []}

    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        extracted = await reporter._extract_report(item["caption_text"], item["caption_language"])
        meta = extracted.get("_extraction_meta") or {}
        record["attempts"].append({"stage": "extraction", "n": attempt, "wall_s": time.perf_counter() - t0,
                                   "status": meta.get("status"), "reason": meta.get("reason"),
                                   "meta": {k: meta.get(k) for k in ("model_snapshot", "token_usage", "latency_s")}})
        reason = meta.get("reason") or ""
        if meta.get("status") == "ok" or not (reason.startswith("api_error") or reason == "timeout"):
            break
        record["failures"].append({"stage": "extraction", "reason": reason})
        await asyncio.sleep(backoff_s(reason, attempt))
    record["extraction"] = extracted

    description = extracted.get("description") or item["caption_text"]
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        analysis = await reporter._analyze_image_evidence(data, "image/jpeg", description, item["caption_language"])
        record["attempts"].append({"stage": "vision", "n": attempt, "wall_s": time.perf_counter() - t0,
                                   "status": analysis.get("status"), "reason": analysis.get("error"),
                                   "meta": {k: analysis.get(k) for k in ("model_snapshot", "token_usage", "latency_s")}})
        err = analysis.get("error") or ""
        if analysis["status"] != "error" or not (err.startswith("api_error") or err == "timeout"):
            break
        record["failures"].append({"stage": "vision", "reason": err})
        await asyncio.sleep(backoff_s(err, attempt))
    analysis.pop("image_path", None)
    record["vision"] = analysis
    record["completed_at"] = datetime.now(timezone.utc).isoformat()
    return record


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--max-cost-usd", type=float, default=5.0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--min-interval-s", type=float, default=0.0,
                        help="minimum seconds between item starts (keeps tokens/minute under the account limit)")
    parser.add_argument("--redo-failed", action="store_true",
                        help="move items that ended in an API error/timeout to failed_attempts/ and run them again")
    parser.add_argument("--frozen", help="freeze record that must match the current prompts/policies (test split)")
    args = parser.parse_args()

    from config import Config
    tmp_images = tempfile.mkdtemp(prefix="icitr_eval_images_")
    Config.REPORT_IMAGES_DIR = tmp_images
    Config.COMMUNITY_REPORTS_DB = os.path.join(tmp_images, "unused.db")
    from agent.reporter import CommunityReporter
    reporter = CommunityReporter()

    if args.split == "test":
        if not args.frozen:
            sys.exit("--frozen is required for the test split")
        frozen = json.load(open(args.frozen, encoding="utf-8"))
        current = {"extraction": reporter.prompt_digest(reporter.EXTRACTION_PROMPT),
                   "vision": reporter.prompt_digest(reporter.VISION_PROMPT_TEMPLATE)}
        changed = git("diff", "--name-only", frozen["source_commit"], "HEAD", "--", *FROZEN_PATHS)
        dirty = git("status", "--porcelain", "--", *FROZEN_PATHS)
        if frozen["prompt_digests"] != current or changed or dirty:
            sys.exit(f"frozen code/prompts changed since {frozen['source_commit'][:8]}: {changed or dirty}; "
                     "refusing to run the test split")

    items = [json.loads(l) for l in open(MANIFEST, encoding="utf-8")]
    items = [i for i in items if i["split"] == args.split]
    items_dir = os.path.join(args.run_dir, "items")
    os.makedirs(items_dir, exist_ok=True)
    meta_path = os.path.join(args.run_dir, "run_meta.json")
    if not os.path.exists(meta_path):
        json.dump(run_meta(args, reporter, items), open(meta_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    if args.redo_failed:
        failed_dir = os.path.join(args.run_dir, "failed_attempts")
        os.makedirs(failed_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        for name in os.listdir(items_dir):
            rec = json.load(open(os.path.join(items_dir, name), encoding="utf-8"))
            reasons = [(rec.get("extraction", {}).get("_extraction_meta") or {}).get("reason") or "",
                       rec.get("vision", {}).get("error") or ""]
            if "runner_error" in rec or any(r.startswith("api_error") or r == "timeout" for r in reasons):
                os.replace(os.path.join(items_dir, name), os.path.join(failed_dir, f"{name[:-5]}.{stamp}.json"))

    done = {n[:-5] for n in os.listdir(items_dir)}
    todo = [i for i in items if i["item_id"] not in done]
    print(f"{len(done)} done, {len(todo)} to run; spent so far ${spent(items_dir, Config.MODEL_NAME):.4f}")
    sem = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    stopped = {"cap": False}
    last_start = [0.0]

    async def worker(item):
        async with sem:
            async with lock:
                if spent(items_dir, Config.MODEL_NAME) + 2 * WORST_CASE_CALL_USD * args.concurrency > args.max_cost_usd:
                    stopped["cap"] = True
                    return
                wait = args.min_interval_s - (time.monotonic() - last_start[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                last_start[0] = time.monotonic()
            if stopped["cap"]:
                return
            try:
                record = await run_item(reporter, item, args.retries)
            except Exception as exc:  # recorded, never hidden
                record = {"item_id": item["item_id"], "runner_error": f"{type(exc).__name__}: {exc}",
                          "attempts": [], "failures": [{"stage": "runner", "reason": str(exc)}]}
            path = os.path.join(items_dir, f"{item['item_id']}.json")
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(record, f, indent=1, ensure_ascii=False, default=str)
            os.replace(path + ".tmp", path)
            print(f"{item['item_id']} extraction={record.get('extraction', {}).get('_extraction_meta', {}).get('status')} "
                  f"vision={record.get('vision', {}).get('status')}")

    await asyncio.gather(*(worker(i) for i in todo))
    total = spent(items_dir, Config.MODEL_NAME)
    status = {"finished_at": datetime.now(timezone.utc).isoformat(), "items_completed": len(os.listdir(items_dir)),
              "items_in_split": len(items), "stopped_by_cost_cap": stopped["cap"], "estimated_cost_usd": total}
    json.dump(status, open(os.path.join(args.run_dir, "run_status.json"), "w"), indent=2)
    print(json.dumps(status, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
