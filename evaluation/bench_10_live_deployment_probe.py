"""
Component Benchmark 10 — Live Azure Deployment Network Probe

Closes the "tested locally, not the actual deployed system" gap: hits the
REAL, currently-running Azure Container Apps instance
(whatsapp-agent.wittysand-7a29c211.eastus.azurecontainerapps.io) over the
public internet, using only read-only, side-effect-free endpoints:

  GET /              (root health message)
  GET /health/token  (WhatsApp token validity check — read-only)

No /webhook POST is sent (that would attempt a real outbound WhatsApp Cloud
API call from the container). This benchmark therefore measures genuine
production network round-trip latency (TLS handshake, Azure Container Apps
ingress, FastAPI dispatch) without any side effects on WhatsApp or user data.

Also records the live replica/scale configuration via `az containerapp show`
so the paper can report actual (not documented) autoscaling behaviour.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from evaluation.common import save_json, summarize

BASE_URL = "https://whatsapp-agent.wittysand-7a29c211.eastus.azurecontainerapps.io"
N_REQUESTS = 30


def probe_endpoint(path: str, n: int):
    latencies = []
    statuses = []
    for i in range(n):
        t0 = time.perf_counter()
        try:
            resp = requests.get(f"{BASE_URL}{path}", timeout=15)
            statuses.append(resp.status_code)
        except Exception as exc:
            statuses.append(f"error:{exc}")
        latencies.append(time.perf_counter() - t0)
    return latencies, statuses


def get_live_scale_config():
    try:
        out = subprocess.run(
            ["az", "containerapp", "show", "-g", "rg-whatsapp-agent", "-n", "whatsapp-agent",
             "--query", "{minReplicas:properties.template.scale.minReplicas,"
                         "maxReplicas:properties.template.scale.maxReplicas,"
                         "activeRevision:properties.latestRevisionName,"
                         "provisioningState:properties.provisioningState}",
             "-o", "json"],
            capture_output=True, text=True, timeout=30,
        )
        return json.loads(out.stdout) if out.returncode == 0 else {"error": out.stderr}
    except Exception as exc:
        return {"error": str(exc)}


def main():
    scale_config = get_live_scale_config()
    print("Live scale config:", scale_config)

    root_latencies, root_statuses = probe_endpoint("/", N_REQUESTS)
    token_latencies, token_statuses = probe_endpoint("/health/token", N_REQUESTS)

    result = {
        "base_url": BASE_URL,
        "live_scale_config": scale_config,
        "root_endpoint": {
            "n": N_REQUESTS,
            "latency": summarize(root_latencies),
            "first_request_latency_s": root_latencies[0] if root_latencies else None,
            "warm_latency_after_first": summarize(root_latencies[1:]) if len(root_latencies) > 1 else None,
            "status_codes": root_statuses,
        },
        "health_token_endpoint": {
            "n": N_REQUESTS,
            "latency": summarize(token_latencies),
            "status_codes": token_statuses,
        },
    }
    print(f"root: mean={result['root_endpoint']['latency']['mean']*1000:.1f}ms "
          f"first={result['root_endpoint']['first_request_latency_s']*1000:.1f}ms")
    print(f"health/token: mean={result['health_token_endpoint']['latency']['mean']*1000:.1f}ms")

    save_json("10_live_deployment_probe.json", result)


if __name__ == "__main__":
    main()
