#!/usr/bin/env python3
"""
GasClock - data fetcher.

Samples the last 7 days of Ethereum blocks (one block every ~15 minutes) from
public RPC nodes and aggregates base fees by hour-of-day and day-of-week, so
the site can answer the only question that matters: when is gas actually cheap?

Sampling beats bulk fee-history here: one eth_getBlockByNumber returns both the
timestamp and the base fee, so ~670 samples cost only ~23 batched requests
instead of ~50 heavy ones. Public nodes rate-limit aggressively.

Stdlib only. No API keys. No server.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RPCS = [
    "https://ethereum-rpc.publicnode.com",
    "https://rpc.flashbots.net",
]

BLOCK_SECONDS = 12
DAYS = 7
SAMPLE_EVERY_BLOCKS = 75                 # ~15 min at 12s/block
SAMPLES = DAYS * 24 * 4                  # 4 samples per hour => 672
BATCH = 30
WEI_PER_GWEI = 10 ** 9
OUT = Path(__file__).resolve().parent.parent / "data" / "gas.json"

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}


def rpc(calls, start=0, tries=5):
    """POST a (possibly batched) JSON-RPC call, rotating nodes on failure."""
    body = json.dumps(calls).encode()
    last = None
    for attempt in range(tries):
        node = RPCS[(start + attempt) % len(RPCS)]
        try:
            req = urllib.request.Request(node, data=body, headers=HEADERS)
            with OPENER.open(req, timeout=45) as resp:
                data = json.load(resp)
            return [data] if isinstance(data, dict) else data
        except Exception as exc:                       # noqa: BLE001
            last = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError("rpc failed after %d tries: %r" % (tries, last))


def one(method, params):
    out = rpc([{"jsonrpc": "2.0", "id": 1, "method": method, "params": params}])[0]
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def collect(latest):
    blocks = [latest - i * SAMPLE_EVERY_BLOCKS for i in range(SAMPLES)]
    blocks = [b for b in blocks if b > 0]
    samples, failed = [], 0

    for i in range(0, len(blocks), BATCH):
        group = blocks[i:i + BATCH]
        calls = [
            {"jsonrpc": "2.0", "id": j, "method": "eth_getBlockByNumber",
             "params": [hex(block), False]}
            for j, block in enumerate(group)
        ]
        try:
            by_id = {r.get("id"): r for r in rpc(calls)}
        except Exception as exc:                       # noqa: BLE001
            print("  ! batch %d failed: %r" % (i // BATCH, exc))
            failed += len(group)
            continue

        for j, block in enumerate(group):
            result = (by_id.get(j) or {}).get("result")
            if not result:
                failed += 1
                continue
            samples.append({
                "block": int(result["number"], 16),
                "ts": int(result["timestamp"], 16),
                "fee": int(result["baseFeePerGas"], 16) / WEI_PER_GWEI,
            })
        time.sleep(0.7)

    print("samples: %d  failed: %d" % (len(samples), failed))
    return samples


def mean(values):
    return sum(values) / len(values) if values else None


def aggregate(samples):
    heat = [[[] for _ in range(24)] for _ in range(7)]
    for item in samples:
        when = datetime.fromtimestamp(item["ts"], tz=timezone.utc)
        heat[when.weekday()][when.hour].append(item["fee"])

    heatmap, daily = [], []
    for weekday in range(7):
        row = [mean(heat[weekday][hour]) for hour in range(24)]
        heatmap.append(row)
        daily.append(mean([v for v in row if v is not None]))

    hourly = []
    for hour in range(24):
        flat = [v for weekday in range(7) for v in heat[weekday][hour]]
        hourly.append(mean(flat))

    best = worst = None
    for weekday in range(7):
        for hour in range(24):
            value = heatmap[weekday][hour]
            if value is None:
                continue
            if best is None or value < best["avg_gwei"]:
                best = {"weekday": weekday, "hour": hour, "avg_gwei": value}
            if worst is None or value > worst["avg_gwei"]:
                worst = {"weekday": weekday, "hour": hour, "avg_gwei": value}

    return hourly, daily, heatmap, best, worst


def main():
    latest = int(one("eth_blockNumber", []), 16)
    print("latest block: %d" % latest)

    samples = collect(latest)
    if len(samples) < 100:
        raise SystemExit("too few samples collected")

    samples.sort(key=lambda s: s["block"])
    hourly, daily, heatmap, best, worst = aggregate(samples)

    newest = samples[-1]
    recent = [s["fee"] for s in samples[-8:]]
    recent_avg = mean(recent)

    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_block": latest,
        "window_days": DAYS,
        "sample_blocks": len(samples),
        "current": {
            "base_fee_gwei": round(newest["fee"], 4),
            "recent_avg_gwei": round(recent_avg, 4),
            "low_gwei": round(recent_avg + 0.2, 2),
            "medium_gwei": round(recent_avg + 0.8, 2),
            "high_gwei": round(recent_avg + 1.8, 2),
        },
        "hourly": [None if v is None else round(v, 4) for v in hourly],
        "daily": [None if v is None else round(v, 4) for v in daily],
        "heatmap": [[None if v is None else round(v, 4) for v in row] for row in heatmap],
        "cheapest": {
            "weekday": best["weekday"], "hour": best["hour"],
            "avg_gwei": round(best["avg_gwei"], 4),
        },
        "priciest": {
            "weekday": worst["weekday"], "hour": worst["hour"],
            "avg_gwei": round(worst["avg_gwei"], 4),
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print("wrote %s (%d bytes)" % (OUT, OUT.stat().st_size))
    print("cheapest  weekday=%d hour=%02d UTC  %.2f gwei" % (
        best["weekday"], best["hour"], best["avg_gwei"]))
    print("priciest  weekday=%d hour=%02d UTC  %.2f gwei" % (
        worst["weekday"], worst["hour"], worst["avg_gwei"]))


if __name__ == "__main__":
    main()
